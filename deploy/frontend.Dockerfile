FROM node:24.20.0-bookworm-slim AS build
ARG VITE_TRINE_DEMO_MODE=false
ARG VITE_TRINE_TEST_PRIVATE_KEY=
ENV VITE_TRINE_DEMO_MODE=$VITE_TRINE_DEMO_MODE
ENV VITE_TRINE_TEST_PRIVATE_KEY=$VITE_TRINE_TEST_PRIVATE_KEY
ENV NODE_OPTIONS=--max-old-space-size=1024
WORKDIR /app
RUN test "$VITE_TRINE_DEMO_MODE" = false && test -z "$VITE_TRINE_TEST_PRIVATE_KEY"
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://mirrors.cloud.tencent.com/npm/ --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28.3-alpine
ENV ATLAS_TLS_PROXY_IP=172.30.120.1
COPY deploy/nginx.conf /etc/nginx/nginx.conf.template
COPY deploy/nginx-entrypoint.sh /usr/local/bin/atlas-nginx-entrypoint
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
# Bypass root-oriented image entrypoint scripts. All runtime writes go to /tmp.
ENTRYPOINT ["/usr/local/bin/atlas-nginx-entrypoint"]
