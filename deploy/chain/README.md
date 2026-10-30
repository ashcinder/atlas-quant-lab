# Isolated lab Supervisor containers

> 当前指南：按QuantJudge实现4be31bf核对（2026-10-30）；环境验收与限制见[统一状态](../../docs/CURRENT_STATUS.md)。

This is the source/build companion to [the complete lab deployment guide](../../docs/LAB_CHAIN_DEPLOYMENT.md). It adds Supervisor and MySQL 8.4 to the release Web/API stack. It is a single-node test chain, not a production consensus network, real-funds service, or TEE.

## Build and install

On a trusted build machine, follow the complete guide to build API/Web and Supervisor with the same source fingerprint, prepare the pinned MySQL base, and package all four exact image IDs. Set the full API/Web image names explicitly; the default two-image tags are not the complete acceptance images. Do not modify sources between builds and packaging. The target machine loads the reviewed package rather than building application sources.

The operator copies the no-secret templates outside the repository, initializes a private chain directory, and merges ENV files as data, without sourcing them as shell code:

```bash
bash deploy/chain/init-secrets.sh /absolute/private/atlas-chain
python3 deploy/chain/merge-env.py /absolute/private/lab.env /absolute/private/atlas-chain/chain.env /absolute/private/full.env
# Review domain, TLS, all image identities, network addresses and resource limits first.
bash deploy/release/start-release.sh /absolute/private/full.env
```

The target requires Linux amd64, at least 8GiB available host memory (12GiB+ recommended), Docker/Compose and the documented operator tools. API uses a 6GiB limit for new proof generation. The complete guide includes HTTPS and hidden-input administrator account creation.

## Network, identity and recovery

The Go process binds to container loopback42519. Nginx exposes42515 only inside Compose and allows the fixed API address. MySQL is on a separate internal network. Neither RPC nor MySQL publishes host ports; the browser signs locally and the API broadcasts signed transactions.

Initialization creates random test wallets and database passwords outside source control. Secret files are0600, the directory0700; the public ENV contains only addresses and paths. The chain locks its genesis identity and rejects address drift. Restarting the original volumes does not reseed balances or nonce.

Cold-backup the business volume, chain state, MySQL and private chain configuration together, stopping writes in API→Supervisor→MySQL order. Use the complete guide's backup/restore tools, which restore to independent volumes and a private directory. Never delete one chain volume and reuse the other. Controlled restart/cold recovery has local acceptance; arbitrary crash atomicity remains unproven.
