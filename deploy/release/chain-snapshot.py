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

from preflight import read_env

ROOT = Path(__file__).resolve().parents[2]


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
    services=['api','supervisor','supervisor-db']
    active=[]
    for service in services:
        if subprocess.check_output([*command,'ps','--status','running','--quiet',service],text=True).strip():active.append(service)
    if archive.exists() or archive.with_name(archive.name+'.sha256').exists():raise ValueError('backup already exists')
    image=values['ATLAS_API_IMAGE']
    volumes={'atlas-data':'api','supervisor-state':'chain','supervisor-mysql':'mysql'}
    args=['docker','run','--rm','--platform','linux/amd64','--network','none','--user','0:0','--entrypoint','python']
    for volume,directory in volumes.items():args.extend(['-v',f'{project}_{volume}:/snapshot/{directory}:ro'])
    args.extend(['-v',f'{Path(values["ATLAS_CHAIN_SECRETS_DIR"]).resolve()}:/snapshot/secrets:ro','-v',f'{archive.parent}:/backup'])
    program="import os,tarfile;os.umask(0o077);t=tarfile.open('/backup/'+os.environ['BACKUP_NAME'],'x:gz');[t.add('/snapshot/'+n,arcname=n,filter=lambda m:m if m.isfile() or m.isdir() else None) for n in ('api','chain','mysql')];t.add('/snapshot/secrets',arcname='secrets',recursive=False);[t.add('/snapshot/secrets/'+n,arcname='secrets/'+n,recursive=False) for n in ('mysql-password','mysql-root-password','wallet.json','chain.env')];t.close()"
    try:
        for service in active:run([*command,'stop',service])
        run([*args,'-e','BACKUP_NAME='+archive.name,image,'-c',program])
        archive.chmod(0o600)
        manifest=archive.with_name(archive.name+'.sha256')
        manifest.write_text(checksum(archive)+'  '+archive.name+'\n');manifest.chmod(0o600)
    finally:
        failed=[]
        for service in reversed(active):
            try:run([*command,'start',service])
            except subprocess.CalledProcessError:failed.append(service)
        if failed:raise RuntimeError('backup completed but services require attention: '+','.join(failed))
    print('Private coordinated backup created; includes database credentials and test wallet. Store securely.')


def restore(env_file, archive, project):
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]+',project):raise ValueError('invalid new project name')
    expected=archive.with_name(archive.name+'.sha256').read_text().split()[0]
    if checksum(archive)!=expected:raise ValueError('backup checksum mismatch')
    values=read_env(env_file)
    volumes={'atlas-data':'api','supervisor-state':'chain','supervisor-mysql':'mysql'}
    secrets=archive.parent/(project+'.secrets')
    if secrets.exists():raise ValueError('refusing to overwrite a recovered secrets directory')
    for volume in volumes:
        found=subprocess.run(['docker','volume','inspect',f'{project}_{volume}'],capture_output=True)
        if found.returncode==0:raise ValueError('refusing to overwrite an existing restore volume')
    args=['docker','run','--rm','--platform','linux/amd64','--network','none','--user','0:0','--entrypoint','python','-v',f'{archive.parent}:/backup:ro']
    created=[]
    program="""import os,tarfile
from pathlib import PurePosixPath
with tarfile.open('/backup/'+os.environ['BACKUP_NAME'],'r:gz') as t:
    for m in t:
        p=PurePosixPath(m.name)
        if p.is_absolute() or '..' in p.parts or p.parts[0] not in ('api','chain','mysql','secrets') or not (m.isdir() or m.isfile()):
            raise ValueError('unexpected backup member')
        if p.parts[0]=='secrets' and len(p.parts)>1 and (len(p.parts)!=2 or p.parts[1] not in ('mysql-password','mysql-root-password','wallet.json','chain.env')):
            raise ValueError('unexpected secret backup member')
        t.extract(m,'/restore',numeric_owner=True,filter='fully_trusted')
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
            run(['docker','volume','create',name],stdout=subprocess.DEVNULL);created.append(name)
            args.extend(['-v',f'{name}:/restore/{directory}'])
        args.extend(['-v',f'{secrets}:/restore/secrets'])
        run([*args,'-e','BACKUP_NAME='+archive.name,'-e','RESTORE_UID='+str(os.getuid()),'-e','RESTORE_GID='+str(os.getgid()),values['ATLAS_API_IMAGE'],'-c',program])
        values.update(COMPOSE_PROJECT_NAME=project,ATLAS_CHAIN_SECRETS_DIR=str(secrets))
        with os.fdopen(os.open(secrets/'restored.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600),'w') as f:
            f.write('\n'.join(k+'='+v for k,v in values.items())+'\n')
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
