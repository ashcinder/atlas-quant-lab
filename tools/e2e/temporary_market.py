"""Restore only publication pointers changed by synthetic scenario scripts."""
import json
import os
from pathlib import Path

from app.market_publication import query_key


def checkpoint(publications, name, sources):
    assert os.environ.get('ATLAS_E2E_ISOLATED') == '1'
    assert os.environ.get('ATLAS_DATA_DIR') == '/work/data'
    assert json.loads(Path('/work/fixture.json').read_text())['synthetic_only']
    path = Path('/work') / (name + '-publication.json')
    if path.exists():
        return
    keys = [query_key(dict(symbol='BTC-USD', asset_class='crypto', interval='1d', data_source=s)) for s in sources]
    with publications.connect() as db:
        rows = [db.execute('SELECT * FROM market_publications WHERE query_key=?', (key,)).fetchone() for key in keys]
    assert all(rows), 'The original synthetic publication must exist'
    path.write_text(json.dumps(rows))


def restore(publications, name):
    assert os.environ.get('ATLAS_E2E_ISOLATED') == '1'
    assert os.environ.get('ATLAS_DATA_DIR') == '/work/data'
    assert json.loads(Path('/work/fixture.json').read_text())['synthetic_only']
    path = Path('/work') / (name + '-publication.json')
    if not path.exists():
        return {'restored': False, 'reason': 'scenario_not_started'}
    rows = json.loads(path.read_text())
    with publications.connect() as db:
        db.executemany('INSERT OR REPLACE INTO market_publications VALUES (?,?,?)', rows)
    path.unlink()
    # Keep immutable versions/objects referenced by the scenario's saved reports.
    return {'restored': True, 'publication_pointers': len(rows)}
