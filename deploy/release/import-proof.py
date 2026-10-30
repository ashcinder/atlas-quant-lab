#!/usr/bin/env python3
"""Explicitly import only the public receipt pinned by the release manifest."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
if len(sys.argv) != 2:
    raise SystemExit('usage: import-proof.py ENV_FILE')
record = json.loads((ROOT / 'release-manifest.json').read_text())['public_proof_bundle']
if not record:
    raise SystemExit('this release contains no public proof fixture')
payload = (ROOT / record['path']).read_bytes()
if hashlib.sha256(payload).hexdigest() != record['sha256']:
    raise SystemExit('public bundle hash mismatch')
with ZipFile(ROOT / record['path']) as archive:
    receipt_hash = hashlib.sha256(archive.read('proof.r0')).hexdigest()
if receipt_hash != record['receipt_sha256']:
    raise SystemExit('public receipt hash mismatch')
command = [sys.executable, str(Path(__file__).with_name('compose.py')), sys.argv[1], 'exec', '-T', 'api', 'python']
subprocess.run([*command, '-c', "import sys; from pathlib import Path; Path('/tmp/public-proof.zip').write_bytes(sys.stdin.buffer.read())"], input=payload, check=True)
subprocess.run([*command, '/app/scripts/import-verified-proof.py', '--bundle', '/tmp/public-proof.zip',
                '--expected-receipt-sha256', receipt_hash], check=True)
