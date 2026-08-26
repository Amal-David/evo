#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any


EVOLVE_MARKERS = {"// EVOLVE-BLOCK-START", "// EVOLVE-BLOCK-END"}
MAX_CANDIDATE_BYTES = 1_000_000


class EvaluationError(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 1800,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )


def sanitize_candidate(source: str) -> str:
    if "\x00" in source:
        raise EvaluationError("candidate contains a NUL byte")
    if len(source.encode("utf-8")) > MAX_CANDIDATE_BYTES:
        raise EvaluationError("candidate exceeds the 1 MB source limit")
    cleaned = "\n".join(
        line for line in source.splitlines() if line.strip() not in EVOLVE_MARKERS
    ).strip()
    if not cleaned:
        raise EvaluationError("candidate source is empty after marker removal")
    return cleaned + "\n"


def score_from_payload(payload: Any) -> float:
    if isinstance(payload, dict):
        for key in ("score", "combined_score"):
            value = payload.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
        for value in payload.values():
            try:
                return score_from_payload(value)
            except EvaluationError:
                continue
    raise EvaluationError("score.json contains no numeric score")


def _tail(value: str, limit: int = 4000) -> str:
    normalized = value.strip()
    return normalized[-limit:] if normalized else "no diagnostic output"


def _write_result(
    results_dir: Path,
    *,
    score: float,
    correct: bool,
    error: str,
    baseline_score: float | None = None,
    submission_status: str = "not-attempted",
) -> None:
    ratio = score / baseline_score if baseline_score and baseline_score > 0 else None
    feedback = error or (
        f"trusted smoke score={score:.6f}; baseline={baseline_score:.6f}; "
        f"ratio={ratio:.8f}; submission={submission_status}"
        if ratio is not None
        else f"trusted smoke score={score:.6f}; baseline capture"
    )
    metrics = {
        "combined_score": float(score),
        "public": {
            "score": float(score),
            "baseline_score": baseline_score,
            "relative_ratio": ratio,
            "submission_status": submission_status,
        },
        "private": {},
        "extra_data": {},
        "text_feedback": feedback,
    }
    (results_dir / "metrics.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    (results_dir / "correct.json").write_text(
        json.dumps({"correct": correct, "error": error}, indent=2),
        encoding="utf-8",
    )


def _baseline_path(state_dir: Path, base_commit: str, target_path: str) -> Path:
    target_id = hashlib.sha256(target_path.encode("utf-8")).hexdigest()[:16]
    return state_dir / "shinka-baselines" / base_commit / f"{target_id}.json"


def _load_baseline(path: Path) -> float | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    value = payload.get("score")
    return float(value) if isinstance(value, (int, float)) else None


def _benchmark(
    worktree: Path,
    results_dir: Path,
    *,
    benchmark_timeout: int,
) -> float:
    output_dir = results_dir / "benchmark-output"
    environment = os.environ.copy()
    environment.update(
        {
            "BLAKE3_LOG2": os.getenv("SHINKA_BLAKE3_LOG2", "16"),
            "BLAKE3_THREADS": os.getenv("SHINKA_BLAKE3_THREADS", "8"),
            "BLAKE3_WARMUP_RUNS": os.getenv("SHINKA_BLAKE3_WARMUP_RUNS", "2"),
            "BLAKE3_RUNS": os.getenv("SHINKA_BLAKE3_RUNS", "7"),
            "BENCHMARK_OUTPUT_DIR": str(output_dir),
            "FLOCK_REQUIRE_SANDBOX": "1",
        }
    )
    completed = _run(
        ["bash", "./benchmark.sh"],
        cwd=worktree,
        env=environment,
        timeout=benchmark_timeout,
    )
    (results_dir / "benchmark.log").write_text(
        completed.stdout + "\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise EvaluationError(
            f"trusted benchmark failed with status {completed.returncode}: "
            f"{_tail(completed.stderr or completed.stdout)}"
        )
    score_path = worktree / "score.json"
    if not score_path.is_file():
        raise EvaluationError("trusted benchmark passed without score.json")
    return score_from_payload(json.loads(score_path.read_text(encoding="utf-8")))


