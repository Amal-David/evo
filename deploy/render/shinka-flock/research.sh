#!/usr/bin/env bash
set -Eeuo pipefail

readonly data_dir=/data
readonly state_dir="$data_dir/state"
readonly log_file="$data_dir/logs/shinka-flock-autonomous.log"
readonly workspace_parent="$data_dir/workspace"
readonly benchmark_dir="$workspace_parent/flock-challenge-multi"
readonly benchmark_name=eigenlabs/flock-challenge-multi/x86
readonly frontier_branch=main
readonly model=opencode/mimo-v2.5-free
readonly variant=high
readonly target_path="${SHINKA_TARGET_PATH:-crates/flock-prover/src/r1cs_hashes/blake3_witgen8.rs}"
readonly max_target_bytes="${SHINKA_MAX_TARGET_BYTES:-100000}"
readonly memory_soft_limit="${SHINKA_MEMORY_SOFT_LIMIT:-30064771072}"
readonly frontier_check_interval="${SHINKA_FRONTIER_CHECK_INTERVAL:-900}"
readonly research_seed_source=/workspace/deploy/render/shinka-flock/research-seed.md
readonly research_logbook_dir="$data_dir/shinka/logbook"
readonly research_seed_path="$research_logbook_dir/research-seed.md"
readonly seed_submission="${SHINKA_SEED_SUBMISSION:-25ec5a6e-7c56-4f1d-bd14-522681f952be}"
readonly seed_source_commit="${SHINKA_SEED_SOURCE_COMMIT:-ae4c22df596fb7ca642766b362cb7b1e38a6fdb4}"
readonly seed_base_commit="${SHINKA_SEED_BASE_COMMIT:-207fc36d9eb365bff6ecc0f1959962a812df55cf}"
readonly seed_root="$data_dir/shinka/seeds/$seed_submission"
readonly seed_patch="$seed_root/seed.patch"
readonly seed_target_source="$seed_root/target.rs"
readonly seed_changed_paths="$seed_root/changed-paths.txt"
readonly seed_receipt="$seed_root/receipt.txt"

mkdir -p \
  "$state_dir" \
  "$data_dir/logs" \
  "$workspace_parent" \
  "$data_dir/shinka" \
  "$research_logbook_dir"
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
echo v2 > "$state_dir/shinka-supervisor-version"
rm -f "$state_dir/shinka-bootstrap-last-error"

test -s "$research_seed_source"
cp "$research_seed_source" "$research_seed_path"
sha256sum "$research_seed_path" | awk '{print $1}' \
  > "$state_dir/shinka-research-seed.sha256"
printf '%s source=Amal-David/evo seed=%s\n' \
  "$(date -u +%FT%TZ)" "$(cat "$state_dir/shinka-research-seed.sha256")" \
  > "$state_dir/shinka-research-seed-receipt"

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
echo landlock-seccomp-v1 > "$state_dir/shinka-sandbox-version"
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

if ! [[ "$seed_submission" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]]; then
  log "Configured seed submission is not a full Yukon UUID"
  false
fi
if ! [[ "$seed_source_commit" =~ ^[0-9a-f]{40}$ ]] || \
   ! [[ "$seed_base_commit" =~ ^[0-9a-f]{40}$ ]]; then
  log "Configured seed source or base commit is malformed"
  false
fi

