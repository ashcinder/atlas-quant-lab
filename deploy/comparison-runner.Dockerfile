# Pass a fixed, verified Linux RQAlpha image ID from the deployment host.
ARG RQALPHA_BASE
FROM ${RQALPHA_BASE}
USER root
COPY deploy/comparison-runner.requirements.lock /opt/trine/headless.lock
RUN python -m pip --disable-pip-version-check install --no-cache-dir --index-url https://mirrors.cloud.tencent.com/pypi/simple -r /opt/trine/headless.lock
RUN python -m pip --disable-pip-version-check install --no-cache-dir --no-deps --index-url https://mirrors.cloud.tencent.com/pypi/simple https://codeload.github.com/ashcinder/vnpy/tar.gz/fa5206fe63836f3f8cd1ebd7168fbd19a5e2ff09 https://codeload.github.com/vnpy/vnpy_ctastrategy/tar.gz/7a8768de9784dda35a7b261a7ade1dbfbff50919
COPY backend/engine_workers /opt/trine/backend/engine_workers
COPY backend/app/backtest/unified.py /opt/trine/backend/app/backtest/unified.py
USER 65532:65532
ENV HOME=/tmp
ENTRYPOINT ["python", "/opt/trine/backend/engine_workers/native.py"]
