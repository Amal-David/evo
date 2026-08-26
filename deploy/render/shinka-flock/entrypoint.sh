#!/usr/bin/env bash
set -Eeuo pipefail

readonly runtime_home=/data/home
readonly state_dir=/data/state
readonly log_dir=/data/logs
readonly workspace_dir=/data/workspace
readonly shinka_dir=/data/shinka

mkdir -p \
  "$runtime_home" \
  "$state_dir" \
  "$log_dir" \
  "$workspace_dir" \
  "$shinka_dir"
chown -R runner:runner \
  "$runtime_home" \
  "$state_dir" \
  "$log_dir" \
  "$workspace_dir" \
  "$shinka_dir"

# Render private services still need a listener. Serve an empty directory so
# the health endpoint cannot expose research state, source, or credentials.
mkdir -p /tmp/shinka-flock-health
python3 -m http.server "${PORT:-10000}" \
  --bind 0.0.0.0 --directory /tmp/shinka-flock-health >/dev/null 2>&1 &

if [ -z "${YUKON_API_TOKEN:-}" ]; then
  echo "YUKON_API_TOKEN is required" >&2
  exec sleep infinity
fi

exec runuser -u runner -- env \
  HOME="$runtime_home" \
  XDG_CONFIG_HOME="$runtime_home/.config" \
  XDG_DATA_HOME="$runtime_home/.local/share" \
  OPENCODE_DATA_HOME="$runtime_home/.local/share/opencode" \
  PATH="/opt/shinka/bin:/opt/shinka/venv/bin:$runtime_home/.local/bin:/usr/local/bin:/usr/bin:/bin" \
  YUKON_API_TOKEN="$YUKON_API_TOKEN" \
  SHINKA_PRICING_MODE=offline \
  SHINKA_HEADLESS_COMMAND=headless \
  SHINKA_HEADLESS_TIMEOUT="${SHINKA_HEADLESS_TIMEOUT:-3600}" \
  RAYON_NUM_THREADS="${RAYON_NUM_THREADS:-8}" \
  NODE_OPTIONS="${NODE_OPTIONS:---max-old-space-size=4096}" \
  /usr/local/bin/shinka-flock-research
