FROM node:24.20.0-bookworm-slim AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.28.3-alpine
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
USER 101:101
EXPOSE 8080
# Bypass root-oriented image entrypoint scripts. All runtime writes go to /tmp.
ENTRYPOINT ["nginx"]
CMD ["-g", "daemon off;"]
