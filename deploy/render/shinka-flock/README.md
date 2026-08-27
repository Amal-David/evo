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
- Optional submission-identity overrides: `SHINKA_GIT_USER_NAME` and
  `SHINKA_GIT_USER_EMAIL`. The service defaults to the public
  `Amal-David`/GitHub-noreply identity so a correct candidate cannot be blocked
  merely because private identity values were not copied into Render.

The default evolutionary lane replaces only
`crates/flock-prover/src/r1cs_hashes/blake3_witgen8.rs`. It starts from official
near-miss submission `25ec5a6e-7c56-4f1d-bd14-522681f952be`, which scored only
440.23 proofs/s below the promoted frontier. The supervisor recovers that
submission in an isolated Yukon clone, stores a checksummed patch on the
persistent disk, and verifies that the patch applies to the current promoted
base. Its three supporting-file changes remain fixed while Shinka evolves the
witness file upward. The unchanged seed is benchmarked for reference but is
never resubmitted. Set `SHINKA_TARGET_PATH` to another single Rust file under
the x86 track's editable paths only together with a compatible seed. Files over
100 KiB are rejected by default to keep mutation prompts bounded.

The curated, secret-free research dossier is versioned at
`deploy/render/shinka-flock/research-seed.md`. At boot it is copied to
`/data/shinka/logbook/research-seed.md`; its SHA-256 and provenance receipt are
written under `/data/state`. Every Shinka proposal receives this context with
explicit OFFICIAL, LOCAL, OPEN, and CLOSED labels, so historical failures are
not silently rediscovered or mistaken for current frontier facts.

At the same gate, the freshly installed `yukon-cli` skill is read into the
Shinka task prompt and checksummed under `/data/state`. The Yukon participation
token remains only in the service environment; it is never copied into the
prompt, logbook, note, result archive, or public submission.

The dedicated branch deliberately reuses the existing Flock service's
Dockerfile path so Render can clone its service configuration without exposing
or manually copying environment secrets. The live Evo service remains on
`codex/opencode-headless`, where the same path still builds the Evo image.

Shinka uses the official Headless CLI provider string
`headless/opencode@opencode/mimo-v2.5-free?effort=high`. The image places a
dedicated OpenCode wrapper first on `PATH`; it verifies that the exact model and
native `high` variant reach OpenCode unchanged. The last model/variant receipt
is stored at
`/data/state/shinka-opencode-last-invocation` without prompts or credentials.

Render blocks the Linux namespaces required by ordinary bubblewrap. This image
therefore provides a contract-specific `bwrap` compatibility adapter that
keeps the benchmark and checksum-pinned verifier unchanged while restricting
the generated worker with Landlock and seccomp. It denies network and
process-inspection syscalls, limits filesystem access to reviewed runtime
libraries and the private benchmark scratch directory, and rejects any
unexpected launcher argument or path.

Before Shinka can generate proposals, the supervisor must capture a positive,
correct untouched-baseline receipt through that sandbox and must verify the
official near-miss patch against the promoted frontier. A failed gate holds the
campaign for inspection instead of letting zero-score generations consume model
calls. A materially changed descendant with a positive point estimate, or a
mechanistically distinct candidate within 1% of baseline whose local result may
be noise- or hardware-masked, may trigger one official Yukon probe after
current-frontier, editable-path, correctness, deduplication, attribution,
note-size, note-secret, daily-quota, and cooldown checks. The monitor must
observe receipts; it must not bypass these gates.
