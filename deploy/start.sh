#!/bin/bash
# Startup script for trine-runtime-web to inject environment variables

# Wait for nginx to start
sleep 2

# Inject VITE environment variables into the served JS files
VITE_DEMO_MODE=${VITE_TRINE_DEMO_MODE:-true}
VITE_TEST_KEY=${VITE_TRINE_TEST_PRIVATE_KEY:-0f7597919f8d6442707e93d2723adca206e9090623914942bf876bd6b4f5e5c9}

# Replace in all JS files
for f in /usr/share/nginx/html/assets/*.js; do
  if [ -f "$f" ]; then
    sed -i "s/\"DEV\"[,:][^}]*import.meta.env.VITE_TRINE_DEMO_MODE[^}]*}/\"DEV\": false, \"VITE_TRINE_DEMO_MODE\": \"$VITE_DEMO_MODE\", \"VITE_TRINE_TEST_PRIVATE_KEY\": \"$VITE_TEST_KEY\"}/g" "$f" 2>/dev/null
    sed -i "s/VITE_TRINE_DEMO_MODE[^,;)]*==[^,;)]*'true'[^,;)]*VITE_TRINE_TEST_PRIVATE_KEY/true \&\& \"$VITE_TEST_KEY\"/g" "$f" 2>/dev/null
  fi
done

echo "Environment variables injected into frontend assets"

# Run nginx
exec nginx -g "daemon off;"
