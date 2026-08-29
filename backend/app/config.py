from pathlib import Path

APP_NAME = "Atlas Quant Lab API"
APP_VERSION = "0.2.0"
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / ".data"
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "atlas_quant.db"

for directory in (DATA_DIR, CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)
