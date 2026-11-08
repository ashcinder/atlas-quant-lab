"""Fail-closed evidence gate. This tool never deploys or mutates Docker."""
import argparse,json,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('evidence_directory',type=Path)
p.add_argument('--manifest',type=Path,default=root/'tools/e2e/case-manifest.json',help='Use a separate acceptance manifest for an explicitly agreed test scope')
a=p.parse_args();folder=a.evidence_directory
manifest=json.loads(a.manifest.read_text());checks={};counts={'passed':0,'failed':0,'blocked':0,'unverified':0}
def walk(suite):
 for spec in suite.get('specs',[]):
  for t in spec.get('tests',[]):yield spec,t
 for child in suite.get('suites',[]):yield from walk(child)
for browser in manifest['browsers']:
 path=folder/(browser+'.json');tests=[]
 if path.exists():
  r=json.loads(path.read_text());tests=[(s,t) for suite in r.get('suites',[]) for s,t in walk(suite) if t.get('projectName')==browser]
 for prefix in manifest['required_case_prefixes']:
  matching=[t for s,t in tests if s['title'].startswith(prefix+' ') or s['title']==prefix]
  checks[browser+':'+prefix]=bool(matching) and all(t.get('status')=='expected' and t.get('results') and all(x.get('status')=='passed' for x in t['results']) for t in matching)
  statuses={x.get('status') for t in matching for x in t.get('results',[])}
  counts['passed' if checks[browser+':'+prefix] else 'failed' if statuses-{'skipped'} else 'unverified']+=1
supp=json.loads((folder/'supplements.json').read_text()) if (folder/'supplements.json').exists() else {}
for key in manifest['required_supplements']:
 if key=='resources_and_recovery':continue
 item=supp.get(key,{});status=item.get('status','unverified');evidence=folder/item.get('evidence','missing')
 checks[key]=status=='passed' and evidence.is_file()
 counts[status if status in counts and (status!='passed' or checks[key]) else 'unverified']+=1

def read_evidence(name):
 path=folder/name
 return json.loads(path.read_text()) if path.is_file() else {}

run=read_evidence('performance-run.json')
pin=read_evidence('performance-pin.json')
candidate=read_evidence('release-candidate.json')
load=read_evidence('performance.json')
recovery=read_evidence('recovery-result.json')
capacity=read_evidence('capacity-summary.json')
persistence=read_evidence('persistence-result.json')
images=run.get('images')
project=run.get('project')
fingerprint=pin.get('source_fingerprint')
pinned=bool(images and project and fingerprint) and (
 candidate.get('images')==images and candidate.get('source_fingerprint')==fingerprint
 and run.get('synthetic_only') is True and pin.get('backend_image_matches') is True
 and pin.get('served_dist_matches') is True
 and pin.get('image_ids')=={f'/{project}-{role}-1':image for role,image in images.items()}
)

def same_run(item):
 return pinned and item.get('images')==images and item.get('source_fingerprint')==fingerprint and item.get('run_id')==run.get('run_id')

def record(name, passed, complete):
 checks[name]=passed
 counts['passed' if passed else 'failed' if complete else 'unverified']+=1

record('50_browser_hour', same_run(load) and load.get('success') is True
       and load.get('requested_users')==50 and load.get('duration_seconds')==3600
       and load.get('actual_contexts')==50 and load.get('elapsed_seconds',0)>=3600
       and load.get('benchmark_dataset',{}).get('count')==1000,
       bool(load and run and pin and candidate))
record('resources_and_recovery', all(same_run(item) for item in (recovery,capacity,persistence))
       and recovery.get('passed') is True and recovery.get('full_ten_minutes') is True
       and recovery.get('elapsed_seconds',0)>=600 and recovery.get('runtime_instances')==4
       and capacity.get('resource_sampling_complete') is True and capacity.get('health_ok') is True
       and capacity.get('browser_rss_after_close_zero') is True and persistence.get('passed') is True,
       bool(recovery and capacity and persistence and run and pin and candidate))
out={'schema':'atlas.release-gate/v1','passed':all(checks.values()),'counts':counts,'checks':checks,'missing_or_failed':[k for k,v in checks.items() if not v]};(folder/'gate-result.json').write_text(json.dumps(out,indent=2));print(json.dumps(out,indent=2));sys.exit(0 if out['passed'] else 2)
