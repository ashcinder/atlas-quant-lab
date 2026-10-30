#!/usr/bin/env bash
set -euo pipefail

proof_bundle=
if [[ ${1:-} == --proof-bundle ]]; then
  [[ $# -eq 3 ]] || { printf 'usage: %s [--proof-bundle PUBLIC.zip] OUTPUT.tar.gz\n' "$0" >&2; exit 2; }
  proof_bundle=$2
  shift 2
fi
if [[ $# -ne 1 ]]; then
  printf 'usage: %s [--proof-bundle PUBLIC.zip] OUTPUT.tar.gz\n' "$0" >&2
  exit 2
fi

repo=$(cd "$(dirname "$0")/../.." && pwd)
output_parent=$(cd "$(dirname "$1")" && pwd)
output="$output_parent/$(basename "$1")"
api_image=${ATLAS_API_IMAGE:-atlas-quant-api:20261030-lab-v1-amd64}
web_image=${ATLAS_WEB_IMAGE:-atlas-quant-web:20261030-lab-v1-amd64}
images=("$api_image" "$web_image")
if [[ ${ATLAS_CHAIN_MODE:-} == isolated_lab ]]; then
  supervisor_image=${ATLAS_SUPERVISOR_IMAGE:-atlas-supervisor:20261030-lab-full-v1-amd64}
  mysql_image=${ATLAS_MYSQL_IMAGE:-atlas-mysql:8.4-amd64}
  images+=("$supervisor_image" "$mysql_image")
fi
if [[ -e "$output" ]]; then
  printf 'output already exists: %s\n' "$output" >&2
  exit 1
fi

for image in "${images[@]}"; do
  platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
  if [[ "$platform" != linux/amd64 ]]; then
    printf 'image is not linux/amd64: %s (%s)\n' "$image" "$platform" >&2
    exit 1
  fi
done
fingerprint=$(python3 "$repo/deploy/release/source-manifest.py" | python3 -c 'import json,sys; print(json.load(sys.stdin)["snapshot_sha256"])')
source_images=("$api_image" "$web_image")
if [[ ${ATLAS_CHAIN_MODE:-} == isolated_lab ]]; then source_images+=("$supervisor_image"); fi
for image in "${source_images[@]}"; do
  built_fingerprint=$(docker image inspect --format '{{index .Config.Labels "org.atlas.source-snapshot"}}' "$image")
  [[ "$built_fingerprint" == "$fingerprint" ]] || { printf 'source changed after image build: %s\n' "$image" >&2; exit 1; }
done

stage=$(mktemp -d "${TMPDIR:-/tmp}/atlas-release.XXXXXXXX")
trap 'rm -rf "$stage"' EXIT
bundle="$stage/atlas-quant-lab-release"
mkdir -p "$bundle/images" "$bundle/deploy/release" "$bundle/docs"

docker save "${images[@]}" | gzip -9 > "$bundle/images/atlas-images.tar.gz"
install -m 0644 "$repo/compose.release.yaml" "$repo/.env.lab.example" "$bundle/"
install -m 0644 "$repo/deploy/release/nginx-tls.conf.template" "$bundle/deploy/release/"
install -m 0755 \
  "$repo/deploy/release/load-images.sh" \
  "$repo/deploy/release/preflight.py" \
  "$repo/deploy/release/compose.py" \
  "$repo/deploy/release/checksums.py" \
  "$repo/deploy/release/import-proof.py" \
  "$repo/deploy/release/render-tls-proxy.py" \
  "$repo/deploy/release/start-release.sh" \
  "$repo/deploy/release/healthcheck.sh" \
  "$repo/deploy/release/backup-data.sh" \
  "$repo/deploy/release/restore-data.sh" \
  "$repo/deploy/release/rollback-images.sh" \
  "$repo/deploy/release/chain-snapshot.py" \
  "$bundle/deploy/release/"
install -m 0644 "$repo/docs/LAB_OFFLINE_DEPLOYMENT.md" "$bundle/docs/"
if [[ ${ATLAS_CHAIN_MODE:-} == isolated_lab ]]; then
  install -m 0644 "$repo/compose.chain.yaml" "$repo/.env.chain.lab.example" "$bundle/"
  mkdir -p "$bundle/deploy/chain" "$bundle/contracts/isolated-supervisor/scripts"
  install -m 0755 "$repo/deploy/chain/init-secrets.sh" "$repo/deploy/chain/merge-env.py" "$bundle/deploy/chain/"
  install -m 0755 "$repo/deploy/chain/fund-test-account.py" "$bundle/deploy/chain/"
  install -m 0644 "$repo/deploy/chain/fund-test-account.mjs" "$bundle/deploy/chain/"
  install -m 0644 "$repo/contracts/isolated-supervisor/scripts/create-wallet.mjs" "$bundle/contracts/isolated-supervisor/scripts/"
  install -m 0644 "$repo/docs/LAB_CHAIN_DEPLOYMENT.md" "$bundle/docs/"
fi
python3 "$repo/deploy/release/source-manifest.py" > "$bundle/source-manifest.json"
# Render image names into the shipped template, even when the build tags were overridden.
python3 - "$bundle/.env.lab.example" "$api_image" "$web_image" <<'PY'
from pathlib import Path
import sys
path, api, web = sys.argv[1:]
p = Path(path)
lines = p.read_text().splitlines()
p.write_text('\n'.join('ATLAS_API_IMAGE='+api if line.startswith('ATLAS_API_IMAGE=') else 'ATLAS_WEB_IMAGE='+web if line.startswith('ATLAS_WEB_IMAGE=') else line for line in lines)+'\n')
PY

proof_hash=
if [[ -n "$proof_bundle" ]]; then
  [[ -f "$proof_bundle" ]] || { printf 'proof bundle not found: %s\n' "$proof_bundle" >&2; exit 1; }
  mkdir -p "$bundle/proof"
  install -m 0644 "$proof_bundle" "$bundle/proof/public-proof.zip"
  proof_hash=$(python3 - "$bundle/proof/public-proof.zip" <<'PY'
import hashlib,json,sys
from pathlib import Path
from zipfile import ZipFile
with ZipFile(sys.argv[1]) as z:
    allowed={'manifest.json','journal.json','proof.r0','market.json','verify-proof-bundle.py','README.txt'}
    assert set(z.namelist())==allowed and len(z.namelist())==6, 'only the public six-file proof bundle can be shipped'
    assert sum(i.file_size for i in z.infolist())<=25_000_000
    m=json.loads(z.read('manifest.json'))
    assert hashlib.sha256(z.read('proof.r0')).hexdigest()==m['proof_hash']
print(hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
fi

source_commit=$(git -C "$repo" rev-parse HEAD)
api_id=$(docker image inspect --format '{{.Id}}' "$api_image")
web_id=$(docker image inspect --format '{{.Id}}' "$web_image")
python3 - "$bundle/release-manifest.json" "$source_commit" "$api_image" "$api_id" "$web_image" "$web_id" "$proof_hash" <<'PY'
import json
import sys
from pathlib import Path

path, commit, api_name, api_id, web_name, web_id, proof_hash = sys.argv[1:]
manifest = {
    "schema": "atlas.quantjudge.offline-release.v1",
    "source_commit": commit,
    "source_snapshot": json.loads(Path(path).with_name('source-manifest.json').read_text()),
    "platform": "linux/amd64",
    "images": {"api": {"name": api_name, "id": api_id}, "web": {"name": web_name, "id": web_id}},
    "verifier": {
        "sha256": "b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3",
        "profile": "atlas_program_backtest_risc0_v2",
        "image_id": "02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4",
    },
    "public_proof_bundle": ({"path": "proof/public-proof.zip", "sha256": proof_hash} if proof_hash else None),
}
if proof_hash:
    from zipfile import ZipFile
    with ZipFile(Path(path).parent/'proof/public-proof.zip') as z:
        manifest['public_proof_bundle']['receipt_sha256']=json.loads(z.read('manifest.json'))['proof_hash']
Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
PY

if [[ ${ATLAS_CHAIN_MODE:-} == isolated_lab ]]; then
  python3 - "$bundle/release-manifest.json" "$supervisor_image" "$mysql_image" <<'PY'
import json,subprocess,sys
from pathlib import Path
p=Path(sys.argv[1]);m=json.loads(p.read_text())
for component,name in zip(('supervisor','mysql'),sys.argv[2:]):
    record=json.loads(subprocess.check_output(['docker','image','inspect',name],text=True))[0]
    m['images'][component]={'name':name,'id':record['Id']}
    if component=='supervisor':
        m['images'][component]['binary_sha256']=record['Config']['Labels']['org.atlas.supervisor.binary-sha256']
m['chain']={'mode':'isolated_lab','chain_id':1051,'new_chain_on_fresh_volumes':True,'real_funds':False,'tee_required':False,'minimum_available_ram_gib':8}
p.write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
PY
fi

python3 - "$bundle" <<'PY'
import hashlib
import sys
from pathlib import Path

root = Path(sys.argv[1])
lines = []
for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != "SHA256SUMS"):
    with path.open('rb') as stream:
        h=hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
        digest = h.hexdigest()
    lines.append(f"{digest}  {path.relative_to(root)}")
(root / "SHA256SUMS").write_text("\n".join(lines) + "\n")
PY

COPYFILE_DISABLE=1 tar --no-xattrs -C "$stage" -czf "$output" atlas-quant-lab-release
python3 "$repo/deploy/release/checksums.py" "$output" > "$output.sha256"
python3 - "$output" <<'PY'
import hashlib
import sys
from pathlib import Path

path = Path(sys.argv[1])
with path.open('rb') as stream:
    h=hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
    print(f"{h.hexdigest()}  {path}")
PY