if [ ! -s "$seed_patch" ] || [ ! -s "$seed_target_source" ] || \
   [ ! -s "$seed_changed_paths" ] || [ ! -s "$seed_receipt" ]; then
  log "Recovering official near-miss $seed_submission in an isolated Yukon clone"
  seed_stage=$(mktemp -d "$data_dir/shinka/seed-recovery.XXXXXX")
  yukon clone "$benchmark_name" "$seed_stage/repo"
  cd "$seed_stage/repo"
  yukon reset "$seed_submission" 2>&1 | tee "$seed_stage/reset.log"
  test "$(git rev-parse HEAD)" = "$seed_base_commit"
  # Yukon decorates field labels with ANSI color codes even when piped. Match
  # the full source commit itself; the reset receipt contains it only in the
  # `from` field, while HEAD independently verifies the submission base.
  grep -Fq "$seed_source_commit" "$seed_stage/reset.log"
  git -c core.whitespace=cr-at-eol diff --cached --check
  git diff --cached --name-only > "$seed_stage/changed-paths.txt"
  test -s "$seed_stage/changed-paths.txt"
  grep -Fxq "$target_path" "$seed_stage/changed-paths.txt"
  while IFS= read -r changed_path; do
    jq -e \
      --arg changed "$changed_path" \
      '.schemaVersion == 2 and any(.tracks[]; .name == "x86" and any(.editablePaths[]; . as $editable | $changed == $editable or ($changed | startswith($editable + "/"))))' \
      benchmark.json >/dev/null
  done < "$seed_stage/changed-paths.txt"
  mkdir -p "$seed_root"
  git diff --cached --binary > "$seed_root/seed.patch.tmp"
  git show ":$target_path" > "$seed_root/target.rs.tmp"
  cp "$seed_stage/changed-paths.txt" "$seed_root/changed-paths.txt.tmp"
  patch_sha=$(sha256sum "$seed_root/seed.patch.tmp" | awk '{print $1}')
  printf '%s submission=%s source=%s base=%s patch_sha256=%s\n' \
    "$(date -u +%FT%TZ)" "$seed_submission" "$seed_source_commit" \
    "$seed_base_commit" "$patch_sha" > "$seed_root/receipt.txt.tmp"
  mv "$seed_root/seed.patch.tmp" "$seed_patch"
  mv "$seed_root/target.rs.tmp" "$seed_target_source"
  mv "$seed_root/changed-paths.txt.tmp" "$seed_changed_paths"
  mv "$seed_root/receipt.txt.tmp" "$seed_receipt"
  cd "$benchmark_dir"
  rm -rf "$seed_stage"
fi

grep -Fq "submission=$seed_submission" "$seed_receipt"
grep -Fq "source=$seed_source_commit" "$seed_receipt"
grep -Fq "base=$seed_base_commit" "$seed_receipt"
recorded_seed_sha=$(sed -n 's/.* patch_sha256=\([0-9a-f]\{64\}\).*/\1/p' "$seed_receipt")
test -n "$recorded_seed_sha"
test "$(sha256sum "$seed_patch" | awk '{print $1}')" = "$recorded_seed_sha"
test "$(wc -c < "$seed_target_source")" -le "$max_target_bytes"

log "Checking that the near-miss patch applies cleanly to the promoted frontier"
seed_preflight_parent=$(mktemp -d "$data_dir/shinka/seed-preflight.XXXXXX")
seed_preflight="$seed_preflight_parent/worktree"
git worktree add --quiet --detach "$seed_preflight" "$base_commit"
if ! git -C "$seed_preflight" apply --index --3way "$seed_patch"; then
  git worktree remove --force "$seed_preflight" || true
  rmdir "$seed_preflight_parent" || true
  log "Near-miss seed no longer applies cleanly to the promoted frontier"
  false
fi
git -C "$seed_preflight" -c core.whitespace=cr-at-eol diff --cached --check
git worktree remove --force "$seed_preflight"
rmdir "$seed_preflight_parent"
printf '%s submission=%s source=%s source_base=%s promoted=%s patch_sha256=%s\n' \
  "$(date -u +%FT%TZ)" "$seed_submission" "$seed_source_commit" \
  "$seed_base_commit" "$base_commit" "$recorded_seed_sha" \
  > "$state_dir/shinka-near-miss-seed-ready"

log "Running Yukon setup for the promoted Flock frontier"
FLOCK_REQUIRE_SANDBOX=1 yukon setup --track x86 \
  2>&1 | tee "$state_dir/shinka-setup.log"
yukon submissions "$benchmark_name" --all \
  > "$state_dir/shinka-submissions.txt"
date -u +%FT%TZ > "$state_dir/shinka-submissions-refreshed-at"

