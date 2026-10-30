# Isolated lab Supervisor containers

This stack adds a single-node, test-only chain and MySQL 8.4 to the release Web/API stack. It is suitable for local integration and later native server smoke testing. It is not a production consensus network, does not custody real funds, and does not provide TEE attestation.

The Go process remains bound to `127.0.0.1:42519` inside its container. An Nginx listener exposes port 42515 only on the Compose network and permits the fixed API address. Neither MySQL nor RPC publishes a host port. MySQL uses a separate internal network shared only with Supervisor.

Create a private configuration, build the fixed `linux/amd64` image, and start the release stack plus this overlay:

```bash
deploy/chain/init-secrets.sh /absolute/private/atlas-chain
set -a
. /absolute/private/atlas-chain/chain.env
. /absolute/private/lab-release.env
set +a
deploy/chain/build-image.sh
docker compose --env-file /absolute/private/lab-release.env --env-file /absolute/private/atlas-chain/chain.env \
  -f compose.release.yaml -f compose.chain.yaml up -d --no-build --pull never
```

The generated public environment sets `ATLAS_CHAIN_MODE=isolated_lab`, the fixed Supervisor and MySQL image tags, the isolated subnet, and the three public test addresses. The password and wallet key values never enter that environment file.

The wallet file and both database password files are mode 0600. Back up both named volumes together while the API and Supervisor are stopped; MySQL rows and the chain state trie form one logical state. Deleting either volume creates a different test chain. Restarting the existing volumes does not reseed balances or nonce.
