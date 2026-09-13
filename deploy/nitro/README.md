# Atlas confidential hosting — AWS Nitro deployment kit

Status: implementation prepared; local cryptography/policy tests and Rust API compilation pass. **No real Nitro hardware, author KMS authorization, Linux worker sandbox, or end-to-end cloud run has been accepted yet.** The Docker Hub connection failed during the initial image build. Do not advertise this as an already deployed confidential service.

## What this release executes

One encrypted Python `decide(context)` strategy per Enclave, continuously, using the existing Atlas `private_runner` signed-signal endpoint. Context contains a BTCUSDT book and an in-memory step counter. It returns a decimal target weight in [0,1], up to eight decimal places. Python standard-library strategies are supported subject to the sandbox; arbitrary dependencies, persistent Python globals, external AI calls and GPU models are not supported by this image. Each decision uses a fresh process; the step counter resets on a deliberate restart.

Author can go offline after packaging and approval. Strategy source, salted commitment opening and the Ed25519 signing key are encrypted together. Parent receives only the envelope, KMS ciphertext and public signed trading targets. This deliberately reuses the existing platform simulated-execution path: **it does not add automatic live trading or assert that exchange fills/market quotes are authentic.** The existing UI may label this path “开发者本地执行”; that label is not a hardware-attestation indicator. Do not set `tee_verified` from a signature alone.

## Trust boundaries

- Author uses an independently reviewed local client, never the platform webpage, to read source and encrypt it. Review `author.py`, `protocol.py` and dependencies in a trusted checkout. Pin an out-of-band release/commit digest; a checksum downloaded beside a malicious webpage is insufficient.
- An independent author AWS account owns the KMS key. Platform's EC2 role receives only `kms:Decrypt`, conditional on nonzero PCR0/PCR1/PCR2 from the author-approved EIF. Explicit Deny rules also reject each mismatching PCR and unattested decrypt. Platform has no access to the author administrator account, credentials, root recovery or key policy changes.
- Author reviews/builds the public enclave controller image and approves its actual measurements. The public image contains no strategy or credentials. **Do not approve measurements just because the platform supplies them.** Build metadata and dependency updates can change measurements; every new image requires deliberate approval. This Dockerfile is version-pinned, not certified bit-for-bit reproducible or independently audited.
- KMS validates the AWS attestation and returns CMS ciphertext bound to an enclave-generated RSA key. The parent cannot unwrap it. This KMS RSA recipient flow is separate from the backend's existing X25519 attested-channel verifier; no key types are silently interchanged.
- Python child has no signing key, no inherited vsock descriptor, runs as uid 65532, and blocks networking (including VSOCK), process creation, ptrace, ioctl and io_uring via seccomp. CPU, memory, time and output size are bounded. Exceptions and stdout never pass through to the parent; only a validated target is signed by the controller.
- Targets, execution timing and trading activity are intentionally observable and can reveal strategy behavior. This is not protection against inference from authorized outputs. The host can deny service, supply manipulated quotes, or restart the enclave. No anti-rollback state or market authenticity proof is provided. The cloud/hardware trust base and possible side channels remain assumptions.

## Deployment sequence

These trust boundaries require two independent setup steps. Once author approval exists, starting the host is one command. Combining author key administration into the platform deploy script would defeat the confidentiality goal.

### 1. Platform creates a Nitro-capable host

Use `host.yaml` with CloudFormation in the chosen region, passing `AuthorAccount`, `SubnetId`, `VpcId`. The subnet needs outbound internet/NAT for package downloads, KMS, Binance and the HTTPS Atlas backend. No inbound ports are opened; administer with SSM. This template creates a c6i.xlarge instance and encrypted disk and costs money when executed. It has not been applied in this task.

Copy the **reviewed public code** to `/opt/atlas`; do not copy an author's private runner directory. On the host:

```bash
cd /opt/atlas
sudo bash deploy/nitro/setup-host.sh
```

This installs the relay's virtualenv, builds the controller Docker image and EIF, and writes:

- `.artifacts/nitro/atlas.eif`
- `.artifacts/nitro/measurements.json`
- `.artifacts/nitro/atlas.eif.sha256`

The NSM helper uses the official AWS Rust API with a committed Cargo.lock. Build for x86_64 on the template's host. The Docker image has no plaintext strategy. No debug enclave is accepted. Independently reproduce/review the artifact on the author's side before approval.

### 2. Author sets up their independent KMS key

The author runs the policy generator in their own reviewed checkout, using the approved measurements and the platform role ARN from CloudFormation:

```bash
python3 deploy/nitro/key_policy.py \
  --author-role arn:aws:iam::111111111111:role/AuthorKeyAdmin \
  --platform-role arn:aws:iam::222222222222:role/PlatformHostRole \
  --measurements approved-measurements.json > approved-key-policy.json
```

