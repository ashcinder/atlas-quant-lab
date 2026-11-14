FROM python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg HOME=/tmp TMPDIR=/tmp MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /opt/atlas
COPY deploy/rqalpha-runner.requirements.lock /opt/atlas/requirements.lock
COPY deploy/rqalpha-runner.build-constraints.txt /opt/atlas/build-constraints.txt
RUN python -I -m pip --isolated --disable-pip-version-check install --no-cache-dir --index-url https://pypi.org/simple 'pip==26.2.2' && python -I -m pip --isolated --disable-pip-version-check install --no-cache-dir --build-constraint /opt/atlas/build-constraints.txt --only-binary=:all: --no-binary=rqalpha,rqrisk --index-url https://pypi.org/simple -r /opt/atlas/requirements.lock && python -I -m pip check
COPY strategy/runner/rqalpha_worker.py /opt/atlas/rqalpha_worker.py
USER 65532:65532
ENTRYPOINT ["python", "-I", "/opt/atlas/rqalpha_worker.py"]
