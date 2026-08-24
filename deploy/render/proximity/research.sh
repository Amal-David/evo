#!/usr/bin/env bash
set -Eeuo pipefail

readonly data_dir=/data
readonly state_dir="$data_dir/state"
readonly log_file="$data_dir/logs/evo-autonomous.log"
readonly complete_marker="$state_dir/evo-research-complete-v5"
readonly model=opencode/x-preview-f-free
readonly variant=max
readonly subagents=1
readonly budget=12
readonly stall=30
readonly memory_soft_limit=12884901888
readonly evo_commit=333e97c1175ce047d4ba2634e396449682b09a4a
readonly evo_source="$data_dir/runtime/evo-$evo_commit"

mkdir -p "$state_dir" "$data_dir/logs" "$data_dir/runtime"
if [ -f "$log_file" ] && [ "$(stat -c %s "$log_file" 2>/dev/null || echo 0)" -gt 104857600 ]; then
  tail -c 52428800 "$log_file" > "$log_file.trimmed"
  mv "$log_file.trimmed" "$log_file"
fi
exec > >(tee -a "$log_file") 2>&1

log() {
  echo "[$(date -u +%FT%TZ)] $*"
}

exec 9>"$state_dir/evo-research.lock"
if ! flock -n 9; then
  log "Another Evo supervisor owns the lock"
  exit 75
fi

cleanup() {
  rm -f "$state_dir/evo-research.pid" "$state_dir/opencode-child.pid"
}
trap cleanup EXIT
echo "$$" > "$state_dir/evo-research.pid"
echo v5 > "$state_dir/evo-supervisor-version"

if [ ! -d "$evo_source/.git" ]; then
  git clone --filter=blob:none https://github.com/Amal-David/evo.git "$evo_source"
fi
if [ "$(git -C "$evo_source" rev-parse HEAD)" != "$evo_commit" ]; then
  git -C "$evo_source" fetch --depth 1 origin "$evo_commit"
  git -C "$evo_source" checkout --detach "$evo_commit"
fi
test "$(git -C "$evo_source" rev-parse HEAD)" = "$evo_commit"
uv tool install --force --editable "$evo_source/plugins/evo"
evo install opencode --from-path "$evo_source" --force
yukon install-skill --target all
evo telemetry off
evo doctor opencode
evo opencode-run --help | grep -Fq -- "--subagents"
for required_skill in discover optimize subagent; do
  test -f "$HOME/.agents/skills/$required_skill/SKILL.md"
done
test -f "$HOME/.agents/skills/yukon-cli/SKILL.md"
printf '%s\n' "$evo_commit" > "$state_dir/evo-fork-commit"
printf '%s fork_commit=%s model=%s variant=%s\n' \
  "$(date -u +%FT%TZ)" "$evo_commit" "$model" "$variant" \
  > "$state_dir/evo-harness-ready"

if [ -f .evo/project.md ]; then
  evo host set opencode
fi

