#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SECRETS_DIR="${1:-}"
API_IMAGE="${ATLAS_API_IMAGE:-atlas-quant-api:20261030-lab-full-v1-amd64}"

if [[ -z "$SECRETS_DIR" || "$SECRETS_DIR" != /* ]]; then
  echo 'Usage: init-secrets.sh /absolute/private/directory' >&2
  exit 2
fi
if [[ "$SECRETS_DIR" =~ [[:space:]] ]]; then
  echo 'The private directory path must not contain whitespace.' >&2
  exit 2
fi
mkdir -p "$SECRETS_DIR"
chmod 0700 "$SECRETS_DIR"
for name in mysql-password mysql-root-password wallet.json chain.env; do
  if [[ -e "$SECRETS_DIR/$name" ]]; then
    echo "Refusing to overwrite $SECRETS_DIR/$name" >&2
    exit 1
  fi
done

openssl rand -hex 32 > "$SECRETS_DIR/mysql-password"
openssl rand -hex 32 > "$SECRETS_DIR/mysql-root-password"
docker run --rm --platform linux/amd64 \
  --network none --read-only --cap-drop ALL --security-opt no-new-privileges:true \
  --user "$(id -u):$(id -g)" \
  --entrypoint node \
  --workdir /app/contracts \
  --volume "$PROJECT_DIR/contracts/isolated-supervisor/scripts/create-wallet.mjs:/app/contracts/create-wallet.mjs:ro" \
  --volume "$SECRETS_DIR:/out" \
  "$API_IMAGE" ./create-wallet.mjs /out/wallet.json

IFS=$'\t' read -r PAYER_ADDRESS RECIPIENT_ADDRESS FEE_ADDRESS < <(python3 - "$SECRETS_DIR/wallet.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding='utf-8'))
values = []
for key in ('payer', 'recipient', 'feeSink'):
    value = data[key]['address']
    if not isinstance(value, str) or len(value) != 42 or not value.startswith('0x'):
        raise SystemExit('generated wallet has an invalid public address')
    values.append(value)
print('\t'.join(values))
PY
)

cat > "$SECRETS_DIR/chain.env" <<EOF
ATLAS_CHAIN_MODE=isolated_lab
ATLAS_CHAIN_SECRETS_DIR=$SECRETS_DIR
ATLAS_NETWORK_SUBNET=172.30.123.0/29
ATLAS_NETWORK_GATEWAY=172.30.123.1
ATLAS_API_IP=172.30.123.2
ATLAS_WEB_IP=172.30.123.3
ATLAS_TLS_PROXY_IP=172.30.123.1
ATLAS_SUPERVISOR_IP=172.30.123.5
ATLAS_SUPERVISOR_IMAGE=atlas-supervisor:20261030-lab-full-v1-amd64
ATLAS_MYSQL_IMAGE=atlas-mysql:8.4-amd64
ATLAS_SUPERVISOR_PAYER_ADDRESS=$PAYER_ADDRESS
ATLAS_SUPERVISOR_RECIPIENT_ADDRESS=$RECIPIENT_ADDRESS
ATLAS_SUPERVISOR_FEE_ADDRESS=$FEE_ADDRESS
QUANTJUDGE_SUPERVISOR_RPC_URL=http://supervisor:42515
TRINE_PROOF_RECIPIENT=$RECIPIENT_ADDRESS
TRINE_PROOF_PRICE_BKC=1
EOF
chmod 0600 "$SECRETS_DIR/mysql-password" "$SECRETS_DIR/mysql-root-password" \
  "$SECRETS_DIR/wallet.json" "$SECRETS_DIR/chain.env"
# Compose secrets are bind-mounted files: Linux preserves their numeric owner.
# Only the nonroot Supervisor needs this password; MySQL reads it as root first.
docker run --rm --platform linux/amd64 --network none --read-only \
  --user 0:0 --cap-drop ALL --cap-add CHOWN --cap-add DAC_OVERRIDE \
  --entrypoint chown --volume "$SECRETS_DIR:/out" "$API_IMAGE" \
  101:101 /out/mysql-password

printf 'Created private isolated-chain configuration: %s\n' "$SECRETS_DIR/chain.env"
printf 'Wallet private key remains only in: %s\n' "$SECRETS_DIR/wallet.json"
