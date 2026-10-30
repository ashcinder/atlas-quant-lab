#!/usr/bin/env python3
"""Portable streaming SHA-256 calculation and verification."""
import hashlib
from pathlib import Path
import sys


def digest(path):
    with Path(path).open('rb') as source:
        h=hashlib.sha256()
        for chunk in iter(lambda: source.read(1024*1024), b''): h.update(chunk)
        return h.hexdigest()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--check':
        for line in Path(sys.argv[2]).read_text().splitlines():
            expected, name = line.split('  ', 1)
            path = Path(name)
            if path.is_absolute() or '..' in path.parts or digest(path) != expected:
                raise SystemExit(f'checksum failed: {name}')
        print('all SHA-256 checks passed')
    elif len(sys.argv) == 2:
        path = Path(sys.argv[1])
        print(f'{digest(path)}  {path.name}')
    else:
        raise SystemExit('usage: checksums.py FILE | --check SHA256SUMS')
