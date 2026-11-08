"""Pin actual test artifacts and prove current backend/frontend bytes are served."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from control import ROOT,inventory
p=argparse.ArgumentParser();p.add_argument('run_directory',type=Path);a=p.parse_args();m=json.loads((a.run_directory/'run.json').read_text());assert m['synthetic_only'] and m['port']!=18095
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source={str(p.relative_to(ROOT)):sha(p) for directory in ['frontend/src','backend/app','tools/e2e','frontend/e2e','config'] for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix not in {'.pyc'}}
source.update({str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'frontend/package-lock.json',ROOT/'frontend/playwright.config.ts',ROOT/'Dockerfile',ROOT/'compose.yaml',ROOT/'compose.browser.yaml']})
dist={str(p.relative_to(ROOT/'frontend/dist')):sha(p) for p in (ROOT/'frontend/dist').rglob('*') if p.is_file()}
api=m['project']+'-api-1';web=m['project']+'-web-1'
code="import hashlib,json;from pathlib import Path;r=Path('/app/backend/app');print(json.dumps({str(p.relative_to(r)):hashlib.sha256(p.read_bytes()).hexdigest() for p in r.rglob('*.py')}))"
actual=json.loads(subprocess.check_output(['docker','exec',api,'python','-c',code],text=True));expected={str(p.relative_to(ROOT/'backend/app')):sha(p) for p in (ROOT/'backend/app').rglob('*.py')};assert actual==expected,'Backend image does not match current Python sources'
raw=subprocess.check_output(['docker','exec',web,'sha256sum',*['/usr/share/nginx/html/'+x for x in dist]],text=True);served={line.split(None,1)[1].replace('/usr/share/nginx/html/',''):line.split()[0] for line in raw.splitlines()};assert served==dist,'Web image does not serve exact compiled output'
containers=json.loads(subprocess.check_output(['docker','inspect',api,web],text=True));ids={x['Name']:x['Image'] for x in containers};pin={'schema':'atlas.e2e-source-pin/v1','backend_image_matches':True,'served_dist_matches':True,'image_ids':ids,'sources':source,'dist':dist,'source_fingerprint':hashlib.sha256(json.dumps(source,sort_keys=True).encode()).hexdigest(),'protected_services':inventory()};(a.run_directory/'candidate-pin.json').write_text(json.dumps(pin,indent=2));print(json.dumps({'source_fingerprint':pin['source_fingerprint'],'image_ids':ids,'backend_image_matches':True,'served_dist_matches':True}))
