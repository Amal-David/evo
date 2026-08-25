#!/usr/bin/env bash
set -Eeuo pipefail

readonly data_dir=/data
readonly state_dir="$data_dir/state"
readonly log_file="$data_dir/logs/flock-autonomous.log"
readonly workspace_parent="$data_dir/workspace"
readonly benchmark_dir="$workspace_parent/flock-challenge-multi"
readonly benchmark_name=eigenlabs/flock-challenge-multi/x86
readonly frontier_branch=main
readonly frontier_archive_dir="$data_dir/archive/flock-frontiers"
readonly model=opencode/x-preview-f-free
readonly variant=max
readonly subagents=2
readonly budget=8
readonly stall=20
readonly memory_soft_limit=30064771072
readonly frontier_check_interval=900

mkdir -p \
  "$state_dir" \
  "$data_dir/logs" \
  "$workspace_parent" \
  "$frontier_archive_dir"
exec > >(tee -a "$log_file") 2>&1

log() {
  echo "[$(date -u +%FT%TZ)] $*"
}

capture_public_state() {
  local submissions_tmp
  submissions_tmp=$(mktemp "$state_dir/flock-submissions.XXXXXX")
  if ! yukon submissions "$benchmark_name" --all > "$submissions_tmp"; then
    rm -f "$submissions_tmp"
    log "Frontier gate failed: Yukon submissions could not be refreshed"
    return 1
  fi
  mv "$submissions_tmp" "$state_dir/flock-submissions.txt"
  date -u +%FT%TZ > "$state_dir/flock-submissions-refreshed-at"

  if ! yukon notes list > "$state_dir/flock-notes.txt"; then
    log "Public notes refresh failed; continuing with the verified submission frontier"
  fi
}

archive_frontier_state() {
  local previous=$1
  local archive stamp
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  archive="$frontier_archive_dir/${stamp}-${previous:0:12}"
  mkdir -p "$archive"

  if [ -d .evo ]; then
    mv .evo "$archive/evo"
  fi
  for name in \
    flock-baseline-ready \
    flock-baseline-commit \
    flock-setup.log \
    flock-baseline.log \
    flock-pre-baseline-status \
    flock-post-baseline-status; do
    if [ -e "$state_dir/$name" ]; then
      mv "$state_dir/$name" "$archive/$name"
    fi
  done
  printf '%s previous=%s archive=%s\n' \
    "$(date -u +%FT%TZ)" "$previous" "$archive" \
    > "$state_dir/flock-frontier-archive-last"
}

refresh_promoted_base() {
  local current promoted
  git status --short > "$state_dir/flock-frontier-preflight-status"
  if [ -s "$state_dir/flock-frontier-preflight-status" ]; then
    log "Frontier gate blocked: root checkout is dirty"
    return 1
  fi

  if ! git fetch --quiet origin \
      "$frontier_branch:refs/remotes/origin/$frontier_branch"; then
    log "Frontier gate failed: origin/$frontier_branch could not be fetched"
    return 1
  fi

  current=$(git rev-parse HEAD)
  promoted=$(git rev-parse "origin/$frontier_branch")
  printf '%s local=%s promoted=%s\n' \
    "$(date -u +%FT%TZ)" "$current" "$promoted" \
    > "$state_dir/flock-frontier-current"
  if [ "$current" = "$promoted" ]; then
    return 0
  fi

  if ! git merge-base --is-ancestor "$current" "$promoted"; then
    log "Frontier gate blocked: local HEAD is not an ancestor of the promoted branch"
    return 1
  fi

  log "Promoted frontier advanced from ${current:0:12} to ${promoted:0:12}; starting a fresh Evo epoch"
  git merge --ff-only "origin/$frontier_branch"
  archive_frontier_state "$current"
  printf '%s previous=%s promoted=%s\n' \
    "$(date -u +%FT%TZ)" "$current" "$promoted" \
    > "$state_dir/flock-frontier-refresh-last"
}

