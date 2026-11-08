"""Own only uniquely named, synthetic E2E resources; never touch live volumes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
LOCAL_PROTECTED_PROJECT = 'atlas-loadtest-20261102-manual2c8g'

def call(*args, capture=True):
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=capture).stdout

def inventory():
    configured = os.environ.get('ATLAS_E2E_PROTECTED_PROJECT')
    project = configured or LOCAL_PROTECTED_PROJECT
    ids = call('docker', 'ps', '-aq', '--filter', f'label=com.docker.compose.project={project}').split()
    if not ids and configured is None:
        return []
    if len(ids) != 5:
        raise RuntimeError(f'Expected five protected application/chain services in {project}')
    rows=json.loads(call('docker','inspect',*ids))
    return [{k:r[k] for k in ('Id','Name','Image','Mounts','HostConfig','RestartCount')}|
            {'state':{k:r['State'].get(k) for k in ('StartedAt','Status','OOMKilled')}} for r in sorted(rows,key=lambda r:r['Name'])]

def paths(run):
    if not re.fullmatch(r'e2e-[a-z0-9][a-z0-9-]{0,43}',run): raise ValueError('Invalid isolated run id')
    out=ROOT/'.artifacts'/run
    return out,'atlas-'+run

def start(args):
    out,project=paths(args.run_id)
    if out.exists(): raise RuntimeError('New run id required; evidence must not be overwritten')
    if call('docker','ps','-aq','--filter',f'name={project}-').strip(): raise RuntimeError('Container identity already exists')
    volume = project + '_e2e-data'
    if volume in call('docker', 'volume', 'ls', '--format', '{{.Name}}').splitlines():
        raise RuntimeError('Synthetic volume identity already exists')
    sample = args.receipt_bundle or ROOT / '.artifacts/browser-compute-20261105/compat-bundle.zip'
    if args.receipt_bundle and not sample.is_file():
        raise ValueError('The specified receipt bundle does not exist')
    protected = inventory()
    out.mkdir();(out/'protected-before.json').write_text(json.dumps(protected,indent=2))
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'backend/app').rglob('*.py'))}
    (out/'source-pins.json').write_text(json.dumps(sources,indent=2))
    config={
      'name':project,
      'services':{
       'api':{'image':args.api_image,'platform':'linux/amd64','init':True,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'pids_limit':256,
        'mem_limit':f'{args.memory-(256 if args.memory>1920 else 128)}m','memswap_limit':f'{args.memory-(256 if args.memory>1920 else 128)}m','cpus':args.cpus-(0.2 if args.cpus>2 else 0.1),
        'environment':{'ATLAS_E2E_ISOLATED':'1','ATLAS_DATA_DIR':'/work/data','ATLAS_OBJECT_ROOT':'/work/data/objects','ATLAS_COMPUTE_MODE':'browser','ATLAS_CLOUD_PROOF_GENERATION':'false','ATLAS_COOKIE_SECURE':'false','ATLAS_ALLOW_REGISTRATION':'true' if args.allow_registration else 'false','ATLAS_ALLOWED_ORIGINS':f'http://127.0.0.1:{args.port}','ATLAS_TRUSTED_PROXY_IPS':'*','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'},
        'entrypoint':['python','/e2e/bootstrap.py'],'volumes':['e2e-data:/work',f'{ROOT}/tools/e2e:/e2e:ro'],
        'tmpfs':['/tmp:size=256m,mode=1777,exec,nosuid'],'networks':['internal'],
        'healthcheck':{'test':['CMD','python','-c',"import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=3)"],'interval':'5s','timeout':'5s','start_period':'120s','retries':10}},
       'web':{'image':args.web_image,'platform':'linux/amd64','init':True,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'pids_limit':64,'mem_limit':'256m' if args.memory>1920 else '128m','memswap_limit':'256m' if args.memory>1920 else '128m','cpus':0.2 if args.cpus>2 else 0.1,
        'environment':{'ATLAS_TLS_PROXY_IP':'127.0.0.1'},'ports':[f'127.0.0.1:{args.port}:8080'],'networks':['internal','edge'],'tmpfs':['/tmp:size=64m,mode=1777,noexec,nosuid'],
        'depends_on':{'api':{'condition':'service_healthy'}},
        'healthcheck':{'test':['CMD','wget','-q','--spider','http://127.0.0.1:8080/healthz'],'interval':'5s','timeout':'5s','retries':10}}
      },'volumes':{'e2e-data':{}},'networks':{'internal':{'internal':True},'edge':{}}}
    if sample.is_file():
        config['services']['api']['volumes'].append(str(sample.resolve())+':/sample-bundle.zip:ro')
    path=out/'compose.json';path.write_text(json.dumps(config,indent=2))
    manifest={'schema':'atlas.e2e-run/v1','run_id':args.run_id,'project':project,'port':args.port,'origin':f'http://127.0.0.1:{args.port}','volume':volume,'api_image':args.api_image,'web_image':args.web_image,'images':{name:json.loads(call('docker','image','inspect',tag))[0]['Id'] for name,tag in [('api',args.api_image),('web',args.web_image)]},'synthetic_only':True,'registration_enabled':args.allow_registration}
    (out/'run.json').write_text(json.dumps(manifest,indent=2))
    call('docker','volume','create',manifest['volume'])
    call('docker','run','--rm','--platform','linux/amd64','--network','none','--user','0','--entrypoint','python','-v',manifest['volume']+':/work',args.api_image,'-c',"import os; os.chown('/work',10001,10001)")
    if args.restore_run_id:
        original,_=paths(args.restore_run_id);previous=json.loads((original/'run.json').read_text())
        proof=json.loads((original/'backup-manifest.json').read_text())
        if not previous['synthetic_only'] or not proof['synthetic_only']:raise RuntimeError('Synthetic backup required')
        archive=original/'backup.tar.gz'
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=proof['archive_sha256']:raise RuntimeError('Backup checksum mismatch')
        # Strip the single validated work prefix, preserving only this new volume.
        code="import tarfile; a=tarfile.open('/backup.tar.gz'); members=a.getmembers(); assert all(m.name=='work' or m.name.startswith('work/') for m in members); [(setattr(m,'name',m.name[5:])) for m in members if m.name.startswith('work/')]; a.extractall('/work',members=[m for m in members if m.name and m.name!='work'],filter='data')"
        call('docker','run','--rm','--platform','linux/amd64','--network','none','--user','10001','--entrypoint','python','-v',manifest['volume']+':/work','-v',str(archive)+':/backup.tar.gz:ro',args.api_image,'-c',code)
    with (out/'startup.log').open('w') as log:
      subprocess.run(['docker','compose','-f',str(path),'up','-d','--no-build','--wait','--wait-timeout','300'],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    api=call('docker','compose','-f',str(path),'ps','-q','api').strip()
    call('docker','cp',api+':/work/fixture.json',str(out/'fixture.json'))
    if inventory()!=json.loads((out/'protected-before.json').read_text()):raise RuntimeError('Protected services changed')
    print(json.dumps(manifest))

def stop(args):
    out,project=paths(args.run_id);manifest=json.loads((out/'run.json').read_text())
    assert manifest['project']==project and manifest['synthetic_only'] and manifest['volume']==project+'_e2e-data'
    config=json.loads((out/'compose.json').read_text())
    if config.get('name')!=project or config.get('volumes')!={'e2e-data':{}}:
        raise RuntimeError('Refusing to stop a project with an unexpected name or volume configuration')
    for s in config['services'].values():
      for v in s.get('volumes',[]):assert not any(x in v for x in ('atlas-release-','supervisor-state','supervisor-mysql'))
    call('docker','compose','-p',project,'-f',str(out/'compose.json'),'down','--volumes')
    unchanged=inventory()==json.loads((out/'protected-before.json').read_text());(out/'protected-after.json').write_text(json.dumps({'unchanged':unchanged,'services':inventory()},indent=2));assert unchanged
    print('Only synthetic run resources removed; protected services unchanged')

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','stop']);p.add_argument('--run-id',required=True)
    p.add_argument('--allow-registration',action='store_true',help='Enable registration only in this isolated project')
    p.add_argument('--receipt-bundle', type=Path, help='Pinned existing v2 receipt bundle for Proof scenarios')
    p.add_argument('--restore-run-id');p.add_argument('--port',type=int,default=18221);p.add_argument('--api-image',default='atlas-quant-api:r23-local');p.add_argument('--web-image',default='atlas-quant-web:r23-local');p.add_argument('--cpus',type=float,default=2);p.add_argument('--memory',type=int,default=1920)
    args=p.parse_args()
    if not 1024<args.port<65536 or args.port==18095 or not 1<=args.cpus<=4 or not 512<=args.memory<=4096:p.error('Unsafe port or unsupported resource budget')
    (start if args.action=='start' else stop)(args)
if __name__=='__main__':main()
