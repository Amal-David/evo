# ShinkaEvolve Flock runner on Render

This image runs an isolated ShinkaEvolve campaign against the promoted Yukon
Flock x86 frontier. It does not share a disk, process, worktree, or benchmark
lock with the existing Evo service.

Render configuration:

- Service type: private service
- Branch: `codex/shinka-opencode-flock`
- Dockerfile: `deploy/render/flock/Dockerfile`
- Region: Singapore
- Instance: Pro Ultra (8 CPU, 32 GB RAM)
- Persistent disk: 50 GB mounted at `/data`
- Required secret: `YUKON_API_TOKEN`
- Required OpenCode authentication: the same OpenCode configuration or
  provider environment used by the existing Flock service
- Submission identity: `SHINKA_GIT_USER_NAME` and `SHINKA_GIT_USER_EMAIL`

The default evolutionary lane replaces only
`crates/flock-prover/src/recycle_alloc.rs`. Set `SHINKA_TARGET_PATH` to another
single Rust file under the x86 track's editable paths before the first run to
change lanes. Files over 100 KiB are rejected by default to keep mutation
prompts bounded.

The dedicated branch deliberately reuses the existing Flock service's
Dockerfile path so Render can clone its service configuration without exposing
or manually copying environment secrets. The live Evo service remains on
`codex/opencode-headless`, where the same path still builds the Evo image.

Shinka uses the official Headless CLI provider string
`headless/opencode@opencode/x-preview-f-free?effort=xhigh`. The image places a
dedicated OpenCode wrapper first on `PATH`; it verifies the exact model and
rewrites Headless's native `--variant xhigh` to `--variant max`. The last
model/variant receipt is stored at
`/data/state/shinka-opencode-last-invocation` without prompts or credentials.

Candidate benchmarks are serialized and run with the checksum-pinned trusted
verifier inside bubblewrap. A positive local point estimate may trigger one
official Yukon probe after current-frontier, editable-path, correctness,
deduplication, attribution, note-size, note-secret, daily-quota, and cooldown
checks. The monitor must observe receipts; it must not bypass these gates.
