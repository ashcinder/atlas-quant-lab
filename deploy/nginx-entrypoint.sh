#!/bin/sh
set -eu

proxy_ip=${ATLAS_TLS_PROXY_IP:-172.30.120.1}
case "$proxy_ip" in
  ''|*[!0-9.]*)
    printf '%s\n' 'ATLAS_TLS_PROXY_IP must be one IPv4 address' >&2
    exit 1
    ;;
esac

sed "s/__ATLAS_TLS_PROXY_IP__/$proxy_ip/g" \
  /etc/nginx/nginx.conf.template > /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g 'daemon off;'
