"""Online SQLite snapshot and file integrity audit for a synthetic E2E volume only."""
import hashlib,json,os,shutil,sqlite3,tarfile,tempfile
from pathlib import Path
source=Path('/work');meta=json.loads((source/'fixture.json').read_text());assert meta.get('synthetic_only') is True
assert os.environ.get('ATLAS_E2E_BACKUP')=='1'
out=Path('/evidence');out.mkdir(exist_ok=True);assert not (out/'backup.tar.gz').exists()
manifest={'schema':'atlas.e2e-backup/v1','synthetic_only':True,'files':{},'databases':{}}
with tempfile.TemporaryDirectory() as folder:
 target=Path(folder)/'work';target.mkdir()
 for path in source.rglob('*'):
  relative=path.relative_to(source)
  if path.is_symlink():raise RuntimeError('Refusing symlink in synthetic volume')
  if path.is_dir(): (target/relative).mkdir(parents=True,exist_ok=True);continue
  if path.name.endswith(('-wal','-shm','-journal')):continue
  dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
  with path.open('rb') as f:header=f.read(16)
  if header==b'SQLite format 3\x00':
   a=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True);b=sqlite3.connect(dest);a.backup(b)
   assert b.execute('PRAGMA quick_check').fetchone()[0]=='ok'
   tables=[r[0] for r in b.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
   manifest['databases'][str(relative)]={name:b.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables};b.close();a.close()
  else:shutil.copy2(path,dest)
  manifest['files'][str(relative)]=hashlib.sha256(dest.read_bytes()).hexdigest()
 with tarfile.open(out/'backup.tar.gz','w:gz') as archive:archive.add(target,arcname='work')
manifest['archive_sha256']=hashlib.sha256((out/'backup.tar.gz').read_bytes()).hexdigest();(out/'backup-manifest.json').write_text(json.dumps(manifest,indent=2));os.chmod(out/'backup.tar.gz',0o600)
print(json.dumps({'databases':len(manifest['databases']),'files':len(manifest['files']),'synthetic_only':True}))
