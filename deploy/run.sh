#!/usr/bin/env bash
# Retired: the legacy launcher removed containers without preserving their data.
printf '%s\n' \
  'deploy/run.sh has been retired; no containers or data were changed.' \
  'Read DEPLOY.md and docs/DEPLOYMENT.md for the supported Compose workflow.' \
  'Back up existing data and identify its volume before migrating.' >&2
exit 1
