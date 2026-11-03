#!/usr/bin/env python3
"""Cold backup/restore of the API, chain trie and MySQL as one private state."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

from preflight import read_env

ROOT = Path(__file__).resolve().parents[2]
VOLUMES = {'atlas-data': ('api', '/app/backend/.data'),
           'supervisor-state': ('supervisor', '/var/lib/atlas-supervisor'),
           'supervisor-mysql': ('supervisor-db', '/var/lib/mysql')}
DIRECTORIES = {'atlas-data': 'api', 'supervisor-state': 'chain', 'supervisor-mysql': 'mysql'}


def checked_resources(values, command):
    project = values.get('COMPOSE_PROJECT_NAME', 'atlas-quant-lab')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]+', project):
        raise ValueError('invalid project name')
    secrets = Path(values['ATLAS_CHAIN_SECRETS_DIR'])
    if not secrets.is_absolute() or not secrets.is_dir() or secrets.stat().st_mode & 0o077:
        raise ValueError('private absolute secrets directory required')
    from preflight import validate_chain
    validate_chain(values)
    containers = {}
    for volume, (service, destination) in VOLUMES.items():
        name = f'{project}_{volume}'
        info = json.loads(subprocess.check_output(['docker', 'volume', 'inspect', name], text=True))[0]
        labels = info.get('Labels') or {}
        if labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.volume') != volume:
            raise ValueError('volume ownership mismatch: ' + name)
        identifiers = subprocess.check_output([*command, 'ps', '--all', '--quiet', service], text=True).split()
        if len(identifiers) != 1:
            raise ValueError('one initialized service required: ' + service)
        container = json.loads(subprocess.check_output(['docker', 'inspect', identifiers[0]], text=True))[0]
        labels = container['Config'].get('Labels') or {}
        if labels.get('com.docker.compose.project') != project or labels.get('com.docker.compose.service') != service:
            raise ValueError('container ownership mismatch: ' + service)
        if not any(m.get('Type') == 'volume' and m.get('Name') == name and m.get('Destination') == destination for m in container['Mounts']):
            raise ValueError('container volume mismatch: ' + service)
        if container['State'].get('Paused') or container['State'].get('Restarting'):
            raise ValueError('service is paused or restarting: ' + service)
        if service == 'supervisor' and not any(m.get('Source') == str(secrets / 'mysql-password') for m in container['Mounts']):
            raise ValueError('secrets do not belong to this Supervisor')
        if service == 'supervisor-db':
            for filename, destination in [('mysql-password', '/run/secrets/supervisor-db-password'),
                                          ('mysql-root-password', '/run/secrets/supervisor-db-root-password')]:
                if not any(m.get('Source') == str(secrets / filename) and m.get('Destination') == destination for m in container['Mounts']):
                    raise ValueError('secrets do not belong to this MySQL: ' + filename)
        containers[service] = container
    if not all(c['State']['Running'] for c in containers.values()):
        raise ValueError('start all three services before coordinated backup to record chain and MySQL identity')
    return containers


def mysql_digest(command):
    dump = subprocess.check_output([*command, 'exec', '-T', 'supervisor-db', 'sh', '-c',
        'MYSQL_PWD="$(cat /run/secrets/supervisor-db-root-password)" exec mysqldump -uroot --skip-comments --skip-dump-date --order-by-primary --hex-blob --skip-extended-insert --no-tablespaces atlas_supervisor_isolated'])
    return hashlib.sha256(dump).hexdigest()


def chain_identity(command):
    code = '''import json
from urllib.request import Request,urlopen
def rpc(method,params):
 r=Request('http://supervisor:42515',data=json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params}).encode(),headers={'Content-Type':'application/json'})
 return json.load(urlopen(r,timeout=15))['result']
print(json.dumps({'chain_id':int(rpc('eth_chainId',[]),16),'block_number':int(rpc('eth_blockNumber',[]),16),'genesis_hash':rpc('eth_getBlockByNumber',['0x0',False])['hash']}))'''
    identity = json.loads(subprocess.check_output([*command, 'exec', '-T', 'api', 'python', '-c', code], text=True))
    if identity['chain_id'] != 1051 or not re.fullmatch(r'0x[0-9a-fA-F]{64}', identity['genesis_hash']):
        raise ValueError('invalid chain identity')
    return identity


def run(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def checksum(path):
    h=hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024), b''):h.update(chunk)
    return h.hexdigest()


def backup(env_file, archive):
    values=read_env(env_file)
    project=values.get('COMPOSE_PROJECT_NAME','atlas-quant-lab')
    command=[sys.executable,str(ROOT/'deploy/release/compose.py'),str(env_file)]
    if archive.exists() or archive.with_name(archive.name+'.sha256').exists():raise ValueError('backup already exists')
    containers = checked_resources(values, command)
    record = {'schema': 'atlas.coordinated-backup.v2', 'project': project,
              'created_at': datetime.now(timezone.utc).isoformat(),
              'images': {k: c['Image'] for k, c in containers.items()}}
    if not archive.parent.is_dir():
        raise ValueError('backup parent directory must exist')
    temporary = archive.with_name(archive.name + '.partial')
    if temporary.exists():
        raise ValueError('unfinished backup already exists; inspect it before retrying')
    image=values['ATLAS_API_IMAGE']
    volumes={'atlas-data':'api','supervisor-state':'chain','supervisor-mysql':'mysql'}
    args=['docker','run','--rm','--platform','linux/amd64','--network','none','--user','0:0','--entrypoint','python']
    for volume,directory in volumes.items():args.extend(['-v',f'{project}_{volume}:/snapshot/{directory}:ro'])
    args.extend(['-v',f'{Path(values["ATLAS_CHAIN_SECRETS_DIR"]).resolve()}:/snapshot/secrets:ro','-v',f'{archive.parent}:/backup',
                 '-v', f'{ROOT / "deploy/release/snapshot-content.py"}:/tools/snapshot_content.py:ro'])
    program="""import io,json,os,sys,tarfile
