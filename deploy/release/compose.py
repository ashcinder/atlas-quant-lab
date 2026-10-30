#!/usr/bin/env python3
"""Run the image-only stack with the reviewed file taking precedence over shell variables."""
import os
from pathlib import Path
import subprocess
import sys

from preflight import read_env, compose_files

if len(sys.argv) < 3:
    raise SystemExit("usage: compose.py ENV_FILE COMPOSE_ARGS...")
env_file = Path(sys.argv[1]).resolve()
root = Path(__file__).resolve().parents[2]
values = read_env(env_file)
raise SystemExit(subprocess.call(
    ["docker", "compose", "--env-file", str(env_file), *compose_files(values), *sys.argv[2:]],
    env={**os.environ, **values},
))
