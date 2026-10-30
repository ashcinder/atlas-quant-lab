ARG ATLAS_WEB_BASE_IMAGE=atlas-quant-web:20261030-lab-v1-amd64
FROM ${ATLAS_WEB_BASE_IMAGE}

ARG ATLAS_SUPERVISOR_BINARY_SHA256
USER root
COPY deploy/chain/.build/atlas-isolated-supervisor-linux-amd64 /usr/local/bin/atlas-isolated-supervisor
COPY deploy/chain/nginx-supervisor.conf /etc/nginx/supervisor.conf.template
COPY deploy/chain/start-supervisor.sh /usr/local/bin/atlas-start-supervisor
RUN test -n "$ATLAS_SUPERVISOR_BINARY_SHA256" \
    && printf '%s  %s\n' "$ATLAS_SUPERVISOR_BINARY_SHA256" /usr/local/bin/atlas-isolated-supervisor | sha256sum -c - \
    && chmod 0555 /usr/local/bin/atlas-isolated-supervisor /usr/local/bin/atlas-start-supervisor \
    && mkdir -p /var/lib/atlas-supervisor/state \
    && chown -R 101:101 /var/lib/atlas-supervisor \
    && chmod 0700 /var/lib/atlas-supervisor /var/lib/atlas-supervisor/state

USER 101:101
EXPOSE 42515
ENTRYPOINT ["/usr/local/bin/atlas-start-supervisor"]
