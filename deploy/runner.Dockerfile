FROM python:3.14.7-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
WORKDIR /runner
COPY strategy/sdk/python/atlas_strategy_sdk /usr/local/lib/python3.14/site-packages/atlas_strategy_sdk
COPY strategy/runner/worker.py /runner/worker.py
USER 65532:65532
ENTRYPOINT ["python", "-I", "/runner/worker.py"]