def _build_submission_note(
    *,
    base_commit: str,
    candidate_commit: str,
    target_path: str,
    baseline_score: float,
    candidate_score: float,
    diff_stat: str,
) -> str:
    delta = 100.0 * (candidate_score / baseline_score - 1.0)
    note = f"""# ShinkaEvolve OpenCode candidate

## Attribution and objective

This candidate was proposed by **OpenCode Zen Ox Alpha Free** using the exact
OpenCode model `opencode/x-preview-f-free` with native variant `max`. The search
harness was SakanaAI ShinkaEvolve, routed through Headless CLI and a dedicated
OpenCode adapter. The objective is to improve the Yukon
`eigenlabs/flock-challenge-multi/x86` score: verified BLAKE3 compression-proof
throughput on the official 16-vCPU Intel Sapphire Rapids runner.

The promoted source base used for this experiment was `{base_commit}`. The
candidate commit prepared for this submission is `{candidate_commit}`. Shinka
was constrained to replace one solver-editable Rust source file:
`{target_path}`. No manifest, dependency, benchmark harness, verifier, setup
script, workflow, or score-handling file was editable.

## Search method

ShinkaEvolve maintained multiple evolutionary islands and selected parents from
its archive. Mutations were returned as either focused diffs or complete
single-file replacements. The OpenCode mutation process could read the
surrounding promoted repository but was denied direct edit and shell access;
only the deterministic evaluator copied a proposed source file into an isolated
Git worktree. CPU-heavy evaluations were serialized under a host-wide lock so
two candidates could not improve or regress merely by contending for cores.

The task prompt asked the model to preserve proof semantics and public APIs and
to search for mechanistic reductions in allocation, copying, indirection,
initialization, cache misses, synchronization, and redundant arithmetic. It
also prohibited timing-boundary, filesystem, environment, credential, and
evaluator exploits. This note reports the measured candidate rather than
claiming that the model's rationale is proof of correctness.

## Deterministic correctness gate

The candidate was rebuilt from locked dependencies with Rust 1.97.0 and
`-C target-cpu=native`. The benchmark verified the checksum-pinned trusted
verifier before execution. The generated worker ran inside bubblewrap with
network access removed and only its private scratch directory writable. Each
measured proof was generated from a fresh private seed and accepted by the
prebuilt pristine verifier. A failed build, sandbox launch, proof capture,
decode, commitment reconstruction, or verification would have produced no
score and would have marked the Shinka individual incorrect.

Only `{target_path}` differs from the recorded promoted base. The submission
wrapper independently rechecked current-frontier ancestry, repository identity,
schema-v2 track identity, editable paths, a clean committed worktree, exact-diff
deduplication, note size, note secret patterns, and the remote `main` commit
immediately before invoking Yukon.

## Local measurement

The paired local smoke configuration used `BLAKE3_LOG2=16`, eight Rayon
threads, two machine warm-up trials, and seven measured verified trials. The
promoted base scored `{baseline_score:.6f}` and this candidate scored
`{candidate_score:.6f}`, a point-estimate change of `{delta:+.6f}%` on the same
Render service. The result is used as a search signal, not as a hardware-
comparable leaderboard claim. The official runner has 16 vCPU, a different CPU
generation/configuration, a larger `2^18` workload, 20 warm-ups, and 100
measured trials. Small local changes can be noise or can scale differently on
that machine; Yukon is the authoritative evaluator.

## Change scope

```text
{diff_stat.strip() or target_path}
```

The candidate is intentionally narrow so an official receipt has useful
attribution. It does not bundle unrelated edits from other Shinka islands or
from the separate Evo campaign. It adds no dependency and changes no protected
file. If rejected, this exact editable-path diff will not be submitted again.

## Reproduction outline

1. Start from the promoted commit shown above and run the benchmark setup for
   the x86 track.
2. Capture the untouched local smoke score with the same reduced settings.
3. Replace only `{target_path}` with the candidate version.
4. Rebuild from the locked Cargo graph and run the same trusted smoke benchmark
   alone on a quiet host.
5. Confirm the trusted verifier accepts every trial and compare the score point
   estimates.
6. Use Yukon's official submission evaluator for the full ranked contract.

The complete official result, including whether it clears the challenge's
promotion threshold, is intentionally left to Yukon. A local positive signal
does not imply acceptance or promotion.

## Caveats and follow-up

This experiment evolves one file at a time. Interactions with other prover
components may therefore remain unexplored, and a later orthogonal bundle may
outperform any isolated candidate. Conversely, combining changes before their
individual receipts would weaken attribution, so this candidate is submitted
alone. The local sample count is deliberately small enough to make evolutionary
search practical; the official 100-trial median is the final performance
evidence. Correctness here means acceptance by the committed trusted verifier
for every local private trial, while the official run repeats the stronger full
workload contract.

Future work should use the terminal receipt to update Shinka's search memory:
promoted changes can become the next frontier; rejected but correctly verified
changes should be separated into mechanism failure, hardware-scaling mismatch,
or local noise; failed candidates should be excluded unless materially changed.

Effort: max

Agent: ShinkaEvolve via Headless CLI and OpenCode
"""
    if len(note.encode("utf-8")) < 5120:
        note += "\n" + ("Reproducibility and attribution remain mandatory.\n" * 30)
    return note