Using the **author's AWS profile**, create a symmetric encryption KMS key with this policy (`aws kms create-key --policy file://approved-key-policy.json`). Record its full key ARN. The author role must be the current key-creation/administration principal. The generator refuses same-account ownership and zero PCRs. The returned key remains author-controlled; revoking the platform decrypt statement prevents subsequent unlocks, but does not erase a key already held by a running enclave. Stop the corresponding strategy instance as well when revoking execution.

### 3. Register and subscribe, then encrypt locally

Use existing `scripts/private-strategy-runner.py init` to initialize the author's strategy directory; upload only `release.public.json` to the strategy center. Subscribe and create a **platform simulation** run; download its connection JSON from strategy trading. Do not start the old local runner simultaneously.

Install `deploy/nitro/requirements.txt` into an author-side virtualenv. With the author AWS profile:

```bash
python deploy/nitro/author.py \
  --directory /private/author-runner \
  --config /private/run-connection.json \
  --key-arn arn:aws:kms:us-east-1:111111111111:key/KEY_UUID \
  --interval 30 \
  --output strategy.nitro-package.json
```

Only the final encrypted `.nitro-package.json` is copied to the parent host. The author client checks the source, public signing key and salted commitment against the selected run's content hash before wrapping the key. Ciphertext header and KMS encryption context bind the package ID and key ARN. Source is not stored in the Atlas database.

### 4. Start continuously

On the parent host, set the public deployment configuration (no plaintext keys):

```bash
export ATLAS_PACKAGE=/opt/atlas-packages/strategy.nitro-package.json
export ATLAS_PLATFORM=https://your-atlas.example
export ATLAS_APPROVED_EIF_SHA256=AUTHOR_APPROVED_EIF_SHA256
sudo --preserve-env=ATLAS_PACKAGE,ATLAS_PLATFORM,ATLAS_APPROVED_EIF_SHA256 \
  bash deploy/nitro/deploy.sh run
```

For background operation, put those three settings in `/etc/atlas-enclave.env` (mode 0600), install the provided `atlas-enclave.service`, then `systemctl enable --now atlas-enclave`. The author can close their computer. **Restart=no** is intentional: unknown order outcomes and rejected signals stop the relay for review rather than replay trades. A host reboot starts a new approved enclave, with fresh in-memory strategy state. The backend independently handles each signed target under existing execution rules.

Only one service/package is supported per host by this launcher. For multiple strategies, use separate hosts or add a reviewed multi-instance lifecycle manager. Never share one enclave with different authors.

## Mandatory cloud acceptance before enabling confidentiality claims

1. Run `docker run --rm --entrypoint python -v "$PWD/deploy/nitro/sandbox_smoke.py:/tmp/smoke.py:ro" atlas-enclave:review -c 'import sys; sys.path.insert(0,"/app"); exec(open("/tmp/smoke.py").read())'`. Requires the real Linux image; this tests the worker, not attestation.
2. Build/run on NSM hardware; author-approved PCRs and a real author KMS key must decrypt successfully. Capture public EIF hash and KMS CloudTrail attestation fields, not secret inputs.
3. Platform role calls Decrypt **without Recipient**: must fail. A debug enclave and a modified controller image must also fail. Wrong PCR1/PCR2, wrong encryption context and different key ARN must fail.
4. Verify the platform cannot put key policy, create grants, or assume the author role. Review account/root recovery ownership separately; code cannot enforce organization ownership.
5. Run the actual encrypted alternating test strategy, verify at least two accepted signed decisions and the resulting simulated buy/sell records in strategy trading and asset overview. Shut down the author computer; execution must continue. Never label this as exchange live fills.
6. Try invalid outputs, network calls, oversized stdout and exception strings containing a canary secret. Only a fixed failure response may leave; search parent process logs and disk for the canary.
7. Tamper with ciphertext; restart with an unapproved EIF; revoke KMS access. New unlocks must fail, without a plaintext fallback.

Local test command:

```bash
backend/.venv/bin/python -m pytest backend/tests/test_nitro_deployment.py backend/tests/test_tee.py -q
cargo check --locked --manifest-path deploy/nitro/nsm/Cargo.toml
```

References: [AWS attested KMS calls](https://docs.aws.amazon.com/kms/latest/developerguide/attested-calls.html), [AWS NSM API](https://github.com/aws/aws-nitro-enclaves-nsm-api), [Nitro KMS walkthrough](https://docs.aws.amazon.com/enclaves/latest/user/connect-enclave-kms.html).

To inventory the reviewed client and controller sources, run `python3 deploy/nitro/release-manifest.py > reviewed-source-manifest.json` and hash that file. Store the digest through an independent trusted channel; on a fresh checkout regenerate the manifest and compare with `cmp`. This inventory is deliberately **not** described as an author signature or a reproducible EIF certificate.
