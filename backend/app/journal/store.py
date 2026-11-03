from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.auth import User, hash_password
from app.config import DB_PATH


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JournalStore:
    def __init__(self, path: Path = DB_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, email TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL, session_version INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ledgers (
                    owner_id TEXT PRIMARY KEY REFERENCES users(id)
                    ON DELETE CASCADE,
                    data TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    sid_hash TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    session_version INTEGER NOT NULL,
                    expires_at INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_owner_id ON sessions(owner_id);
            """)
            connection.execute(
                "INSERT OR IGNORE INTO users (id,email,password_hash,created_at) "
                "VALUES ('local','local@atlas.invalid','',?)",
                (_now(),),
            )

    def create_user(self, email: str, password: str) -> User | None:
        user = User(str(uuid4()), email)
        try:
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO users (id,email,password_hash,created_at) VALUES (?,?,?,?)",
                    (user.id, email, hash_password(password), _now()),
                )
        except sqlite3.IntegrityError:
            return None
        return user

    def user_by_email(self, email: str):
        with self._connect() as connection:
            return connection.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()

    def create_session(
        self, owner_id: str, sid_hash: str, version: int, expires_at: int
    ) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            connection.execute(
                "INSERT INTO sessions "
                "(sid_hash,owner_id,session_version,expires_at,created_at) VALUES (?,?,?,?,?)",
                (sid_hash, owner_id, version, expires_at, _now()),
            )

    def find_session_user(self, user_id: str, email: str, version: int, sid_hash: str):
        with self._connect() as connection:
            return connection.execute(
                "SELECT users.id,users.email,users.session_version FROM sessions "
                "JOIN users ON users.id=sessions.owner_id "
                "WHERE sessions.sid_hash=? AND sessions.owner_id=? "
                "AND sessions.session_version=? AND sessions.expires_at>? "
                "AND users.email=? AND users.session_version=?",
                (sid_hash, user_id, version, int(time.time()), email, version),
            ).fetchone()

    def revoke_session(self, sid_hash: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE sid_hash=?", (sid_hash,))

    def users(self) -> list[User]:
        with self._connect() as connection:
            rows = connection.execute("SELECT id,email,session_version FROM users").fetchall()
        return [User(row["id"], row["email"], row["session_version"]) for row in rows]

    def change_password(self, user: User, password_hash: str) -> User | None:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE users SET password_hash=?, session_version=session_version+1 WHERE id=?",
                (password_hash, user.id),
            )
            if not cursor.rowcount:
                return None
            connection.execute("DELETE FROM sessions WHERE owner_id=?", (user.id,))
            row = connection.execute(
                "SELECT id,email,session_version FROM users WHERE id=?", (user.id,)
            ).fetchone()
        return User(row["id"], row["email"], row["session_version"])

    def read_ledger(self, owner_id: str, empty: dict) -> dict:
        import json

        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO ledgers VALUES (?,?,0,?)",
                (owner_id, json.dumps(empty, ensure_ascii=False), _now()),
            )
            row = connection.execute(
                "SELECT * FROM ledgers WHERE owner_id=?", (owner_id,)
            ).fetchone()
        return {
            "state": json.loads(row["data"]),
            "revision": row["revision"],
            "updatedAt": row["updated_at"],
        }

    def save_ledger(self, owner_id: str, state: dict, revision: int) -> dict | None:
        import json

        updated_at = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE ledgers SET data=?, revision=revision+1, updated_at=? "
                "WHERE owner_id=? AND revision=?",
                (json.dumps(state, ensure_ascii=False), updated_at, owner_id, revision),
            )
        if not cursor.rowcount:
            return None
        return {"state": state, "revision": revision + 1, "updatedAt": updated_at}
