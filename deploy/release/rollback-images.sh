#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 3 ]]; then
  printf 'usage: %s ENV_FILE PREVIOUS_API_IMAGE PREVIOUS_WEB_IMAGE\n' "$0" >&2
  exit 2
fi
root=$(cd "$(dirname "$0")/../.." && pwd)
python3 - "$root" "$1" "$2" "$3" <<'PY'
import os,subprocess,sys,tempfile
from pathlib import Path
root,env_file,api,web=sys.argv[1:]
sys.path.insert(0,str(Path(root)/'deploy/release'))
from preflight import read_env
values=read_env(Path(env_file))
for image in (api,web):
    assert subprocess.check_output(['docker','image','inspect','--format','{{.Os}}/{{.Architecture}}',image],text=True).strip()=='linux/amd64'
values.update(ATLAS_API_IMAGE=api,ATLAS_WEB_IMAGE=web)
with tempfile.NamedTemporaryFile(mode='w',suffix='.env') as temp:
    temp.write('\n'.join(f'{key}={value}' for key,value in values.items())+'\n');temp.flush()
    subprocess.run([sys.executable,str(Path(root)/'deploy/release/compose.py'),temp.name,'up','--detach','--no-build','--pull','never','--wait','--wait-timeout','180'],check=True)
print('previous images restored on the current data volume; update your private env file before the next start')
PY