sys.path.insert(0,'/tools');from snapshot_content import inspect,SECRET_FILES
os.umask(0o077)
record=json.loads(os.environ['SNAPSHOT_RECORD']);record['content']=inspect('/snapshot')
with tarfile.open('/backup/'+os.environ['BACKUP_NAME'],'x:gz') as t:
 for n in ('api','chain','mysql'):
  t.add('/snapshot/'+n,arcname=n,filter=lambda m:m if (m.isfile() or m.isdir()) and not m.issym() else None)
 t.add('/snapshot/secrets',arcname='secrets',recursive=False)
 for n in SECRET_FILES:t.add('/snapshot/secrets/'+n,arcname='secrets/'+n,recursive=False)
 data=json.dumps(record,sort_keys=True).encode();m=tarfile.TarInfo('snapshot-manifest.json');m.size=len(data);m.mode=0o600;t.addfile(m,io.BytesIO(data))
"""
    stopped = []
    published = False
    try:
        # API is the sole writer to the private chain; stop it before identity capture.
        stopped.append('api');run([*command, 'stop', 'api'])
        # The stopped API cannot execute RPC requests. Use the still-running Supervisor.
        identity = {}
        for method, params in [('eth_chainId', []), ('eth_blockNumber', []), ('eth_getBlockByNumber', ['0x0', False])]:
            payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}, separators=(',', ':'))
            raw = subprocess.check_output([*command, 'exec', '-T', 'supervisor', 'wget', '-qO-', '--header=Content-Type: application/json', '--post-data='+payload, 'http://127.0.0.1:42515'], text=True)
            identity[method] = json.loads(raw)['result']
        record['chain'] = {'chain_id': int(identity['eth_chainId'], 16), 'block_number': int(identity['eth_blockNumber'], 16), 'genesis_hash': identity['eth_getBlockByNumber']['hash']}
        if record['chain']['chain_id'] != 1051:raise ValueError('unexpected chain ID')
        stopped.append('supervisor');run([*command, 'stop', 'supervisor'])
        record['mysql_logical_sha256'] = mysql_digest(command)
        stopped.append('supervisor-db');run([*command, 'stop', 'supervisor-db'])
        run([*args,'-e','BACKUP_NAME='+temporary.name,'-e','SNAPSHOT_RECORD='+json.dumps(record),image,'-c',program], capture_output=True)
        temporary.chmod(0o600)
        # Validate the archived bytes, not just the mounted input directories.
        verify_archive(temporary)
        temporary.replace(archive)
        manifest=archive.with_name(archive.name+'.sha256')
        manifest.write_text(checksum(archive)+'  '+archive.name+'\n');manifest.chmod(0o600)
        published = True
    finally:
        temporary.unlink(missing_ok=True)
        if not published:
            archive.unlink(missing_ok=True)
            archive.with_name(archive.name+'.sha256').unlink(missing_ok=True)
        failed=[]
        for service in reversed(stopped):
            try:run([*command,'start','--wait','--wait-timeout','180',service])
            except subprocess.CalledProcessError:failed.append(service)
        if failed:raise RuntimeError('backup completed but services require attention: '+','.join(failed))
    print('Private v2 backup content verified; independent restore and chain/MySQL comparison still required.')


def verify_archive(archive):
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('duplicate archive members')
        for m in members:
            p = Path(m.name)
            if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] not in ('api','chain','mysql','secrets','snapshot-manifest.json') or not (m.isfile() or m.isdir()):
                raise ValueError('unsafe backup member')
            if p.parts[0] == 'secrets' and len(p.parts) > 1 and (len(p.parts) != 2 or p.parts[1] not in ('mysql-password','mysql-root-password','wallet.json','chain.env')):
                raise ValueError('unexpected secret backup member')
        if 'snapshot-manifest.json' not in names:
            return None  # Legacy backups need isolated content/runtime acceptance.
        record = json.load(source.extractfile('snapshot-manifest.json'))
        if record.get('schema') != 'atlas.coordinated-backup.v2':raise ValueError('unsupported backup schema')
        expected = record['content']['files']
        actual = {m.name for m in members if m.isfile() and m.name != 'snapshot-manifest.json'}
        if actual != set(expected):raise ValueError('backup content inventory mismatch')
        for name, entry in expected.items():
            h = hashlib.sha256()
            with source.extractfile(name) as stream:
                for chunk in iter(lambda: stream.read(1024*1024), b''):h.update(chunk)
            if h.hexdigest() != entry['sha256'] or source.getmember(name).size != entry['bytes']:
                raise ValueError('backup file digest mismatch: ' + name)
        return record


def restore(env_file, archive, project):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]+',project):raise ValueError('invalid new project name')
    expected=archive.with_name(archive.name+'.sha256').read_text().split()[0]
    if checksum(archive)!=expected:raise ValueError('backup checksum mismatch')
    record = verify_archive(archive)
    values=read_env(env_file)
    volumes={'atlas-data':'api','supervisor-state':'chain','supervisor-mysql':'mysql'}
    secrets=archive.parent/(project+'.secrets')
    if secrets.exists():raise ValueError('refusing to overwrite a recovered secrets directory')
    for volume in volumes:
        found=subprocess.run(['docker','volume','inspect',f'{project}_{volume}'],capture_output=True)
        if found.returncode==0:raise ValueError('refusing to overwrite an existing restore volume')
    import shutil
    with tarfile.open(archive, 'r:gz') as source:required_bytes=sum(m.size for m in source if m.isfile())
    if shutil.disk_usage(archive.parent).free < required_bytes + 2*1024**3:raise ValueError('insufficient restore directory space')
    free=int(subprocess.check_output(['docker','run','--rm','--network','none','--entrypoint','python',values['ATLAS_API_IMAGE'],'-c','import shutil;print(shutil.disk_usage("/").free)'],text=True))
    if free < required_bytes + 2*1024**3:raise ValueError('insufficient Docker restore space')
    args=['docker','run','--rm','--platform','linux/amd64','--network','none','--user','0:0','--entrypoint','python','-v',f'{archive.parent}:/backup:ro', '-v',f'{ROOT / "deploy/release/snapshot-content.py"}:/tools/snapshot_content.py:ro']
    created=[]
    program="""import os,tarfile