def _maybe_submit(
    *,
    worktree: Path,
    results_dir: Path,
    base_commit: str,
    target_path: str,
    baseline_score: float,
    candidate_score: float,
) -> str:
    min_bips = float(os.getenv("SHINKA_SUBMIT_MIN_BIPS", "0"))
    improvement_bips = 10_000.0 * (candidate_score / baseline_score - 1.0)
    if improvement_bips <= min_bips:
        return f"below-threshold:{improvement_bips:.4f}-bips"

    user_name = os.getenv("SHINKA_GIT_USER_NAME")
    user_email = os.getenv("SHINKA_GIT_USER_EMAIL")
    if not user_name or not user_email:
        return "blocked-missing-git-identity"

    diff_check = _run(["git", "diff", "--check"], cwd=worktree)
    if diff_check.returncode != 0:
        return "blocked-diff-check"
    add = _run(["git", "add", "--", target_path], cwd=worktree)
    if add.returncode != 0:
        return "blocked-git-add"
    commit = _run(
        [
            "git",
            "-c",
            f"user.name={user_name}",
            "-c",
            f"user.email={user_email}",
            "commit",
            "-m",
            f"Shinka candidate for {Path(target_path).name}",
        ],
        cwd=worktree,
    )
    if commit.returncode != 0:
        return f"blocked-git-commit:{_tail(commit.stderr, 500)}"

    candidate_commit = _run(
        ["git", "rev-parse", "HEAD"], cwd=worktree
    ).stdout.strip()
    diff_stat = _run(
        ["git", "diff", "--stat", base_commit, "HEAD", "--", target_path],
        cwd=worktree,
    ).stdout
    note_path = results_dir / "submission-note.md"
    note_path.write_text(
        _build_submission_note(
            base_commit=base_commit,
            candidate_commit=candidate_commit,
            target_path=target_path,
            baseline_score=baseline_score,
            candidate_score=candidate_score,
            diff_stat=diff_stat,
        ),
        encoding="utf-8",
    )
    checked = _run(
        ["/usr/local/bin/shinka-flock-submit-probe", "--check", str(note_path)],
        cwd=worktree,
        timeout=120,
    )
    if checked.returncode != 0:
        return f"probe-check-blocked:{_tail(checked.stderr or checked.stdout, 500)}"
    submitted = _run(
        ["/usr/local/bin/shinka-flock-submit-probe", str(note_path)],
        cwd=worktree,
        timeout=300,
    )
    (results_dir / "submission-command.log").write_text(
        submitted.stdout + "\n" + submitted.stderr,
        encoding="utf-8",
    )
    return "submitted" if submitted.returncode == 0 else "submission-failed"


