"""Read-only restore integrity checks, plus real login/receipt and restart recovery."""
import argparse,json,subprocess,time,urllib.request,http.cookiejar
from pathlib import Path
from control import inventory
p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('restored',type=Path);a=p.parse_args()
s=json.loads((a.source/'run.json').read_text());r=json.loads((a.restored/'run.json').read_text());assert s['synthetic_only'] and r['synthetic_only'] and s['volume']!=r['volume'];before=inventory()
code='''import json,sys,hashlib,sqlite3
from pathlib import Path
m=json.load(sys.stdin);root=Path('/work');bad=[];counts={}
for name,digest in m['files'].items():
 p=root/name
 if name in m['databases']:continue
 if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:bad.append(name)
for name,tables in m['databases'].items():
 db=sqlite3.connect(root/name);assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok';counts[name]={t:db.execute('SELECT COUNT(*) FROM "'+t.replace('"','""')+'"').fetchone()[0] for t in tables}
print(json.dumps({'file_hashes_match':not bad,'mismatched_paths':bad,'database_counts_match':counts==m['databases'],'databases':len(counts)}))
'''
result=subprocess.run(['docker','exec','-i',r['project']+'-api-1','python','-c',code],input=(a.source/'backup-manifest.json').read_text(),text=True,capture_output=True,check=True);value=json.loads(result.stdout);assert value['file_hashes_match'] and value['database_counts_match'],value
cookies=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookies))
def get(path,data=None):
 req=urllib.request.Request(r['origin']+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
 with client.open(req,timeout=30) as response:return json.load(response)
assert get('/api/login',{'email':'author@e2e.example.test','password':'Only-E2E-Fixture-2026!'})
fixture=json.loads((a.restored/'fixture.json').read_text());assert get('/api/v1/quantjudge/zk-proofs/'+fixture['proof_id']+'/verify',{})['valid']
value['historical_real_receipt_verified']=True
for service in ['api','web']:
 subprocess.run(['docker','compose','-f',str(a.restored/'compose.json'),'restart',service],capture_output=True,check=True)
 deadline=time.monotonic()+120
 while True:
  try:
   get('/api/session');get('/api/ledger');break
  except Exception:
   if time.monotonic()>deadline:raise
   time.sleep(1)
 value[service+'_restart_cookie_and_ledger_recovered']=True
value['protected_unchanged']=inventory()==before;assert value['protected_unchanged'];value['passed']=True
(a.restored/'recovery-result.json').write_text(json.dumps(value,indent=2));print(json.dumps(value))
