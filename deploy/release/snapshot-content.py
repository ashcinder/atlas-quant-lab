#!/usr/bin/env python3
"""Private content manifest, executed inside the reviewed API image."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

SECRET_FILES = ('mysql-password', 'mysql-root-password', 'wallet.json', 'chain.env')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def inspect(root):
    root = Path(root)
    required = ['api/atlas_quant.db', 'api/.session-secret', 'api/quantjudge_package.key',
                'chain/state/lab-identity-v1', 'mysql/mysql.ibd']
    for name in required + ['secrets/' + n for n in SECRET_FILES]:
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise ValueError('missing or empty snapshot content: ' + name)
    if not (root / 'chain/state').is_dir() or not any((root / 'chain/state').rglob('*')):
        raise ValueError('chain state is empty')
    if not (root / 'mysql/atlas_supervisor_isolated').is_dir():
        raise ValueError('Supervisor database is missing')
    files = {}
    for name in ('api', 'chain', 'mysql', 'secrets'):
        for path in sorted((root / name).rglob('*')):
            if path.is_symlink():
                # MySQL may ship a unix_socket symlink to /var/run. It is not data.
                if path.name == 'mysql.sock':
                    continue
                raise ValueError('unexpected snapshot symlink: ' + str(path.relative_to(root)))
            if path.is_file():
                if name == 'secrets' and path.name not in SECRET_FILES:
                    continue
                files[str(path.relative_to(root))] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    connection = sqlite3.connect(f'file:{root / "api/atlas_quant.db"}?mode=ro', uri=True)
    try:
        if connection.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        tables = {}
        for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"' + name.replace('"', '""') + '"'
            rows = [json.dumps(list(row), default=lambda v: {'bytes': v.hex()}, ensure_ascii=True, separators=(',', ':'))
                    for row in connection.execute('SELECT * FROM ' + quoted)]
            tables[name] = {'rows': len(rows), 'sha256': hashlib.sha256('\n'.join(sorted(rows)).encode()).hexdigest()}
    finally:
        connection.close()
    return {'files': files, 'sqlite': tables}


if __name__ == '__main__':
    print(json.dumps(inspect(sys.argv[1]), sort_keys=True))
