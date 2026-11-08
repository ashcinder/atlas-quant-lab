ARG ATLAS_E2E_WEB_BASE=atlas-quant-web:r23-local
FROM ${ATLAS_E2E_WEB_BASE}
COPY . /usr/share/nginx/html
