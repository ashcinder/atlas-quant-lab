import os
import secrets
from pathlib import Path

APP_NAME = "Atlas Quant Lab API"
APP_VERSION = "0.1.0"
ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("ATLAS_DATA_DIR", ROOT_DIR / ".data")).expanduser()
CACHE_DIR = DATA_DIR / "cache"
DB_PATH = DATA_DIR / "atlas_quant.db"
ALLOWED_ORIGINS = tuple(
    origin.strip()
    for origin in os.environ.get(
        "ATLAS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
)
ALLOW_REGISTRATION = os.environ.get("ATLAS_ALLOW_REGISTRATION", "true").lower() != "false"
SESSION_SECRET = os.environ.get("ATLAS_SESSION_SECRET", "")
AUTH_ENABLED = True
SESSION_SECONDS = 7 * 24 * 60 * 60

for directory in (DATA_DIR, CACHE_DIR):
    directory.mkdir(parents=True, exist_ok=True)

if not SESSION_SECRET:
    secret_path = DATA_DIR / ".session-secret"
    try:
        with open(
            secret_path, "x", opener=lambda path, flags: os.open(path, flags, 0o600)
        ) as handle:
            handle.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    SESSION_SECRET = secret_path.read_text().strip()
if len(SESSION_SECRET) < 32:
    raise ValueError("ATLAS_SESSION_SECRET must contain at least 32 characters")
STATIC_DIR = Path(os.environ.get("ATLAS_STATIC_DIR", ROOT_DIR.parent / "frontend" / "dist"))
