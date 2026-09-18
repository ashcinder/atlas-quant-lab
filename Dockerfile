# ============================================================
# Atlas Quant - All-in-One Docker Image
# ============================================================
# This image contains: Frontend + Backend + Supervisor + ZKVM
# Built for simple deployment: docker run -p 8080:8080 <image>
# ============================================================

FROM node:24-bookworm-slim AS frontend-build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund 2>/dev/null || true
COPY frontend/ ./
RUN npm run build

FROM golang:1.23-bookworm AS supervisor-build
WORKDIR /build/supervisor
COPY Supervisor/brokerchain-supervisor/go.mod Supervisor/brokerchain-supervisor/go.sum ./
RUN go mod download
COPY Supervisor/brokerchain-supervisor/ ./
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-w -s" -o supervisor .

FROM python:3.14.7-slim-bookworm AS backend-deps
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential openssl libstdc++6 \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.lock ./requirements.lock
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock

FROM python:3.14.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    XDG_CACHE_HOME=/app/backend/.data/cache \
    OPENBLAS_NUM_THREADS=1 \
    OMP_NUM_THREADS=1

# Install runtime deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssl libstdc++6 nginx supervisor curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 atlas \
    && useradd --uid 10001 --gid atlas --no-create-home atlas \
    && mkdir -p /app/backend/.data /app/supervisor \
    && chown atlas:atlas /app/backend/.data \
    && chmod 700 /app/backend/.data

WORKDIR /app

# Copy Python wheels
COPY --from=backend-deps /wheels /wheels
COPY backend/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.lock \
    && pip check \
    && rm -rf /wheels

# Copy backend
COPY backend/app ./backend/app
COPY scripts/prove-private-program.py scripts/prepare-zk-witness.py ./scripts/

# Copy Supervisor binary (built during image creation)
COPY --from=supervisor-build /build/supervisor/supervisor ./supervisor/

# Copy contracts relay (Node.js for contract scripts)
COPY --from=frontend-build /usr/local/bin/node /usr/local/bin/node
COPY contracts/package.json contracts/package-lock.json ./contracts/
RUN npm ci --omit=dev --no-audit --no-fund 2>/dev/null || true
COPY contracts/scripts/decode-transaction.mjs ./contracts/scripts/
COPY contracts/ ./contracts/

# Copy ZKVM
COPY strategy/zkvm/profiles.json ./strategy/zkvm/
COPY strategy/zkvm/target/release/atlas-zkvm ./strategy/zkvm/target/release/atlas-zkvm || true
RUN chmod 0555 ./strategy/zkvm/target/release/atlas-zkvm 2>/dev/null || true

# Copy frontend dist
COPY --from=frontend-build /app/dist ./frontend/dist

# Copy startup scripts
COPY deploy/start.sh ./start.sh
COPY deploy/supervisord.conf /etc/supervisor/supervisord.conf
RUN chmod +x ./start.sh

EXPOSE 8080

USER 10001:10001

HEALTHCHECK --interval=15s --timeout=5s --start-period=45s --retries=4 \
    CMD python -c "import json, urllib.request; r = json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=3)); assert r['status'] == 'ok'"

CMD ["./start.sh"]
