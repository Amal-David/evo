#!/usr/bin/env bash
set -Eeuo pipefail

readonly data_dir=/data
readonly state_dir="$data_dir/state"
readonly log_file="$data_dir/logs/shinka-flock-autonomous.log"
readonly workspace_parent="$data_dir/workspace"
readonly benchmark_dir="$workspace_parent/flock-challenge-multi"
readonly benchmark_name=eigenlabs/flock-challenge-multi/x86
readonly frontier_branch=main
readonly model=opencode/x-preview-f-free
readonly variant=max
readonly target_path="${SHINKA_TARGET_PATH:-crates/flock-prover/src/recycle_alloc.rs}"
readonly max_target_bytes="${SHINKA_MAX_TARGET_BYTES:-100000}"
readonly memory_soft_limit="${SHINKA_MEMORY_SOFT_LIMIT:-30064771072}"
readonly frontier_check_interval="${SHINKA_FRONTIER_CHECK_INTERVAL:-900}"

mkdir -p "$state_dir" "$data_dir/logs" "$workspace_parent" "$data_dir/shinka"
exec > >(tee -a "$log_file") 2>&1

log() {
  echo "[$(date -u +%FT%TZ)] $*"
}

hold_on_error() {
  local status=$?
  printf '%s status=%s\n' "$(date -u +%FT%TZ)" "$status" \
    > "$state_dir/shinka-bootstrap-last-error"
  log "Shinka bootstrap stopped with status $status; holding for inspection"
  exec sleep infinity
}
trap hold_on_error ERR

exec 9>"$state_dir/shinka-supervisor.lock"
if ! flock -n 9; then
  log "Another Shinka supervisor owns the lock"
  exit 75
fi

cleanup() {
  rm -f "$state_dir/shinka-supervisor.pid" "$state_dir/shinka-runner.pid"
}
trap cleanup EXIT
echo "$$" > "$state_dir/shinka-supervisor.pid"
echo v1 > "$state_dir/shinka-supervisor-version"
rm -f "$state_dir/shinka-bootstrap-last-error"

log "Installing the current Yukon CLI and agent skill"
curl -fsSL https://api.yukon.org/yukon/install.sh | sh
yukon install-skill --target opencode
yukon install-skill --target agents

log "Verifying Shinka, Headless, OpenCode and sandbox prerequisites"
python3 -c 'import shinka'
shinka_run --help >/dev/null
headless --check
opencode --version
bwrap --version
python3 - <<'PY'
from shinka.llm.providers.headless import _VALID_EFFORTS
assert _VALID_EFFORTS == {"low", "medium", "high", "xhigh"}
PY

if [ ! -d "$benchmark_dir/.git" ]; then
  log "Cloning eigenlabs/flock-challenge-multi with Yukon"
  cd "$workspace_parent"
  yukon clone eigenlabs/flock-challenge-multi
fi

cd "$benchmark_dir"
git remote get-url origin | grep -Eq \
  'Layr-Labs/flock-challenge-multi|eigenlabs/flock-challenge-multi'
test -f benchmark.json
jq -e \
  --arg target "$target_path" \
  '.schemaVersion == 2 and any(.tracks[]; .name == "x86" and any(.editablePaths[]; . as $editable | $target == $editable or ($target | startswith($editable + "/"))))' \
  benchmark.json >/dev/null

git status --short > "$state_dir/shinka-frontier-preflight-status"
test ! -s "$state_dir/shinka-frontier-preflight-status"
git fetch --quiet origin "$frontier_branch:refs/remotes/origin/$frontier_branch"
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/$frontier_branch)" ]; then
  git merge --ff-only "origin/$frontier_branch"
fi
base_commit=$(git rev-parse HEAD)
target_bytes=$(git cat-file -s "$base_commit:$target_path")
if [ "$target_bytes" -gt "$max_target_bytes" ]; then
  log "Target file is too large for the configured Shinka source budget"
  false
fi
printf '%s local=%s promoted=%s target=%s\n' \
  "$(date -u +%FT%TZ)" "$base_commit" "$base_commit" "$target_path" \
  > "$state_dir/shinka-frontier-current"

log "Running Yukon setup for the promoted Flock frontier"
FLOCK_REQUIRE_SANDBOX=1 yukon setup --track x86 \
  2>&1 | tee "$state_dir/shinka-setup.log"
yukon submissions "$benchmark_name" --all \
  > "$state_dir/shinka-submissions.txt"
date -u +%FT%TZ > "$state_dir/shinka-submissions-refreshed-at"

