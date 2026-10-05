FROM node:24-bookworm-slim AS relay
WORKDIR /app/contracts
COPY contracts/package.json contracts/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM python:3.14.7-slim-bookworm AS wheels
WORKDIR /build
RUN sed -i 's|http://deb.debian.org|https://mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN pip wheel --index-url https://mirrors.cloud.tencent.com/pypi/simple --no-cache-dir --wheel-dir /wheels -r requirements.lock

FROM python:3.14.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/app/backend/.data/cache \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1
WORKDIR /app/backend
RUN sed -i 's|http://deb.debian.org|https://mirrors.cloud.tencent.com|g' /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends openssl libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=wheels /wheels /wheels
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock \
    && pip check \
    && rm -rf /wheels \
    && groupadd --gid 10001 atlas \
    && useradd --uid 10001 --gid atlas --no-create-home atlas \
    && mkdir -p /app/backend/.data \
    && chown atlas:atlas /app/backend/.data \
    && chmod 700 /app/backend/.data
COPY backend/app ./app
COPY --from=relay /usr/local/bin/node /usr/local/bin/node
COPY --from=relay /app/contracts/node_modules /app/contracts/node_modules
COPY contracts/scripts/decode-transaction.mjs /app/contracts/scripts/decode-transaction.mjs
COPY scripts/prove-private-program.py scripts/prepare-zk-witness.py scripts/verify-proof-bundle.py scripts/import-verified-proof.py /app/scripts/
RUN mkdir -p /app/strategy/zkvm/target/release
COPY strategy/zkvm/profiles.json /app/strategy/zkvm/profiles.json
# The Linux verifier is an explicitly supplied release artifact, not the local
# macOS target binary. Build fails if its architecture, hash, or image ID drifts.
COPY strategy/zkvm/release/linux-amd64/atlas-zkvm /app/strategy/zkvm/target/release/atlas-zkvm
RUN chmod 0555 /app/strategy/zkvm/target/release/atlas-zkvm \
    && python -c "import hashlib,json,struct,subprocess; p='/app/strategy/zkvm/target/release/atlas-zkvm'; b=open(p,'rb').read(); assert b[:4]==b'\\x7fELF' and struct.unpack_from('<H',b,18)[0]==62; assert hashlib.sha256(b).hexdigest()=='b62a2d6ed3dd49e0f02762f8291aab2f075c4f0686290844113779d797d582b3'; d=json.loads(subprocess.check_output([p,'profile','--profile','atlas_program_backtest_risc0_v2'])); assert d['image_id']=='02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4'"
USER 10001:10001
EXPOSE 8000
# In-process research jobs and alert monitoring require exactly one worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log", "--timeout-graceful-shutdown", "30"]