goal=$(cat <<'EOF'
Run a fully unattended Evo HQ frontier-research campaign on this checked-out Yukon Proximity Prize challenge. Objective: produce and officially promote a strictly higher proved centibit score for irs-reduction-threshold-lower while preserving the exact theorem contract and challenge isolation. Continue across stalls and failed approaches until an accepted promoted Yukon receipt establishes a new winning frontier; a plateau is a research signal, not completion.

This problem is at the edge of the existing proof route, so question foundational assumptions rather than only sweeping constants. Use Evo's native OpenCode task-tool orchestration, never an ad-hoc shell swarm. Candidate proof work is serialized because this 4-CPU, 16-GB container and Lean build are memory-bound. In parallel research phases, use Evo's independent failure-analysis, literature, and frontier-extrapolation ideators, and use its mandatory pre/post verifier roles around every experiment. Assign genuinely distinct briefs: audit the theorem and imported definitions from first principles; search for sharper analytic/combinatorial reductions and certificate representations; attempt counterexample-directed checks of hidden monotonicity or rounding assumptions; and independently criticize every proposed lemma. Keep factual hypotheses, sources, rejected assumptions, proof failures, experiment receipts, and next questions in Evo scratchpad entries, annotations, outcomes, and ideator proposals so restarts inherit a real logbook.

The benchmark command and safety gate must be /data/state/run-local-gate.sh; its score field is the local maximization metric. Never run benchmark.sh here because the full Comparator previously caused status 137. Never call yukon run here because Render lacks systemd-run, so local results are not official benchmark receipts. Read benchmark.json, README.md, AGENTS.md, the installed Yukon skill, and Evo's current phase skill before acting. Change candidates only through Evo experiments and only under ProximityPrize/SubmissionLower. The submission root must remain flat. Never import ProximityPrize, TargetUpper, SubmissionUpper, or any upper-track module. Do not weaken or bypass the local contract gate.

You are authorized to submit a candidate to Yukon without waiting for human review only when a deterministic proof-promotion gate passes. Re-verify repository identity, the selected irs-reduction-threshold-lower track, editable paths, and the current promoted frontier. Require the exact target theorem to compile from a clean candidate worktree; the lower-only import checker, flat-layout checker, axiom/sorry policy, claim/score consistency checks, and /data/state/run-local-gate.sh must all pass; the proved integer score must be strictly higher than the latest promoted score; and an independent verifier subagent must reproduce those facts without relying on the proposing agent's summary. Reject duplicate or previously disproved mechanisms. Prepare a reviewed, secret-free 5-100 KiB Markdown note that records the theorem route, exact files, verification evidence, failures, caveats, and the exact model attribution OpenCode Zen Ox Alpha Free for opencode/x-preview-f-free, variant max. Submit at most once per independently verified candidate with yukon submit --track irs-reduction-threshold-lower, wait for the terminal receipt, and record the submission ID and result in the local Evo logbook. Only an accepted promoted receipt is a win. A rejection becomes evidence for a materially new research branch; never resubmit the same candidate. Do not publish standalone notes, push, open pull requests, or expose credentials.
EOF
)

restart_count=0
if [ -s "$state_dir/evo-research-restarts" ]; then
  restart_count=$(tr -cd '0-9' < "$state_dir/evo-research-restarts")
fi

while [ ! -f "$complete_marker" ]; do
  if [ -f .evo/project.md ]; then
    phase=optimize
  else
    phase=discover
  fi

  restart_count=$((restart_count + 1))
  printf '%s\n' "$restart_count" > "$state_dir/evo-research-restarts"
  log "Launching Evo $phase attempt $restart_count with $model variant $variant"

  shape_args=()
  if [ "$phase" = optimize ]; then
    shape_args=(--subagents "$subagents" --budget "$budget" --stall "$stall")
  fi
  setsid evo opencode-run "$phase" --goal "$goal" \
    --model "$model" --variant "$variant" "${shape_args[@]}" &
  child_pid=$!
  echo "$child_pid" > "$state_dir/opencode-child.pid"
  pressure_stopped=0

  while kill -0 "$child_pid" 2>/dev/null; do
    now=$(date -u +%FT%TZ)
    memory_current=$(cat /sys/fs/cgroup/memory.current 2>/dev/null || echo 0)
    printf '%s memory_current=%s attempt=%s child=%s phase=%s\n' \
      "$now" "$memory_current" "$restart_count" "$child_pid" "$phase" \
      > "$state_dir/evo-supervisor-heartbeat"
    if [ "$memory_current" -ge "$memory_soft_limit" ]; then
      pressure_stopped=1
      log "Memory reached 12 GiB; stopping this attempt before Render kills the container"
      kill -TERM -- "-$child_pid" 2>/dev/null || true
      sleep 10
      kill -KILL -- "-$child_pid" 2>/dev/null || true
      break
    fi
    sleep 5
  done

  if wait "$child_pid"; then
    status=0
  else
    status=$?
  fi
  rm -f "$state_dir/opencode-child.pid"
  printf '%s\n' "$status" > "$state_dir/evo-research-last-exit"

  if [ "$phase" = discover ] && [ -f .evo/project.md ]; then
    evo host set opencode
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
    > "$state_dir/evo-research-last-restart"
  log "OpenCode/Evo stopped with status $status; resuming research in $delay seconds"
  sleep "$delay"
done

log "Evo supervisor reached explicit v5 completion state"
exec sleep infinity
