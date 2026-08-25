#!/usr/bin/env bash
set -Eeuo pipefail

readonly state_dir=/data/state
readonly log_dir=/data/logs
readonly frontier_branch=main
readonly track=x86
readonly model='OpenCode Zen Ox Alpha Free'
readonly daily_limit=15
readonly max_inflight=3
readonly ledger="$state_dir/flock-submission-ledger.tsv"
readonly lock_file="$state_dir/flock-submission.lock"
readonly active_dir="$state_dir/flock-submission-active"

usage() {
  echo "Usage: flock-submit-probe [--check] <submission-note.md>" >&2
}

fail() {
  echo "Submission probe blocked: $*" >&2
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

# Check both recognizable credential formats and every secret-like value in
# the current environment without ever printing the matching value.
if grep -Eiq \
    '(ykn_[[:alnum:]]{20,}|github_pat_[[:alnum:]_]{20,}|gh[pousr]_[[:alnum:]]{20,}|sk-[[:alnum:]_-]{20,})' \
    "$note_file"; then
  fail "public note contains a credential-like value"
fi
while IFS='=' read -r key value; do
  case "$key" in
    *TOKEN*|*KEY*|*SECRET*|*PASSWORD*|*CREDENTIAL*)
      if [ "${#value}" -ge 8 ] && grep -Fq -- "$value" "$note_file"; then
        fail "public note contains a value from a secret-like environment variable"
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
if [ "${#editable_paths[@]}" -eq 0 ]; then
  fail "x86 editable paths are empty"
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  fail "tracked candidate changes must be committed before an official probe"
fi
if [ -n "$(git ls-files --others --exclude-standard -- "${editable_paths[@]}")" ]; then
  fail "editable paths contain untracked files that are not part of the committed candidate"
fi

frontier_record=$(cat "$state_dir/flock-frontier-current" 2>/dev/null || true)
base=$(printf '%s\n' "$frontier_record" | \
  sed -n 's/.* promoted=\([0-9a-f]\{40\}\).*/\1/p')
if [ -z "$base" ]; then
  fail "current promoted frontier receipt is missing"
fi
git cat-file -e "$base^{commit}" 2>/dev/null || fail "promoted frontier commit is unavailable"
git merge-base --is-ancestor "$base" HEAD || fail "candidate is not based on the current frontier"

if ! remote_frontier=$(git ls-remote origin "refs/heads/$frontier_branch" | \
    awk 'NR == 1 { print $1 }'); then
  fail "could not refresh the promoted frontier"
fi
if [ -z "$remote_frontier" ] || [ "$remote_frontier" != "$base" ]; then
  fail "promoted frontier moved; refresh before submitting"
fi

mapfile -t changed_paths < <(git diff --name-only "$base" HEAD)
if [ "${#changed_paths[@]}" -eq 0 ]; then
  fail "candidate has no changes from the promoted frontier"
fi
for changed in "${changed_paths[@]}"; do
  allowed=0
  for editable in "${editable_paths[@]}"; do
    if [ "$changed" = "$editable" ] || [[ "$changed" = "$editable/"* ]]; then
      allowed=1
      break
    fi
  done
  if [ "$allowed" -ne 1 ]; then
    fail "candidate changes a non-editable path: $changed"
  fi
done

fingerprint=$(git diff --binary "$base" HEAD -- "${editable_paths[@]}" | sha256sum | \
  awk '{ print $1 }')
head_commit=$(git rev-parse HEAD)
today=$(date -u +%F)
timestamp=$(date -u +%Y%m%dT%H%M%SZ)

mkdir -p "$state_dir" "$log_dir" "$active_dir"
exec 9>"$lock_file"
flock 9

for active in "$active_dir"/*; do
  [ -e "$active" ] || continue
  active_pid=$(cat "$active" 2>/dev/null || true)
  if ! [[ "$active_pid" =~ ^[0-9]+$ ]] || ! kill -0 "$active_pid" 2>/dev/null; then
    rm -f "$active"
  fi
done

if [ -f "$ledger" ] && \
    awk -F '\t' -v fingerprint="$fingerprint" \
      '$3 == fingerprint { found=1 } END { exit !found }' "$ledger"; then
  fail "this exact editable-path diff already used an official probe"
fi

used_today=0
if [ -f "$ledger" ]; then
  used_today=$(awk -F '\t' -v today="$today" \
    '$1 == today && $6 == "reserved" { count++ } END { print count+0 }' "$ledger")
fi
remaining=$((daily_limit - used_today))
if [ "$remaining" -le 0 ]; then
  fail "daily official-probe quota of $daily_limit is exhausted"
fi

active_count=0
for active in "$active_dir"/*; do
  [ -e "$active" ] || continue
  active_count=$((active_count + 1))
done
if [ "$mode" = submit ] && [ "$active_count" -ge "$max_inflight" ]; then
  fail "local in-flight limit of $max_inflight is reached"
fi

if [ "$mode" = check ]; then
  printf 'eligible fingerprint=%s remaining_today=%s active=%s\n' \
    "$fingerprint" "$remaining" "$active_count"
  exit 0
fi

active_file="$active_dir/$fingerprint"
printf '%s\n' "$$" > "$active_file"
receipt="$log_dir/flock-submission-${timestamp}-${fingerprint:0:12}.log"
printf '%s\t%s\t%s\t%s\t%s\treserved\t%s\n' \
  "$today" "$timestamp" "$fingerprint" "$base" "$head_commit" "$receipt" \
  >> "$ledger"
flock -u 9

cleanup() {
  rm -f "$active_file"
}
trap cleanup EXIT

set +e
yukon submit --track "$track" --note-file "$note_file" --model "$model" \
  2>&1 | tee "$receipt"
status=${PIPESTATUS[0]}
set -e

exec 9>"$lock_file"
flock 9
printf '%s\t%s\t%s\t%s\t%s\texit_%s\t%s\n' \
  "$today" "$(date -u +%Y%m%dT%H%M%SZ)" "$fingerprint" "$base" \
  "$head_commit" "$status" "$receipt" >> "$ledger"
flock -u 9
exit "$status"
