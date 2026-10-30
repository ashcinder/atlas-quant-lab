#!/usr/bin/env python3
"""Render the host Nginx TLS proxy from the reviewed lab environment."""

from __future__ import annotations

import argparse
from pathlib import Path

from preflight import read_env, required, validate_config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists")
    values = read_env(args.env_file)
    validate_config(values)
    template = Path(__file__).with_name("nginx-tls.conf.template").read_text()
    replacements = {
        "__ATLAS_DOMAIN__": required(values, "ATLAS_DOMAIN"),
        "__ATLAS_HTTP_PORT__": required(values, "ATLAS_HTTP_PORT"),
        "__ATLAS_HTTPS_PORT__": required(values, "ATLAS_HTTPS_PORT"),
        "__ATLAS_TLS_CERT_FILE__": required(values, "ATLAS_TLS_CERT_FILE"),
        "__ATLAS_TLS_KEY_FILE__": required(values, "ATLAS_TLS_KEY_FILE"),
    }
    for marker, value in replacements.items():
        if any(character.isspace() for character in value):
            parser.error(f"unsafe whitespace in {marker}")
        template = template.replace(marker, value)
    args.output.write_text(template)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
