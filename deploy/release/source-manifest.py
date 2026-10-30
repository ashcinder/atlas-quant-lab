#!/usr/bin/env python3
"""Fingerprint tracked sources and explicitly scoped new implementation files."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def manifest():
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    new = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode().split('\0')
    prefixes = ('backend/app/', 'backend/tests/', 'frontend/src/', 'deploy/', 'scripts/')
    names = set(tracked) | {name for name in new if name.startswith(prefixes)}
    names |= {'compose.release.yaml', 'compose.chain.yaml', '.env.lab.example', '.env.chain.lab.example', 'docs/LAB_OFFLINE_DEPLOYMENT.md', 'docs/LAB_CHAIN_DEPLOYMENT.md'}
    files = {}
    for name in sorted(names):
        if '/.build/' in name:
            continue
        path = ROOT / name
        if name and path.is_file() and not path.is_symlink():
            with path.open('rb') as stream:
                h=hashlib.sha256()
                for chunk in iter(lambda: stream.read(1024*1024), b''): h.update(chunk)
                files[name] = h.hexdigest()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'base_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'working_tree_modified': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT)),
            'snapshot_sha256': fingerprint, 'files': files}


if __name__ == '__main__':
    print(json.dumps(manifest(), indent=2, sort_keys=True))
