"""Public source digests for independent review. Not a signature or trust anchor."""
import hashlib
import json
from pathlib import Path
root = Path(__file__).resolve().parent
files = sorted([*root.glob('*.py'), *root.glob('*.sh'), root/'Dockerfile', root/'requirements.txt', root/'host.yaml', root/'atlas-enclave.service', root/'nsm/Cargo.toml', root/'nsm/Cargo.lock', root/'nsm/src/main.rs'])
manifest = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
print(json.dumps(manifest, sort_keys=True, indent=2))