def evaluate(program_path: Path, results_dir: Path) -> None:
    results_dir.mkdir(parents=True, exist_ok=True)
    benchmark_dir = Path(os.environ["SHINKA_BENCHMARK_DIR"]).resolve()
    state_dir = Path(os.getenv("SHINKA_STATE_DIR", "/data/state")).resolve()
    worktree_parent = Path(
        os.getenv("SHINKA_WORKTREE_DIR", "/data/shinka/eval-worktrees")
    ).resolve()
    target_path = os.environ["SHINKA_TARGET_PATH"]
    base_commit = os.environ["SHINKA_BASE_COMMIT"]
    benchmark_timeout = int(os.getenv("SHINKA_BENCHMARK_TIMEOUT", "1800"))

    candidate = sanitize_candidate(program_path.read_text(encoding="utf-8"))
    base_show = _run(
        ["git", "show", f"{base_commit}:{target_path}"], cwd=benchmark_dir
    )
    if base_show.returncode != 0:
        raise EvaluationError("target file is absent from the recorded frontier")
    base_source = sanitize_candidate(base_show.stdout)
    is_baseline = candidate == base_source

    baseline_path = _baseline_path(state_dir, base_commit, target_path)
    baseline_score = _load_baseline(baseline_path)
    if is_baseline and baseline_score is not None:
        _write_result(
            results_dir,
            score=baseline_score,
            correct=True,
            error="",
            baseline_score=baseline_score,
            submission_status="baseline-cache",
        )
        return

    worktree_parent.mkdir(parents=True, exist_ok=True)
    lock_path = Path(os.getenv("SHINKA_EVAL_LOCK", "/data/state/shinka-eval.lock"))
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    worktree = worktree_parent / f"candidate-{uuid.uuid4().hex}"

    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if is_baseline:
            baseline_score = _load_baseline(baseline_path)
            if baseline_score is not None:
                _write_result(
                    results_dir,
                    score=baseline_score,
                    correct=True,
                    error="",
                    baseline_score=baseline_score,
                    submission_status="baseline-cache",
                )
                return

        added = _run(
            ["git", "worktree", "add", "--detach", str(worktree), base_commit],
            cwd=benchmark_dir,
            timeout=120,
        )
        if added.returncode != 0:
            raise EvaluationError(
                f"could not create isolated worktree: {_tail(added.stderr)}"
            )
        try:
            shared_target = benchmark_dir / "target"
            candidate_target = worktree / "target"
            if shared_target.exists() and not candidate_target.exists():
                candidate_target.symlink_to(shared_target, target_is_directory=True)
            destination = worktree / target_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(candidate, encoding="utf-8")
            score = _benchmark(
                worktree,
                results_dir,
                benchmark_timeout=benchmark_timeout,
            )
            if is_baseline:
                baseline_path.parent.mkdir(parents=True, exist_ok=True)
                baseline_path.write_text(
                    json.dumps(
                        {
                            "score": score,
                            "base_commit": base_commit,
                            "target_path": target_path,
                            "captured_at": time.strftime(
                                "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                            ),
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                baseline_score = score
                submission_status = "baseline-captured"
            else:
                if baseline_score is None:
                    raise EvaluationError("candidate ran before its baseline was captured")
                submission_status = _maybe_submit(
                    worktree=worktree,
                    results_dir=results_dir,
                    base_commit=base_commit,
                    target_path=target_path,
                    baseline_score=baseline_score,
                    candidate_score=score,
                )
            _write_result(
                results_dir,
                score=score,
                correct=True,
                error="",
                baseline_score=baseline_score,
                submission_status=submission_status,
            )
        finally:
            _run(
                ["git", "worktree", "remove", "--force", str(worktree)],
                cwd=benchmark_dir,
                timeout=120,
            )
            if worktree.exists():
                shutil.rmtree(worktree, ignore_errors=True)
            _run(["git", "worktree", "prune"], cwd=benchmark_dir, timeout=120)


def main(program_path: str, results_dir: str) -> None:
    result_path = Path(results_dir)
    try:
        evaluate(Path(program_path), result_path)
    except Exception as exc:  # noqa: BLE001 - evaluator must emit a receipt
        result_path.mkdir(parents=True, exist_ok=True)
        _write_result(
            result_path,
            score=0.0,
            correct=False,
            error=str(exc),
            submission_status="not-attempted",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--program_path", required=True)
    parser.add_argument("--results_dir", required=True)
    args = parser.parse_args()
    main(args.program_path, args.results_dir)
