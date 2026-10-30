#!/usr/bin/env python3
"""Create one account while public registration is disabled."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.auth import normalize_email, valid_email, valid_password
from app.journal.store import JournalStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="member email address")
    args = parser.parse_args()

    email = normalize_email(args.email)
    if not valid_email(email):
        parser.error("email is invalid")
    password = getpass.getpass("Password (8-128 characters): ")
    repeated = getpass.getpass("Repeat password: ")
    if password != repeated:
        parser.error("passwords do not match")
    if not valid_password(password):
        parser.error("password must contain 8 to 128 characters")

    user = JournalStore().create_user(email, password)
    if user is None:
        parser.error("account already exists")
    print(f"created account: {user.email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
