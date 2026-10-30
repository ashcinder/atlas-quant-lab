#!/bin/sh
set -eu
umask 077

api_ip=${ATLAS_API_IP:-172.30.123.2}
case "$api_ip" in
  ''|*[!0-9.]*)
    printf '%s\n' 'ATLAS_API_IP must be one IPv4 address' >&2
    exit 1
    ;;
esac

test -r "${ATLAS_SUPERVISOR_DB_PASSWORD_FILE:?set ATLAS_SUPERVISOR_DB_PASSWORD_FILE}"
mkdir -p /tmp/supervisor-client-body /tmp/supervisor-proxy \
  /tmp/supervisor-fastcgi /tmp/supervisor-uwsgi /tmp/supervisor-scgi
sed "s/__ATLAS_API_IP__/$api_ip/g" \
  /etc/nginx/supervisor.conf.template > /tmp/nginx-supervisor.conf

supervisor_pid=''
nginx_pid=''
stop_all() {
  trap - TERM INT EXIT
  if [ -n "$nginx_pid" ]; then kill "$nginx_pid" 2>/dev/null || true; fi
  if [ -n "$supervisor_pid" ]; then kill "$supervisor_pid" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap stop_all TERM INT EXIT

/usr/local/bin/atlas-isolated-supervisor &
supervisor_pid=$!
nginx -c /tmp/nginx-supervisor.conf -g 'daemon off;' &
nginx_pid=$!

while kill -0 "$supervisor_pid" 2>/dev/null && kill -0 "$nginx_pid" 2>/dev/null; do
  sleep 1
done
printf '%s\n' 'Supervisor or its private RPC proxy exited unexpectedly' >&2
exit 1