target_id=$(printf '%s' "$target_path" | sha256sum | awk '{print substr($1,1,16)}')
seed_lineage="${seed_submission:0:8}-${recorded_seed_sha:0:12}"
task_dir="$data_dir/shinka/tasks/$target_id"
results_dir="$data_dir/shinka/results/$base_commit/$target_id/$seed_lineage/landlock-seccomp-v1"
mkdir -p "$task_dir" "$results_dir"
cp /workspace/deploy/render/shinka-flock/evaluate.py "$task_dir/evaluate.py"
cp /workspace/deploy/render/shinka-flock/run_evo.py "$task_dir/run_evo.py"
cp /workspace/deploy/render/shinka-flock/research_context.py \
  "$task_dir/research_context.py"
{
  echo '// EVOLVE-BLOCK-START'
  cat "$seed_target_source"
  echo '// EVOLVE-BLOCK-END'
} > "$task_dir/initial.rs"
{
  echo '// EVOLVE-BLOCK-START'
  git show "$base_commit:$target_path"
  echo '// EVOLVE-BLOCK-END'
} > "$task_dir/baseline.rs"
printf '%s base=%s target=%s model=%s variant=%s seed_submission=%s seed_source=%s seed_lineage=%s\n' \
  "$(date -u +%FT%TZ)" "$base_commit" "$target_path" "$model" "$variant" \
  "$seed_submission" "$seed_source_commit" "$seed_lineage" \
  > "$state_dir/shinka-campaign"

log "Capturing a fail-closed trusted baseline before evolutionary search"
baseline_receipt_dir="$results_dir/baseline-preflight"
mkdir -p "$baseline_receipt_dir"
setsid env \
  SHINKA_BENCHMARK_DIR="$benchmark_dir" \
  SHINKA_BASE_COMMIT="$base_commit" \
  SHINKA_TARGET_PATH="$target_path" \
  SHINKA_RESULTS_DIR="$results_dir" \
  SHINKA_STATE_DIR="$state_dir" \
  SHINKA_RESEARCH_SEED_PATH="$research_seed_path" \
  SHINKA_SEED_PATCH="$seed_patch" \
  SHINKA_SEED_TARGET_SOURCE="$seed_target_source" \
  SHINKA_SEED_SUBMISSION="$seed_submission" \
  python3 "$task_dir/evaluate.py" \
    --program_path "$task_dir/baseline.rs" \
    --results_dir "$baseline_receipt_dir" &
baseline_pid=$!
while kill -0 "$baseline_pid" 2>/dev/null; do
  memory_current=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
  printf '%s memory_current=%s child=%s phase=baseline-preflight\n' \
    "$(date -u +%FT%TZ)" "$memory_current" "$baseline_pid" \
    > "$state_dir/shinka-supervisor-heartbeat"
  if [ "$memory_current" -ge "$memory_soft_limit" ]; then
    log "Memory reached the configured ceiling during baseline preflight"
    kill -TERM -- "-$baseline_pid" 2>/dev/null || true
    wait "$baseline_pid" || true
    false
  fi
  sleep 10
done
wait "$baseline_pid"
jq -e '.correct == true and (.error | length == 0)' \
  "$baseline_receipt_dir/correct.json" >/dev/null
baseline_score=$(jq -er \
  '.combined_score | select(type == "number" and . > 0)' \
  "$baseline_receipt_dir/metrics.json")
printf '%s base=%s score=%s sandbox=landlock-seccomp-v1\n' \
  "$(date -u +%FT%TZ)" "$base_commit" "$baseline_score" \
  > "$state_dir/shinka-baseline-ready"
log "Trusted baseline ready at score $baseline_score"

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
    SHINKA_RESEARCH_SEED_PATH="$research_seed_path" \
    SHINKA_SEED_PATCH="$seed_patch" \
    SHINKA_SEED_TARGET_SOURCE="$seed_target_source" \
    SHINKA_SEED_SUBMISSION="$seed_submission" \
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
