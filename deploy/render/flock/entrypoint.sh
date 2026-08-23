#!/usr/bin/env bash
set -Eeuo pipefail

runtime_home=/data/home
state_dir=/data/state
log_dir=/data/logs
workspace_dir=/data/workspace

mkdir -p "$runtime_home" "$state_dir" "$log_dir" "$workspace_dir"
chown -R runner:runner "$runtime_home" "$state_dir" "$log_dir" "$workspace_dir"

# Render private services must accept connections on their assigned TCP port.
# Serve an empty directory so the health listener cannot expose runner state.
mkdir -p /tmp/flock-health
python3 -m http.server "${PORT:-10000}" \
  --bind 0.0.0.0 --directory /tmp/flock-health >/dev/null 2>&1 &

if [ -z "${YUKON_API_TOKEN:-}" ]; then
  echo "YUKON_API_TOKEN is required" >&2
  exec sleep infinity
fi

exec runuser -u runner -- env \
  HOME="$runtime_home" \
  XDG_CONFIG_HOME="$runtime_home/.config" \
  XDG_DATA_HOME="$runtime_home/.local/share" \
  PATH="$runtime_home/.local/bin:/usr/local/bin:/usr/bin:/bin" \
  YUKON_API_TOKEN="$YUKON_API_TOKEN" \
  EVO_TELEMETRY=0 \
  RAYON_NUM_THREADS=8 \
  NODE_OPTIONS=--max-old-space-size=4096 \
  /usr/local/bin/flock-research
