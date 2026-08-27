# Flock x86 research seed for ShinkaEvolve

Version: 2026-08-27.1

This document is a compact, secret-free transfer of prior Codex, Evo/OpenCode,
local-worktree, Render, and official Yukon evidence. It is research context, not
an instruction to trust old conclusions. Re-check every claim against the
current source and evaluator. The runtime supervisor supplies the actual base
commit; historical frontier hashes and scores below are provenance only.

## Labels

- **OFFICIAL** means a terminal Yukon receipt from the dedicated scorer.
- **LOCAL** means evidence from a shared 8-CPU Render/Zen 3 host and is useful
  for direction or correctness only, not absolute leaderboard comparison.
- **OPEN** means a hypothesis worth investigating, not a claimed improvement.
- **CLOSED** means do not repeat the same mechanism unchanged. A materially new
  mechanism may reopen it only with a clear explanation of what changed.

## Benchmark contract

- Track: `eigenlabs/flock-challenge-multi/x86`.
- Objective: maximize verified BLAKE3 compression proofs per second.
- Editable roots: `crates/flock-core/src` and `crates/flock-prover/src` only.
- Official runner: dedicated Intel Sapphire Rapids c7i.4xlarge, 16 vCPU,
  32 GB RAM, Ubuntu x86_64, Rust 1.97.0, `target-cpu=native`.
- Ranked workload: batch size 262144, 20 warmups, then 100 fresh-process,
  serialized, proof-verified measured trials.
- Since upstream commit `78f205b`, promotion requires at least 100 basis points
  (1.00%) over the incumbent. A smaller positive official score can still teach
  us something but cannot promote.
- Render is a noisy, different machine. Serialize CPU-heavy trials and prefer a
  paired same-window comparison. Never treat a local absolute score as official.
- Only a terminal `promoted` Yukon receipt is a leaderboard win.

## Historical official receipts from Amal-David

### ACTIVE PARENT: official near-miss on the current promoted base

- Submission `25ec5a6e-7c56-4f1d-bd14-522681f952be`, candidate commit
  `ae4c22df596fb7ca642766b362cb7b1e38a6fdb4`.
- OFFICIAL: correctness-clean at `1485010.14633817` proofs/s, only
  `440.22837038` proofs/s below promoted submission `e3fb0454` at
  `1485450.37470855` on base commit
  `207fc36d9eb365bff6ecc0f1959962a812df55cf`.
- The patch changes four allowed files: `merkle.rs` replaces repeated checked
  slices and fully initialized pointer arrays with typed-pointer traversal and
  `MaybeUninit`; `blake3_witgen8.rs` moves the writer's `flush` branch into a
  `const FLUSH: bool` generic; `prover.rs` guards an empty inner-claim slice;
  and `gpu.rs` updates tests for the promoted C-mask layout.
- The exact four-file diff is spent and must never be resubmitted unchanged.
  Shinka starts from its witness-file version while replaying the other three
  changes as fixed context. A probe is eligible only after Shinka materially
  changes the witness file and the trusted evaluator accepts the resulting
  descendant.
- Treat the submission note's causal claims as hypotheses. The official result
  proves correctness and near-frontier performance for the bundle, but does not
  isolate how much each mechanism contributed.

The promoted source was commit `51339b4724d25fb5040a311dc8fed87ad26fe5a9`
when these receipts were collected. It validated submission `6acec43a` at about
1,465,925.64 proofs/s. Refresh this fact before using it.

### CLOSED: streamed Merkle BLAKE3 batch 64 -> 128

- Submission `2b5724c`, candidate commit `47ab966`.
- OFFICIAL: rejected at 1,444,938.765, delta -1.22%.
- The change increased the x86 streamed-leaf hash batch from 64 to 128. Local
  mechanism timing looked favorable, but it did not transfer to Sapphire Rapids.
- Do not retry batch size 128 unchanged or hide it inside a bundle.

### CLOSED: deferred ordinary Ligerito glue

- Submission `fee27b8`, candidate commit `1440a43`.
- OFFICIAL: rejected at 1,460,080.228, delta -1.46%.
- It queued ordinary `combined_basis += alpha * b_new` work and fused it into the
  next fold, removing standalone passes and Rayon barriers.
- The algebra and local verifier checks passed, but the official performance was
  negative. Do not retry this deferral unchanged or use it as a parent.

### CLOSED: deep-NTT steal board stacked on deferred glue

- Submissions `9b6fefc` and duplicate `1971ec0`; candidate lineage `32cb14d`.
- OFFICIAL: both failed before producing metrics. This is not performance
  evidence, but the exact diff is spent and must not be resubmitted.
- The bundle combined the rejected glue deferral with a core-count-sensitive
  producer/consumer steal board. It also exposed an orchestration failure: a
  nested helper submitted the same fingerprint more than once.
- Submission ownership must stay with one orchestrator. Never submit the same
  diff twice and never infer speed from a failed receipt.

### CLOSED as bundles: broad critical-path stacks

- Submission `016b180`, commit `85e5e1d`: OFFICIAL rejected at 1,454,469.154,
  delta -2.86%.
