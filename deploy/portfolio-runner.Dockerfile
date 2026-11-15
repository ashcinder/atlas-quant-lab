FROM python:3.12.14-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /runner
COPY deploy/portfolio-runner.requirements.lock /runner/requirements.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: -r /runner/requirements.lock && python -m pip check
COPY strategy/sdk/python/atlas_strategy_sdk /usr/local/lib/python3.12/site-packages/atlas_strategy_sdk
COPY strategy/runner/worker.py /runner/worker.py
USER 65532:65532
ENTRYPOINT ["python", "-I", "/runner/worker.py"]
