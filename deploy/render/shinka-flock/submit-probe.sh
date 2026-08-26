#!/usr/bin/env bash
set -Eeuo pipefail

readonly state_dir=/data/state
readonly log_dir=/data/logs
readonly benchmark_name=eigenlabs/flock-challenge-multi/x86
readonly frontier_branch=main
readonly track=x86
readonly model='OpenCode Zen Ox Alpha Free'
readonly daily_limit="${SHINKA_SUBMISSION_DAILY_LIMIT:-15}"
readonly cooldown_seconds="${SHINKA_SUBMISSION_COOLDOWN_SECONDS:-1200}"
readonly ledger="$state_dir/shinka-submission-ledger.tsv"
readonly lock_file="$state_dir/shinka-submission.lock"
readonly last_submit_file="$state_dir/shinka-submission-last-at"

usage() {
  echo "Usage: shinka-flock-submit-probe [--check] <submission-note.md>" >&2
}

fail() {
  echo "Shinka submission probe blocked: $*" >&2
  exit 1
}

mode=submit
if [ "${1:-}" = --check ]; then
  mode=check
  shift
fi
if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

note_file=$1
test -f "$note_file" || fail "note file does not exist"
note_file=$(realpath "$note_file")
note_bytes=$(wc -c < "$note_file" | tr -d '[:space:]')
if [ "$note_bytes" -lt 5120 ] || [ "$note_bytes" -gt 102400 ]; then
  fail "public note must be between 5 KiB and 100 KiB"
fi
if grep -Eiq \
    '(ykn_[[:alnum:]]{20,}|github_pat_[[:alnum:]_]{20,}|gh[pousr]_[[:alnum:]]{20,}|sk-[[:alnum:]_-]{20,})' \
    "$note_file"; then
  fail "public note contains a credential-like value"
fi
while IFS='=' read -r key value; do
  case "$key" in
    *TOKEN*|*KEY*|*SECRET*|*PASSWORD*|*CREDENTIAL*)
      if [ "${#value}" -ge 8 ] && grep -Fq -- "$value" "$note_file"; then
        fail "public note contains a secret-like environment value"
      fi
      ;;
  esac
done < <(env)

repo=$(git rev-parse --show-toplevel 2>/dev/null) || fail "run inside a Git worktree"
cd "$repo"
git remote get-url origin | grep -Eq \
  'Layr-Labs/flock-challenge-multi|eigenlabs/flock-challenge-multi' || \
  fail "repository identity does not match the Flock challenge"
jq -e --arg track "$track" \
  '.schemaVersion == 2 and any(.tracks[]; .name == $track)' \
  benchmark.json >/dev/null || fail "benchmark schema or x86 track is missing"

mapfile -t editable_paths < <(
  jq -r --arg track "$track" \
    '.tracks[] | select(.name == $track) | .editablePaths[]' benchmark.json
)
test "${#editable_paths[@]}" -gt 0 || fail "x86 editable paths are empty"
git diff --quiet || fail "candidate worktree has uncommitted changes"
git diff --cached --quiet || fail "candidate index has uncommitted changes"

frontier_record=$(cat "$state_dir/shinka-frontier-current" 2>/dev/null || true)
base=$(printf '%s\n' "$frontier_record" | \
  sed -n 's/.* promoted=\([0-9a-f]\{40\}\).*/\1/p')
test -n "$base" || fail "promoted frontier receipt is missing"
git merge-base --is-ancestor "$base" HEAD || \
  fail "candidate is not based on the recorded frontier"

remote_frontier=$(git ls-remote origin "refs/heads/$frontier_branch" | \
  awk 'NR == 1 { print $1 }')
if [ -z "$remote_frontier" ] || [ "$remote_frontier" != "$base" ]; then
  fail "promoted frontier moved; refresh before submitting"
fi

mapfile -t changed_paths < <(git diff --name-only "$base" HEAD)
test "${#changed_paths[@]}" -gt 0 || fail "candidate has no changes"
for changed in "${changed_paths[@]}"; do
  allowed=0
  for editable in "${editable_paths[@]}"; do
    if [ "$changed" = "$editable" ] || [[ "$changed" = "$editable/"* ]]; then
      allowed=1
      break
    fi
  done
  [ "$allowed" -eq 1 ] || fail "candidate changes a non-editable path: $changed"
done

fingerprint=$(git diff --binary "$base" HEAD -- "${editable_paths[@]}" | \
  sha256sum | awk '{ print $1 }')
head_commit=$(git rev-parse HEAD)
today=$(date -u +%F)
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$state_dir" "$log_dir"
exec 9>"$lock_file"
flock 9

if [ -f "$ledger" ] && awk -F '\t' -v fingerprint="$fingerprint" \
    '$3 == fingerprint && $6 == "reserved" { found=1 } END { exit !found }' \
    "$ledger"; then
  fail "this exact editable-path diff already used an official probe"
fi
used_today=0
if [ -f "$ledger" ]; then
  used_today=$(awk -F '\t' -v today="$today" \
    '$1 == today && $6 == "reserved" { count++ } END { print count+0 }' "$ledger")
fi
remaining=$((daily_limit - used_today))
[ "$remaining" -gt 0 ] || fail "daily official-probe quota is exhausted"

now_epoch=$(date +%s)
last_epoch=0
if [ -s "$last_submit_file" ]; then
  last_epoch=$(tr -cd '0-9' < "$last_submit_file")
fi
next_epoch=$((last_epoch + cooldown_seconds))
if [ "$mode" = submit ] && [ "$now_epoch" -lt "$next_epoch" ]; then
  fail "official-probe cooldown is active"
fi

if [ "$mode" = check ]; then
  printf 'eligible fingerprint=%s remaining_today=%s\n' "$fingerprint" "$remaining"
  exit 0
fi

receipt="$log_dir/shinka-submission-${timestamp}-${fingerprint:0:12}.log"
printf '%s\t%s\t%s\t%s\t%s\treserved\t%s\n' \
  "$today" "$timestamp" "$fingerprint" "$base" "$head_commit" "$receipt" \
  >> "$ledger"
printf '%s\n' "$now_epoch" > "$last_submit_file"
flock -u 9

set +e
yukon submit "$benchmark_name" --track "$track" \
  --note-file "$note_file" --model "$model" 2>&1 | tee "$receipt"
status=${PIPESTATUS[0]}
set -e

exec 9>"$lock_file"
flock 9
printf '%s\t%s\t%s\t%s\t%s\texit_%s\t%s\n' \
  "$today" "$(date -u +%Y%m%dT%H%M%SZ)" "$fingerprint" "$base" \
  "$head_commit" "$status" "$receipt" >> "$ledger"
flock -u 9
exit "$status"