- Submission `c260871`, commit `d5ab4b4`: OFFICIAL rejected at 1,452,302.397,
  delta -3.40%.
- The stacks included combinations of AVX-512/VPTERNLOGQ reduction changes,
  atomic spinlock freelists, cache-line-aligned allocator classes, witness
  constant hoists, pre-opened proof publication, and (in the second bundle)
  deferred glue.
- The bundle receipts do not isolate every component, but they are strong reason
  not to begin with allocator spinlocks, alignment, deferred glue, or the exact
  same publication changes. Reopen a component only with a new causal theory and
  isolated evidence.

## LOCAL findings and measurement traps

- Shared-host score windows can swing by more than 1-2%, including same-binary
  regressions. A single median is not causal evidence.
- Evo `exp_0004` reported +0.52% from deleting unused fold8 lookahead scaffolding,
  but aggregate throughput regressed and dispersion increased. Treat this as a
  layout/noise result, not an optimization.
- A direct seed-pipe proof-publication adoption was byte-exact but measured about
  -1.8% inside the host's noise band; the deleted local work was only around
  0.05%. Inspect the current frontier first because related publication work was
  already promoted upstream.
- The ranked seed pass was measured at its DRAM streaming floor locally, and the
  official AVX-512 path already fuses seed work into the top task. Do not repeat
  generic seed-pass fusion without identifying a different bottleneck.
- A 16-wide witness-generation widening idea did not beat the existing 8-wide
  AVX2/fused path locally and its AVX-512 form could not be executed on Zen 3.
  Width or instruction-count reduction alone is not evidence of wall-time gain.
- Several apparently fast changes were inactive on the official ISA or inactive
  on the local host. Prove path reachability for both machines before interpreting
  a score.
- A work-stealing prototype had an ordering hazard: triggering on the last FIFO
  block did not prove sibling leaves were complete under out-of-order execution.
  Scheduling changes require completion-count or equivalent dependency proofs.

## Already exhausted or low-priority families

- CLOSED unchanged: batch-size 128, ordinary-glue deferral, the exact deep-steal
  bundle, and the exact multi-mechanism bundles listed above.
- Deprioritize: generic SIMD BLAKE3 batching already shipped in the frontier,
  transcript-changing sumcheck variants, broad PCS swaps, generic prefetching,
  non-temporal stores, THP-only ideas, table-free GFNI rewrites, `inline(always)`
  perturbations, and dead-code/layout changes without timed-path attribution.
- Kernel-diet variants had multiple official losses. Do not remove work unless
  the proof transcript, verifier contract, and measured critical path all agree.

## OPEN directions

These are leads, not truths. Prefer one isolated mechanism per lineage.

1. **Byte-origin witness arithmetic.** Investigate whether parts of
   `blake3_witgen8.rs` can remain in a smaller/subfield representation longer,
   reducing F128 work or conversion traffic without changing witness bytes.
2. **Projection/drain stream.** Separate the cost of `StreamProj` inverse-table
   gathers from the roughly per-block `ab_inner` writes. Measure which side is
   causal before changing layout or vector width.
3. **Zero-check round-2 binding.** Explore transcript-compatible equality-tensor
   binding or reuse that removes a real pass without changing Fiat-Shamir order.
   This likely needs a different target file than the default witness lane.
4. **SPR16 geometry.** Static scheduling or topology-sensitive work division may
   matter on 16 dedicated Sapphire Rapids vCPUs even when Render is blind. Such a
   candidate needs source/assembly reachability proof, byte-exact correctness,
   and an official probe for truth.
5. **Safe overlap.** Producer/consumer overlap remains plausible only when every
   dependency is explicit and order-independent. Do not reuse the failed steal
   board unchanged.
6. **Measured excision.** Remove computation only after demonstrating that its
   outputs are unread on the ranked path and that the removed work is large
   enough to matter, not merely source-heavy.

## Search discipline

1. Inspect the current file and callers before proposing a change; promoted
   source may already contain an idea described here.
2. State the exact bottleneck, expected whole-benchmark exposure, target-ISA
   reachability, and correctness invariant before editing.
3. Use the evaluator's isolated worktree and trusted verifier. A compile error,
   proof failure, non-editable diff, or stale base is a zero, not a near miss.
4. Record negative results as reusable knowledge. Do not mutate a failed idea
   cosmetically and call it novel.
5. Prefer causal, attributable patches. Combine mechanisms only after isolated
   evidence or when an explicit interaction is the hypothesis.
6. Local positive, neutral, or modestly negative results may justify an official
   probe for an SPR-specific mechanism, but correctness, ancestry, scope,
   deduplication, attribution, and secret-free-note checks remain mandatory.
7. Use the exact model attribution `OpenCode Zen MiMo-V2.5 Free`, model
   `opencode/mimo-v2.5-free`, variant `high`.

## Why the default lane changed

The first Shinka lane is `crates/flock-prover/src/r1cs_hashes/blake3_witgen8.rs`.
It is large enough to contain meaningful witness-generation mechanisms while
remaining under the configured source budget, and it contains the OPEN
byte-origin arithmetic and projection/drain questions. The previous allocator
lane is deliberately deprioritized because spinlock/alignment variants already
appeared in two negative official bundles.