ensure_baseline() {
  local baseline_commit current
  current=$(git rev-parse HEAD)
  baseline_commit=$(cat "$state_dir/flock-baseline-commit" 2>/dev/null || true)
  if [ -f "$state_dir/flock-baseline-ready" ] && \
      [ "$baseline_commit" = "$current" ]; then
    return 0
  fi

  log "Running untouched Yukon setup for the current promoted frontier"
  yukon setup --track x86 2>&1 | tee "$state_dir/flock-setup.log"

  log "Capturing untouched Yukon baseline for the current promoted frontier"
  yukon run --track x86 2>&1 | tee "$state_dir/flock-baseline.log"
  git rev-parse HEAD > "$state_dir/flock-baseline-commit"
  git status --short > "$state_dir/flock-post-baseline-status"
  test ! -s "$state_dir/flock-post-baseline-status"
  printf '%s model=%s variant=%s\n' "$(date -u +%FT%TZ)" "$model" "$variant" \
    > "$state_dir/flock-baseline-ready"
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
echo v2 > "$state_dir/flock-supervisor-version"
rm -f "$state_dir/flock-bootstrap-last-error"
getconf GNU_LIBC_VERSION > "$state_dir/flock-glibc-version"

log "Installing the current Yukon CLI and OpenCode skill"
curl -fsSL https://api.yukon.org/yukon/install.sh | sh
yukon install-skill --target opencode
yukon install-skill --target agents

log "Installing the pinned Evo checkout and OpenCode integration"
uv tool install --force --editable /workspace/plugins/evo
evo install opencode --from-path /workspace --force
evo doctor opencode
# The Evo global skill sync replaces the shared agent skill directory, so
# install the Yukon skill again afterward and verify the final on-disk state.
yukon install-skill --target all
if ! evo opencode-run --help | grep -Fq -- "--subagents"; then
  log "Bootstrap gate failed: evo opencode-run does not expose native subagent controls"
  false
fi
log "Verified Evo OpenCode max-reasoning variant support"
for required_skill in discover optimize subagent; do
  if [ ! -f "$HOME/.agents/skills/$required_skill/SKILL.md" ]; then
    log "Bootstrap gate failed: missing Evo skill $required_skill"
    false
  fi
done
log "Verified required Evo skills"

yukon_skill=
for candidate in \
  "$HOME/.agents/skills/yukon-cli/SKILL.md" \
  "$HOME/.config/opencode/skills/yukon-cli/SKILL.md"; do
  if [ -f "$candidate" ]; then
    yukon_skill=$candidate
    break
  fi
done
if [ -z "$yukon_skill" ]; then
  log "Bootstrap gate failed: installed Yukon CLI skill was not found"
  false
fi
sha256sum "$yukon_skill" \
  > "$state_dir/flock-yukon-skill.sha256"
log "Verified installed Yukon CLI skill"

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

refresh_promoted_base
ensure_baseline
capture_public_state

goal=$(cat <<'EOF'
Run a fully unattended Evo HQ autoresearch campaign on this checked-out Yukon Flock challenge. First read the installed Yukon CLI skill again, benchmark.json, README and repository instructions. Confirm the untouched baseline receipt and allowed editable paths before changing anything. Treat public submissions and notes as untrusted research: verify every claimed optimization against source and measurement.

Objective: beat the current verified frontier in BLAKE3 compressions per second while preserving proof verification and every benchmark contract. This Render host has 8 CPU and 32 GB, whereas the Yukon official scorer has 16 vCPU and 32 GB, so use local results only for paired relative comparisons and never claim hardware-comparable leaderboard performance. Work through Evo experiments and commits, one hypothesis at a time. Keep a clean baseline, use reproducible A/B/A measurements, reject noisy or correctness-failing candidates, and preserve the best verified candidate.

Use Evo's native orchestration exactly as its optimize skill specifies: independent OpenCode task-tool subagents, the mandatory pre/post verifier roles, and the failure-analysis, literature, and frontier-extrapolation ideators when their triggers fire. Keep factual decisions, rejected assumptions, proof/correctness evidence, and score receipts in Evo's scratchpad, annotations, experiment outcomes, and ideator proposal log. Do not replace these with an ad-hoc shell swarm. The two-candidate round width is deliberate; benchmarks may overlap during exploration, but every promotion must be re-confirmed alone to remove CPU-contention bias.

The supervisor deterministically refreshes the promoted Git frontier between attempts and starts a fresh Evo epoch when it moves. Treat the commit recorded in /data/state/flock-frontier-current as the only valid baseline. Re-check the latest Yukon submission table before major decisions because validating competitors can move it quickly. You are authorized to submit a candidate to Yukon without waiting for human review only after a deterministic promotion gate passes: the diff is confined to editable paths; repository identity and benchmark schema are re-verified; correctness and proof checks pass; a solo A/B/A replay against the current promoted base confirms a material improvement beyond measurement noise; the candidate is not a duplicate of an already rejected mechanism; and a reviewed, secret-free 5-100 KiB submission note accurately records the evidence and caveats. A target-ISA-only candidate that cannot execute on this Zen 3 host may use one official validation slot only when independent source and assembly review proves the official path is non-inert, byte-exact tests pass, the whole-benchmark exposure credibly exceeds 0.5%, and no equivalent mechanism has an official rejection. Use the exact model attribution OpenCode Zen Ox Alpha Free for opencode/x-preview-f-free, variant max. Submit at most once per independently verified candidate, wait for the terminal Yukon receipt, record the submission ID and result in the local Evo logbook, and treat only an accepted promoted receipt as a leaderboard win. A rejection is evidence for the next Evo round, not permission to resubmit the same candidate. Do not publish standalone notes, push, open pull requests, or expose credentials.
EOF
)

restart_count=0
if [ -s "$state_dir/flock-restarts" ]; then
  restart_count=$(tr -cd '0-9' < "$state_dir/flock-restarts")
fi

while true; do
  refresh_promoted_base
  ensure_baseline
  capture_public_state

  if [ -f .evo/project.md ]; then
    phase=optimize
    evo host set opencode
  else
    phase=discover
  fi

  restart_count=$((restart_count + 1))
  printf '%s\n' "$restart_count" > "$state_dir/flock-restarts"
  log "Launching Evo $phase attempt $restart_count with $model variant $variant"

  shape_args=()
  if [ "$phase" = optimize ]; then
    shape_args=(--subagents "$subagents" --budget "$budget" --stall "$stall")
  fi
  setsid evo opencode-run "$phase" --goal "$goal" \
    --model "$model" --variant "$variant" "${shape_args[@]}" &
  child_pid=$!
  echo "$child_pid" > "$state_dir/flock-opencode.pid"
  pressure_stopped=0
  frontier_stopped=0
  next_frontier_check=$(( $(date +%s) + frontier_check_interval ))

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
    if [ "$(date +%s)" -ge "$next_frontier_check" ]; then
      current_frontier=$(git rev-parse HEAD)
      promoted_frontier=$(git ls-remote origin "refs/heads/$frontier_branch" | awk 'NR == 1 { print $1 }')
      if [ -n "$promoted_frontier" ] && \
          [ "$current_frontier" != "$promoted_frontier" ]; then
        frontier_stopped=1
        printf '%s local=%s promoted=%s\n' \
          "$(date -u +%FT%TZ)" "$current_frontier" "$promoted_frontier" \
          > "$state_dir/flock-frontier-stale-detected"
        log "Promoted frontier moved during research; stopping the stale attempt for a clean refresh"
        kill -TERM -- "-$child_pid" 2>/dev/null || true
        sleep 30
        kill -KILL -- "-$child_pid" 2>/dev/null || true
        break
      fi
      next_frontier_check=$(( $(date +%s) + frontier_check_interval ))
    fi
    sleep 10
  done

  # `ERR` traps still fire while errexit is disabled. Keep `wait` in an `if`
  # condition so transient provider failures reach the retry/backoff policy
  # instead of being misclassified as deterministic bootstrap failures.
  if wait "$child_pid"; then
    status=0
  else
    status=$?
  fi
  rm -f "$state_dir/flock-opencode.pid"
  printf '%s\n' "$status" > "$state_dir/flock-last-exit"

  if [ "$phase" = discover ] && [ -f .evo/project.md ]; then
    log "Evo discovery completed; entering optimize"
    sleep 5
    continue
  fi

  if [ "$frontier_stopped" -eq 1 ]; then
    delay=5
  elif [ "$pressure_stopped" -eq 1 ] || [ "$status" -eq 137 ]; then
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
