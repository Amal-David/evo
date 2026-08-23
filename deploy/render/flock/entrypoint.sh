#!/usr/bin/env bash
set -Eeuo pipefail

runtime_home=/data/home
state_dir=/data/state
log_dir=/data/logs
workspace_dir=/data/workspace

mkdir -p "$runtime_home" "$state_dir" "$log_dir" "$workspace_dir"
chown -R runner:runner "$runtime_home" "$state_dir" "$log_dir" "$workspace_dir"

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
