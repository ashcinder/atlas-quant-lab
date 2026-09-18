FROM node:24-bookworm-slim AS relay
WORKDIR /app/contracts
COPY contracts/package.json contracts/package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM python:3.14.7-slim-bookworm AS wheels
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock

FROM python:3.14.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/app/backend/.data/cache \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1
WORKDIR /app/backend
RUN apt-get update && apt-get install -y --no-install-recommends openssl libstdc++6 \
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
COPY scripts/prove-private-program.py scripts/prepare-zk-witness.py /app/scripts/
RUN mkdir -p /app/strategy/zkvm/target/release
COPY strategy/zkvm/profiles.json /app/strategy/zkvm/profiles.json
# The release image includes the pinned native RISC Zero verifier built for this
# deployment.  The backend still fails closed when the binary is unavailable.
COPY strategy/zkvm/target/release/atlas-zkvm /app/strategy/zkvm/target/release/atlas-zkvm
RUN chmod 0555 /app/strategy/zkvm/target/release/atlas-zkvm
USER 10001:10001
EXPOSE 8000
# In-process research jobs and alert monitoring require exactly one worker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers", "--no-access-log", "--timeout-graceful-shutdown", "30"]
