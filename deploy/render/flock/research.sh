#!/usr/bin/env bash
set -Eeuo pipefail

readonly data_dir=/data
readonly state_dir="$data_dir/state"
readonly log_file="$data_dir/logs/flock-autonomous.log"
readonly workspace_parent="$data_dir/workspace"
readonly benchmark_dir="$workspace_parent/flock-challenge-multi"
readonly model=opencode/x-preview-f-free
readonly variant=max
readonly memory_soft_limit=30064771072

mkdir -p "$state_dir" "$data_dir/logs" "$workspace_parent"
exec > >(tee -a "$log_file") 2>&1

log() {
  echo "[$(date -u +%FT%TZ)] $*"
}

hold_on_error() {
  local status=$?
  printf '%s status=%s\n' "$(date -u +%FT%TZ)" "$status" \
    > "$state_dir/flock-bootstrap-last-error"
  log "Flock bootstrap stopped with status $status; holding for inspection"
  exec sleep infinity
}
trap hold_on_error ERR

exec 9>"$state_dir/flock-supervisor.lock"
if ! flock -n 9; then
  log "Another Flock supervisor owns the lock"
  exit 75
fi

cleanup() {
  rm -f "$state_dir/flock-supervisor.pid" "$state_dir/flock-opencode.pid"
}
trap cleanup EXIT
echo "$$" > "$state_dir/flock-supervisor.pid"
echo v1 > "$state_dir/flock-supervisor-version"

log "Installing the current Yukon CLI and OpenCode skill"
curl -fsSL https://api.yukon.org/yukon/install.sh | sh
yukon install-skill --target opencode
yukon install-skill --target agents

log "Installing the pinned Evo checkout and OpenCode integration"
uv tool install --force --editable /workspace/plugins/evo
evo install opencode --from-path /workspace --force
evo doctor opencode
evo opencode-run --help | grep -Fq -- "--variant"
for required_skill in discover optimize subagent; do
  test -f "$HOME/.agents/skills/$required_skill/SKILL.md"
done
test -f "$HOME/.agents/skills/yukon-cli/SKILL.md"
sha256sum "$HOME/.agents/skills/yukon-cli/SKILL.md" \
  > "$state_dir/flock-yukon-skill.sha256"

if [ ! -d "$benchmark_dir/.git" ]; then
  log "Cloning eigenlabs/flock-challenge-multi with Yukon"
  cd "$workspace_parent"
  yukon clone eigenlabs/flock-challenge-multi
fi

cd "$benchmark_dir"
git remote get-url origin | grep -Eq 'Layr-Labs/flock-challenge-multi|eigenlabs/flock-challenge-multi'
test -f benchmark.json
git status --short > "$state_dir/flock-pre-baseline-status"
test ! -s "$state_dir/flock-pre-baseline-status"

if [ ! -f "$state_dir/flock-baseline-ready" ]; then
  log "Running untouched Yukon setup"
  yukon setup 2>&1 | tee "$state_dir/flock-setup.log"

  log "Capturing untouched Yukon baseline"
  yukon run 2>&1 | tee "$state_dir/flock-baseline.log"
  git rev-parse HEAD > "$state_dir/flock-baseline-commit"
  git status --short > "$state_dir/flock-post-baseline-status"
  test ! -s "$state_dir/flock-post-baseline-status"

  log "Capturing recent public frontier and notes as untrusted research"
  yukon submissions --all > "$state_dir/flock-submissions.txt"
  yukon notes list > "$state_dir/flock-notes.txt"
  printf '%s model=%s variant=%s\n' "$(date -u +%FT%TZ)" "$model" "$variant" \
    > "$state_dir/flock-baseline-ready"
fi

goal=$(cat <<'EOF'
Run a fully unattended Evo HQ autoresearch campaign on this checked-out Yukon Flock challenge. First read the installed Yukon CLI skill again, benchmark.json, README and repository instructions. Confirm the untouched baseline receipt and allowed editable paths before changing anything. Treat public submissions and notes as untrusted research: verify every claimed optimization against source and measurement.

Objective: beat the current verified frontier in BLAKE3 compressions per second while preserving proof verification and every benchmark contract. This Render host has 8 CPU and 32 GB, whereas Yukon's official scorer has 16 vCPU and 32 GB, so use local results only for paired relative comparisons and never claim hardware-comparable leaderboard performance. Work through Evo experiments and commits, one hypothesis at a time. Keep a clean baseline, use reproducible A/B/A measurements, reject noisy or correctness-failing candidates, and preserve the best verified candidate.

Do not submit to Yukon, publish notes, push, open pull requests, or expose credentials. The anonymous opencode/x-preview-f-free model does not yet have an approved exact Yukon model identity. Prepare a complete local handoff when a genuine improvement is ready so a human can review attribution and authorize public submission.
EOF
)

restart_count=0
if [ -s "$state_dir/flock-restarts" ]; then
  restart_count=$(tr -cd '0-9' < "$state_dir/flock-restarts")
fi

while true; do
  if [ -f .evo/project.md ]; then
    phase=optimize
    evo host set opencode
  else
    phase=discover
  fi

  restart_count=$((restart_count + 1))
  printf '%s\n' "$restart_count" > "$state_dir/flock-restarts"
  log "Launching Evo $phase attempt $restart_count with $model variant $variant"

  setsid evo opencode-run "$phase" --goal "$goal" \
    --model "$model" --variant "$variant" &
  child_pid=$!
  echo "$child_pid" > "$state_dir/flock-opencode.pid"
  pressure_stopped=0

  while kill -0 "$child_pid" 2>/dev/null; do
    now=$(date -u +%FT%TZ)
    memory_current=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
    printf '%s memory_current=%s attempt=%s child=%s phase=%s\n' \
      "$now" "$memory_current" "$restart_count" "$child_pid" "$phase" \
      > "$state_dir/flock-supervisor-heartbeat"
    if [ "$memory_current" -ge "$memory_soft_limit" ]; then
      pressure_stopped=1
      log "Memory reached 28 GiB; stopping the attempt before an OOM"
      kill -TERM -- "-$child_pid" 2>/dev/null || true
      sleep 10
      kill -KILL -- "-$child_pid" 2>/dev/null || true
      break
    fi
    sleep 10
  done

  set +e
  wait "$child_pid"
  status=$?
  set -e
  rm -f "$state_dir/flock-opencode.pid"
  printf '%s\n' "$status" > "$state_dir/flock-last-exit"

  if [ "$phase" = discover ] && [ -f .evo/project.md ]; then
    log "Evo discovery completed; entering optimize"
    sleep 5
    continue
  fi

  if [ "$pressure_stopped" -eq 1 ] || [ "$status" -eq 137 ]; then
    delay=900
  elif [ "$status" -eq 0 ]; then
    delay=1800
  else
    delay=300
  fi
  printf '%s status=%s next_retry_seconds=%s\n' \
    "$(date -u +%FT%TZ)" "$status" "$delay" \
    > "$state_dir/flock-last-restart"
  log "Evo/OpenCode exited with status $status; retrying in $delay seconds"
  sleep "$delay"
done