target_id=$(printf '%s' "$target_path" | sha256sum | awk '{print substr($1,1,16)}')
task_dir="$data_dir/shinka/tasks/$target_id"
results_dir="$data_dir/shinka/results/$base_commit/$target_id"
mkdir -p "$task_dir" "$results_dir"
cp /workspace/deploy/render/shinka-flock/evaluate.py "$task_dir/evaluate.py"
cp /workspace/deploy/render/shinka-flock/run_evo.py "$task_dir/run_evo.py"
{
  echo '// EVOLVE-BLOCK-START'
  git show "$base_commit:$target_path"
  echo '// EVOLVE-BLOCK-END'
} > "$task_dir/initial.rs"
printf '%s base=%s target=%s model=%s variant=%s\n' \
  "$(date -u +%FT%TZ)" "$base_commit" "$target_path" "$model" "$variant" \
  > "$state_dir/shinka-campaign"

restart_count=0
if [ -s "$state_dir/shinka-restarts" ]; then
  restart_count=$(tr -cd '0-9' < "$state_dir/shinka-restarts")
fi

while true; do
  restart_count=$((restart_count + 1))
  printf '%s\n' "$restart_count" > "$state_dir/shinka-restarts"
  log "Launching ShinkaEvolve attempt $restart_count with $model variant $variant"

  setsid env \
    SHINKA_BENCHMARK_DIR="$benchmark_dir" \
    SHINKA_BASE_COMMIT="$base_commit" \
    SHINKA_TARGET_PATH="$target_path" \
    SHINKA_RESULTS_DIR="$results_dir" \
    SHINKA_STATE_DIR="$state_dir" \
    python3 "$task_dir/run_evo.py" &
  child_pid=$!
  echo "$child_pid" > "$state_dir/shinka-runner.pid"
  pressure_stopped=0
  frontier_stopped=0
  next_frontier_check=$(( $(date +%s) + frontier_check_interval ))

  while kill -0 "$child_pid" 2>/dev/null; do
    memory_current=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
    printf '%s memory_current=%s attempt=%s child=%s model=%s variant=%s\n' \
      "$(date -u +%FT%TZ)" "$memory_current" "$restart_count" \
      "$child_pid" "$model" "$variant" \
      > "$state_dir/shinka-supervisor-heartbeat"
    if [ "$memory_current" -ge "$memory_soft_limit" ]; then
      pressure_stopped=1
      log "Memory reached the configured ceiling; stopping before OOM"
      kill -TERM -- "-$child_pid" 2>/dev/null || true
      sleep 10
      kill -KILL -- "-$child_pid" 2>/dev/null || true
      break
    fi
    if [ "$(date +%s)" -ge "$next_frontier_check" ]; then
      promoted_frontier=$(git ls-remote origin "refs/heads/$frontier_branch" | \
        awk 'NR == 1 { print $1 }')
      if [ -n "$promoted_frontier" ] && [ "$promoted_frontier" != "$base_commit" ]; then
        frontier_stopped=1
        printf '%s local=%s promoted=%s\n' \
          "$(date -u +%FT%TZ)" "$base_commit" "$promoted_frontier" \
          > "$state_dir/shinka-frontier-stale-detected"
        log "Promoted frontier moved; stopping the stale Shinka campaign"
        kill -TERM -- "-$child_pid" 2>/dev/null || true
        sleep 30
        kill -KILL -- "-$child_pid" 2>/dev/null || true
        break
      fi
      next_frontier_check=$(( $(date +%s) + frontier_check_interval ))
    fi
    sleep 10
  done

  if wait "$child_pid"; then
    status=0
  else
    status=$?
  fi
  rm -f "$state_dir/shinka-runner.pid"
  printf '%s\n' "$status" > "$state_dir/shinka-last-exit"

  if [ "$frontier_stopped" -eq 1 ]; then
    log "Reloading the current promoted frontier into a fresh Shinka epoch"
    flock -u 9
    exec /usr/local/bin/shinka-flock-research
  elif [ "$pressure_stopped" -eq 1 ] || [ "$status" -eq 137 ]; then
    delay=900
  elif [ "$status" -eq 0 ]; then
    delay=1800
  else
    delay=300
  fi
  printf '%s status=%s next_retry_seconds=%s\n' \
    "$(date -u +%FT%TZ)" "$status" "$delay" \
    > "$state_dir/shinka-last-restart"
  log "ShinkaEvolve exited with status $status; retrying in $delay seconds"
  sleep "$delay"
done
