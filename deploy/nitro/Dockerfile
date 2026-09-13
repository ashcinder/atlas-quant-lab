FROM rust:1.85-bookworm AS nsm
WORKDIR /build
COPY deploy/nitro/nsm/ ./
RUN cargo build --release --locked
FROM python:3.14.7-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openssl libseccomp2 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir cryptography==50.0.0
WORKDIR /app
COPY --from=nsm /build/target/release/atlas-nsm /usr/local/bin/atlas-nsm
COPY deploy/nitro/protocol.py deploy/nitro/enclave.py deploy/nitro/worker.py /app/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "-I", "/app/enclave_entry.py"]
# -I omits /app from sys.path; explicitly add only the measured application directory.
COPY deploy/nitro/enclave_entry.py /app/
