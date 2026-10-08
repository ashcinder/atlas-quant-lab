#!/usr/bin/env python3
"""Isolated, persistent competition chain. Never rebuild an existing run root."""
import argparse, json, os, signal, subprocess, time, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = Path.home() / '.local/share/atlas-competition-20261008'
MYSQL = Path('/usr/local/mysql/bin')

def rpc(root, method, params=None):
    settings = json.loads((root / 'demo.json').read_text())
    req = urllib.request.Request(f"http://127.0.0.1:{settings['rpc_port']}", data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params or []}).encode(), headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=3) as r: data=json.load(r)
    if data.get('error'): raise RuntimeError(f"RPC {method} failed")
    return data.get('result')

def health(root):
    expected=json.loads((root/'demo.json').read_text())
    chain=int(rpc(root,'eth_chainId'),16)
    genesis=rpc(root,'eth_getBlockByNumber',['0x0',False])['hash']
    if chain != 1051 or (expected.get('genesis') and genesis != expected['genesis']): raise RuntimeError('Network identity mismatch; do not recreate this chain')
    return {'test_only':True,'chain_id':chain,'genesis':genesis,'height':int(rpc(root,'eth_blockNumber'),16)}

def own_pid(root, name):
    p=root/name
    if not p.exists(): return None
    pid=int(p.read_text())
    result=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
    # Only stop processes that refer to this private run root or this dedicated API.
    if result.returncode or not result.stdout.strip(): return None
    if str(root) not in result.stdout: raise RuntimeError('PID ownership mismatch')
    if name == 'api.pid' and 'demo.py serve' not in result.stdout: raise RuntimeError('API PID ownership mismatch')
    return pid

def wait_until(callback):
    last=None
    for _ in range(60):
        try: return callback()
        except Exception as e: last=e; time.sleep(.5)
    raise RuntimeError(f'Startup failed: {type(last).__name__}; inspect private logs')

def mysql_ready(root):
    subprocess.run([str(MYSQL/'mysqladmin'),f'--defaults-extra-file={root}/secrets/mysql-root.cnf','ping'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def start(root):
    settings=json.loads((root/'demo.json').read_text())
    if own_pid(root,'supervisor.pid'): health(root); return
    if not own_pid(root,'mysql-launch.pid'):
        log=(root/'logs/mysql.stdout.log').open('ab')
        proc=subprocess.Popen([str(MYSQL/'mysqld'),f'--defaults-file={root}/my.cnf'],stdout=log,stderr=log,start_new_session=True)
        (root/'mysql-launch.pid').write_text(str(proc.pid));wait_until(lambda:mysql_ready(root))
    wallet=json.loads((root/'secrets/wallet.json').read_text())
    env=os.environ.copy();env.update({
        'ATLAS_SUPERVISOR_STATE_ROOT':str(root/'state'),'ATLAS_SUPERVISOR_LEVELDB_DIR':str(root/'state/leveldb'),
        'ATLAS_SUPERVISOR_DB_PORT':str(settings['mysql_port']),'ATLAS_SUPERVISOR_DB_NAME':'atlas_supervisor_isolated',
        'ATLAS_SUPERVISOR_DB_USER':'atlas_supervisor','ATLAS_SUPERVISOR_DB_PASSWORD':(root/'secrets/mysql-password').read_text(),
        'ATLAS_SUPERVISOR_PAYER_ADDRESS':wallet['payer']['address'],'ATLAS_SUPERVISOR_RECIPIENT_ADDRESS':wallet['recipient']['address'],
        'ATLAS_SUPERVISOR_FEE_ADDRESS':wallet['feeSink']['address'],'ATLAS_SUPERVISOR_RPC_ADDR':f"127.0.0.1:{settings['rpc_port']}"})
    log=(root/'logs/supervisor.log').open('ab')
    proc=subprocess.Popen([str(root/'atlas-isolated-supervisor')],cwd=root/'supervisor',env=env,stdout=log,stderr=log,start_new_session=True)
    (root/'supervisor.pid').write_text(str(proc.pid));wait_until(lambda:health(root))

def stop(root):
    for name in ['api.pid','supervisor.pid']:
        pid=own_pid(root,name)
        if pid:
            os.kill(pid,signal.SIGTERM)
            for _ in range(60):
                if not own_pid(root,name): break
                time.sleep(.25)
            else: raise RuntimeError('Process did not stop; retained state for diagnosis')
    if own_pid(root,'mysql-launch.pid'):
        subprocess.run([str(MYSQL/'mysqladmin'),f'--defaults-extra-file={root}/secrets/mysql-root.cnf','shutdown'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def api_start(root):
    health(root)
    if own_pid(root,'api.pid'): return
    settings=json.loads((root/'demo.json').read_text());env=os.environ.copy()
    env.update(ATLAS_DATA_DIR=str(root/'atlas-data'),ATLAS_STATIC_DIR=str(REPO/'frontend/dist'),QUANTJUDGE_SUPERVISOR_RPC_URL=f"http://127.0.0.1:{settings['rpc_port']}",ATLAS_ALLOW_REGISTRATION='true',ATLAS_ALLOWED_ORIGINS=f"http://127.0.0.1:{settings['api_port']}")
    log=(root/'logs/api.log').open('ab')
    proc=subprocess.Popen([str(REPO/'backend/.venv/bin/python'),str(Path(__file__).resolve()),'serve','--root',str(root)],cwd=REPO/'backend',env=env,stdout=log,stderr=log,start_new_session=True)
    (root/'api.pid').write_text(str(proc.pid))
    def ready():
        with urllib.request.urlopen(f"http://127.0.0.1:{settings['api_port']}/api/v1/health",timeout=2) as r: assert json.load(r)['status']=='ok'
    wait_until(ready)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['init','start','stop','status','recover','api','serve']);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);a=p.parse_args();root=a.root.resolve()
    if not root.name.startswith('atlas-competition-') or root == REPO or REPO in root.parents: raise RuntimeError('Use a dedicated atlas-competition-* directory outside the repository')
    os.umask(0o077)
    if a.action=='serve':
        import sys
        sys.path.insert(0,str(REPO/'backend'))
        import uvicorn
        settings=json.loads((root/'demo.json').read_text())
        uvicorn.run('app.main:app',host='127.0.0.1',port=settings['api_port'],workers=1,access_log=False)
        return
    if a.action=='init':
        if root.exists(): raise RuntimeError('Refusing to initialize existing directory; use start/recover')
        root.mkdir(parents=True,mode=0o700)
        settings={'test_only':True,'rpc_port':42529,'mysql_port':19326,'api_port':8018}
        (root/'demo.json').write_text(json.dumps(settings,indent=2))
        env=os.environ.copy();env.update(ATLAS_SUPERVISOR_RUN_ROOT=str(root),ATLAS_SUPERVISOR_RPC_PORT='42529',ATLAS_SUPERVISOR_MYSQL_PORT='19326',ATLAS_SUPERVISOR_RESULT_FILE=str(root/'bootstrap-validation.json'),ATLAS_SUPERVISOR_KEEP_RUNNING='1')
        subprocess.run(['bash',str(REPO/'contracts/isolated-supervisor/scripts/run-validation.sh')],env=env,check=True)
        settings['genesis']=health(root)['genesis'];(root/'demo.json').write_text(json.dumps(settings,indent=2))
    elif a.action=='stop': stop(root); print('Dedicated demo stopped; chain/data retained'); return
    elif a.action in ['start','recover']: start(root)
    elif a.action=='api': start(root);api_start(root)
    print(json.dumps(health(root),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
