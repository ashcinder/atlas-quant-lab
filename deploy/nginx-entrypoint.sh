#!/bin/sh
set -eu

proxy_ip=${ATLAS_TLS_PROXY_IP:-172.30.120.1}
case "$proxy_ip" in
  ''|*[!0-9.]*)
    printf '%s\n' 'ATLAS_TLS_PROXY_IP must be one IPv4 address' >&2
    exit 1
    ;;
esac

cdn_origins=${ATLAS_PUBLIC_CDN_ORIGINS:-}
for origin in $cdn_origins; do
  if ! printf '%s\n' "$origin" | grep -Eq '^https://[a-zA-Z0-9.-]+(:[0-9]{1,5})?$'; then
    printf '%s\n' 'ATLAS_PUBLIC_CDN_ORIGINS must contain HTTPS origins without paths' >&2
    exit 1
  fi
done
sed -e "s/__ATLAS_TLS_PROXY_IP__/$proxy_ip/g" \
  -e "s|__ATLAS_PUBLIC_CDN_ORIGINS__|$cdn_origins|g" \
  /etc/nginx/nginx.conf.template > /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