from pathlib import PurePosixPath
with tarfile.open('/backup/'+os.environ['BACKUP_NAME'],'r:gz') as t:
    for m in t:
        p=PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts or p.parts[0] not in ('api','chain','mysql','secrets','snapshot-manifest.json') or not (m.isdir() or m.isfile()):
            raise ValueError('unexpected backup member')
        if p.parts[0]=='secrets' and len(p.parts)>1 and (len(p.parts)!=2 or p.parts[1] not in ('mysql-password','mysql-root-password','wallet.json','chain.env')):
            raise ValueError('unexpected secret backup member')
        t.extract(m,'/restore',numeric_owner=True,filter='fully_trusted')
manifest=__import__('pathlib').Path('/restore/snapshot-manifest.json')
if manifest.exists():
    import json,sys
    sys.path.insert(0,'/tools');from snapshot_content import inspect
    if inspect('/restore')!=json.loads(manifest.read_text())['content']:raise ValueError('restored content does not match manifest')
os.chown('/restore/secrets',int(os.environ['RESTORE_UID']),int(os.environ['RESTORE_GID']))
os.chmod('/restore/secrets',0o700)
for p in __import__('pathlib').Path('/restore/secrets').iterdir():
    if p.name=='mysql-password':os.chown(p,101,101)
    else:os.chown(p,int(os.environ['RESTORE_UID']),int(os.environ['RESTORE_GID']))
    os.chmod(p,0o600)
