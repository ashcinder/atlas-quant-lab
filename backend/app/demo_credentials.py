"""Per-user demo credentials, encrypted at rest; never returned by an API.

This protects a database copy, not against the platform host administrator.
"""

import json
import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from app.config import DATA_DIR, DB_PATH

KEY_PATH = DATA_DIR / ".demo-account-key"

LOGGER = logging.getLogger(__name__)
# The scheduler re-reads every owner's account on each tick, so an unreadable
# row would otherwise repeat the same warning thousands of times a day.
_REPORTED_UNREADABLE = set()


@contextmanager
def database():
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def exists(connection):
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='demo_credentials'"
        ).fetchone()
        is not None
    )


def cipher(create=False):
    if create:
        try:
            descriptor = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(AESGCM.generate_key(bit_length=256))
    try:
        return AESGCM(KEY_PATH.read_bytes())
    except (OSError, ValueError):
        raise HTTPException(503, "模拟账户加密密钥不可用，请恢复本机密钥文件") from None


def load(owner, venue):
    """Return saved credentials, or None when none are readable here.

    A key file lost with its container, or a database restored from another
    host, leaves rows that can never be decrypted again. That is one account's
    problem, not the caller's: report it as unconfigured so a single unreadable
    row cannot fail a whole page. Callers never fall back to weaker
    credentials on this path — see Exchange.__init__, which clears environment
    keys for any owner other than the configured one.
    """
    with database() as connection:
        if not exists(connection):
            return None
        row = connection.execute(
            "SELECT encrypted FROM demo_credentials WHERE owner=? AND venue=?", (owner, venue)
        ).fetchone()
    if row is None:
        return None
    try:
        blob = row["encrypted"]
        return json.loads(cipher().decrypt(blob[:12], blob[12:], f"{owner}:{venue}:demo".encode()))
    except Exception:
        if (owner, venue) not in _REPORTED_UNREADABLE:
            _REPORTED_UNREADABLE.add((owner, venue))
            LOGGER.warning(
                "%s demo credentials for owner=%s are unreadable here (key missing or rotated); "
                "treating the account as unconfigured",
                venue,
                owner,
            )
        return None


def owners():
    with database() as connection:
        if not exists(connection):
            return []
        return [row[0] for row in connection.execute("SELECT DISTINCT owner FROM demo_credentials")]


def save(owner, venue, credentials):
    nonce = secrets.token_bytes(12)
    encrypted = nonce + cipher(create=True).encrypt(
        nonce, json.dumps(credentials).encode(), f"{owner}:{venue}:demo".encode()
    )
    with database() as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS demo_credentials (owner TEXT NOT NULL, "
            "venue TEXT NOT NULL, encrypted BLOB NOT NULL, PRIMARY KEY(owner,venue))"
        )
        connection.execute(
            "INSERT OR REPLACE INTO demo_credentials VALUES (?,?,?)", (owner, venue, encrypted)
        )
