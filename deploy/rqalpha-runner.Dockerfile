FROM --platform=linux/amd64 python@sha256:82bc3c539b8813ada9d68c63b40158fa002f7f33de9bf3312a3dfdc0620dff56
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg HOME=/tmp TMPDIR=/tmp MPLCONFIGDIR=/tmp/matplotlib
WORKDIR /opt/atlas
COPY deploy/rqalpha-runner.requirements.lock /opt/atlas/requirements.lock
COPY deploy/rqalpha-runner.build-constraints.txt /opt/atlas/build-constraints.txt
RUN python -I -m pip --isolated --disable-pip-version-check install --no-cache-dir --index-url https://pypi.org/simple 'pip==26.2.2' && python -I -m pip --isolated --disable-pip-version-check install --no-cache-dir --build-constraint /opt/atlas/build-constraints.txt --only-binary=:all: --no-binary=rqalpha,rqrisk --index-url https://pypi.org/simple -r /opt/atlas/requirements.lock && python -I -m pip check
COPY strategy/runner/rqalpha_worker.py strategy/runner/rqalpha_minutes.py /opt/atlas/
USER 65532:65532
ENTRYPOINT ["python", "-I", "/opt/atlas/rqalpha_worker.py"]
