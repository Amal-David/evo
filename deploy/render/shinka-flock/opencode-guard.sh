#!/usr/bin/env bash
set -Eeuo pipefail

readonly real_opencode=/usr/local/bin/opencode
readonly state_dir=/data/state

args=()
model=
variant=
expect_model=0
expect_variant=0

for arg in "$@"; do
  if [ "$expect_model" -eq 1 ]; then
    model=$arg
    args+=("$arg")
    expect_model=0
    continue
  fi
  if [ "$expect_variant" -eq 1 ]; then
    variant=$arg
    args+=("$arg")
    expect_variant=0
    continue
  fi
  case "$arg" in
    --model)
      args+=("$arg")
      expect_model=1
      ;;
    --variant)
      args+=("$arg")
      expect_variant=1
      ;;
    *)
      args+=("$arg")
      ;;
  esac
done

if [ "$expect_model" -eq 1 ] || [ "$expect_variant" -eq 1 ]; then
  echo "OpenCode wrapper received an option without its value" >&2
  exit 2
fi

# Keep the Headless-to-OpenCode handoff fail closed: the configured free model
# and its supported reasoning variant must reach the native OpenCode process
# unchanged.
if [ "${1:-}" = run ]; then
  if [ -z "$variant" ]; then
    echo "OpenCode wrapper requires an explicit --variant for Shinka runs" >&2
    exit 2
  fi
  if [ "$model" != opencode/mimo-v2.5-free ]; then
    echo "OpenCode wrapper rejected an unexpected model" >&2
    exit 2
  fi
  if [ "$variant" != high ]; then
    echo "OpenCode wrapper rejected an unexpected variant" >&2
    exit 2
  fi
  mkdir -p "$state_dir"
  printf '%s pid=%s model=%s variant=%s\n' \
    "$(date -u +%FT%TZ)" "$$" "$model" "$variant" \
    > "$state_dir/shinka-opencode-last-invocation"
  printf '%s\n' "$$" > "$state_dir/shinka-opencode.pid"
  trap 'rm -f "$state_dir/shinka-opencode.pid"' EXIT
fi

"$real_opencode" "${args[@]}"
