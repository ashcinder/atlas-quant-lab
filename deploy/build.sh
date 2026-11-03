#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' 'deploy/build.sh is retired; use deploy/release/build-images.sh and package-release.sh' >&2
exit 2
