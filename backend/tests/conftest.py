"""Keep imports of application stores away from the user's local database and keys."""

from pathlib import Path
from tempfile import TemporaryDirectory

from app import config

# Store defaults are evaluated when their modules are imported. Isolate them
# before test collection imports app.main, not in a later fixture.
_test_storage = TemporaryDirectory(prefix="atlas-backend-tests-")
config.DATA_DIR = Path(_test_storage.name)
config.CACHE_DIR = config.DATA_DIR / "cache"
config.DB_PATH = config.DATA_DIR / "atlas_quant.db"
config.CACHE_DIR.mkdir()


def pytest_unconfigure(config):
    _test_storage.cleanup()