"""
    try:
        secrets.mkdir(mode=0o700)
        for volume,directory in volumes.items():
            name=f'{project}_{volume}'
            run(['docker','volume','create','--label','com.docker.compose.project='+project,'--label','com.docker.compose.volume='+volume,name],stdout=subprocess.DEVNULL);created.append(name)
            args.extend(['-v',f'{name}:/restore/{directory}'])
        args.extend(['-v',f'{secrets}:/restore/secrets'])
        run([*args,'-e','BACKUP_NAME='+archive.name,'-e','RESTORE_UID='+str(os.getuid()),'-e','RESTORE_GID='+str(os.getgid()),values['ATLAS_API_IMAGE'],'-c',program],capture_output=True)
        values.update(COMPOSE_PROJECT_NAME=project,ATLAS_CHAIN_SECRETS_DIR=str(secrets))
        with os.fdopen(os.open(secrets/'restored.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
            f.write('\n'.join(k+'='+v for k,v in values.items())+'\n')
        (secrets/'restore-verification.json').write_text(json.dumps({'schema':'atlas.restore-verification.v1','archive_sha256':expected,'content_verified':bool(record),'runtime_verified':False,'legacy':record is None},indent=2))
    except Exception:
        for name in reversed(created):subprocess.run(['docker','volume','rm',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        shutil.rmtree(secrets,ignore_errors=True)
        raise
    print(f'Restored three independent data volumes and private credentials in {secrets}. Review restored.env: change the network, all proxy addresses and port before starting; do not initialize another chain.')


if __name__=='__main__':
    if len(sys.argv) not in (4,5):raise SystemExit('usage: chain-snapshot.py backup ENV ARCHIVE | restore ENV ARCHIVE NEW_PROJECT')
    mode=sys.argv[1];env_file=Path(sys.argv[2]).resolve();archive=Path(sys.argv[3]).resolve()
    if mode=='backup' and len(sys.argv)==4:backup(env_file,archive)
    elif mode=='restore' and len(sys.argv)==5:restore(env_file,archive,sys.argv[4])
    else:raise SystemExit('invalid snapshot operation')
