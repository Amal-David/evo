from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EVALUATOR_PATH = ROOT / "deploy" / "render" / "shinka-flock" / "evaluate.py"
SPEC = importlib.util.spec_from_file_location("shinka_flock_evaluator", EVALUATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
EVALUATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVALUATOR)


def test_sanitize_candidate_removes_only_exact_evolve_markers() -> None:
    source = """// EVOLVE-BLOCK-START
fn useful() {
    // keep EVOLVE-BLOCK-START in explanatory text
}
// EVOLVE-BLOCK-END
"""

    assert EVALUATOR.sanitize_candidate(source) == (
        "fn useful() {\n"
        "    // keep EVOLVE-BLOCK-START in explanatory text\n"
        "}\n"
    )


def test_sanitize_candidate_rejects_empty_program() -> None:
    with pytest.raises(EVALUATOR.EvaluationError, match="empty"):
        EVALUATOR.sanitize_candidate(
            "// EVOLVE-BLOCK-START\n// EVOLVE-BLOCK-END\n"
        )


def test_score_from_payload_prefers_named_score() -> None:
    assert EVALUATOR.score_from_payload({"score": 123.5, "other": 999}) == 123.5
    assert EVALUATOR.score_from_payload({"result": {"combined_score": 8}}) == 8.0


def test_default_submission_threshold_allows_noise_masked_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SHINKA_SUBMIT_MIN_BIPS", raising=False)
    monkeypatch.delenv("SHINKA_GIT_USER_NAME", raising=False)
    monkeypatch.delenv("SHINKA_GIT_USER_EMAIL", raising=False)

    accepted = EVALUATOR._maybe_submit(
        worktree=tmp_path,
        results_dir=tmp_path,
        base_commit="a" * 40,
        target_path="crates/flock-prover/src/recycle_alloc.rs",
        baseline_score=100.0,
        candidate_score=99.5,
    )
    rejected = EVALUATOR._maybe_submit(
        worktree=tmp_path,
        results_dir=tmp_path,
        base_commit="a" * 40,
        target_path="crates/flock-prover/src/recycle_alloc.rs",
        baseline_score=100.0,
        candidate_score=97.0,
    )

    assert accepted == "blocked-missing-git-identity"
    assert rejected.startswith("below-threshold:")


def test_submission_note_meets_yukon_size_and_has_exact_attribution() -> None:
    note = EVALUATOR._build_submission_note(
        base_commit="a" * 40,
        candidate_commit="b" * 40,
        target_path="crates/flock-prover/src/recycle_alloc.rs",
        baseline_score=100.0,
        candidate_score=100.01,
        diff_stat="1 file changed, 1 insertion(+)",
        changed_paths=["crates/flock-prover/src/recycle_alloc.rs"],
        seed_submission="25ec5a6e-7c56-4f1d-bd14-522681f952be",
    )

    assert 5120 <= len(note.encode("utf-8")) <= 102400
    assert "OpenCode Zen Free Pool (Muse Spark 1.2 / Hy3)" in note
    assert "opencode/muse-spark-1.2-contributor-free" in note
    assert "opencode/hy3-free" in note
    assert "variant `high`" in note
    assert "Landlock and seccomp" in note
    assert "bubblewrap" not in note
    assert "25ec5a6e-7c56-4f1d-bd14-522681f952be" in note


def test_evaluator_captures_baseline_then_scores_isolated_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "benchmark"
    target_path = "crates/flock-prover/src/recycle_alloc.rs"
    target = repository / target_path
    target.parent.mkdir(parents=True)
    target.write_text("pub fn value() -> u64 { 100 }\n", encoding="utf-8")
    benchmark = repository / "benchmark.sh"
    benchmark.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"if grep -q optimized {target_path}; then score=101; else score=100; fi\n"
        "printf '{\"score\": %s}\\n' \"$score\" > score.json\n",
        encoding="utf-8",
    )
    benchmark.chmod(0o755)
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    monkeypatch.setenv("SHINKA_BENCHMARK_DIR", str(repository))
    monkeypatch.setenv("SHINKA_BASE_COMMIT", base_commit)
    monkeypatch.setenv("SHINKA_TARGET_PATH", target_path)
    monkeypatch.setenv("SHINKA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SHINKA_WORKTREE_DIR", str(tmp_path / "worktrees"))
    monkeypatch.setenv("SHINKA_EVAL_LOCK", str(tmp_path / "state" / "eval.lock"))

    initial = tmp_path / "initial.rs"
    initial.write_text(
        "// EVOLVE-BLOCK-START\n"
        "pub fn value() -> u64 { 100 }\n"
        "// EVOLVE-BLOCK-END\n",
        encoding="utf-8",
    )
    baseline_results = tmp_path / "baseline-results"
    EVALUATOR.main(str(initial), str(baseline_results))
    baseline_metrics = json.loads(
        (baseline_results / "metrics.json").read_text(encoding="utf-8")
    )
    assert baseline_metrics["combined_score"] == 100.0
    assert baseline_metrics["public"]["submission_status"] == "baseline-captured"

    candidate = tmp_path / "candidate.rs"
    candidate.write_text(
        "// EVOLVE-BLOCK-START\n"
        "pub fn value() -> u64 { 101 } // optimized\n"
        "// EVOLVE-BLOCK-END\n",
        encoding="utf-8",
    )
    candidate_results = tmp_path / "candidate-results"
    EVALUATOR.main(str(candidate), str(candidate_results))
    candidate_metrics = json.loads(
        (candidate_results / "metrics.json").read_text(encoding="utf-8")
    )
    assert candidate_metrics["combined_score"] == 101.0
    assert candidate_metrics["public"]["relative_ratio"] == 1.01
    assert (
        candidate_metrics["public"]["submission_status"]
        == "blocked-missing-git-identity"
    )
    assert subprocess.run(
        ["git", "status", "--short"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""


def test_evaluator_layers_seed_patch_but_does_not_resubmit_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "benchmark"
    target_path = "crates/flock-prover/src/r1cs_hashes/blake3_witgen8.rs"
    support_path = "crates/flock-core/src/merkle.rs"
    target = repository / target_path
    support = repository / support_path
    target.parent.mkdir(parents=True)
    support.parent.mkdir(parents=True)
    target.write_bytes(b"pub fn witness() -> u64 { 100 }\r\n")
    support.write_bytes(b"pub fn merkle() -> u64 { 100 }\r\n")
    benchmark = repository / "benchmark.sh"
    benchmark.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f"if grep -q seed_witness {target_path} && "
        f"grep -q seed_merkle {support_path}; then score=102; else score=100; fi\n"
        "printf '{\"score\": %s}\\n' \"$score\" > score.json\n",
        encoding="utf-8",
    )
    benchmark.chmod(0o755)
    subprocess.run(["git", "init"], cwd=repository, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repository, check=True
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repository,
        check=True,
    )
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(
        ["git", "commit", "-m", "baseline"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    target.write_bytes(b"pub fn witness() -> u64 { 102 } // seed_witness\r\n")
    support.write_bytes(b"pub fn merkle() -> u64 { 102 } // seed_merkle\r\n")
    seed_patch = tmp_path / "seed.patch"
    seed_patch.write_bytes(
        subprocess.run(
            ["git", "diff", "--binary"],
            cwd=repository,
            check=True,
            capture_output=True,
        ).stdout,
    )
    seed_target = tmp_path / "seed-target.rs"
    seed_target.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(
        ["git", "restore", "--", target_path, support_path],
        cwd=repository,
        check=True,
    )

    monkeypatch.setenv("SHINKA_BENCHMARK_DIR", str(repository))
    monkeypatch.setenv("SHINKA_BASE_COMMIT", base_commit)
    monkeypatch.setenv("SHINKA_TARGET_PATH", target_path)
    monkeypatch.setenv("SHINKA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("SHINKA_WORKTREE_DIR", str(tmp_path / "worktrees"))
    monkeypatch.setenv("SHINKA_EVAL_LOCK", str(tmp_path / "state" / "eval.lock"))
    monkeypatch.setenv("SHINKA_SEED_PATCH", str(seed_patch))
    monkeypatch.setenv("SHINKA_SEED_TARGET_SOURCE", str(seed_target))
    monkeypatch.setenv(
        "SHINKA_SEED_SUBMISSION", "25ec5a6e-7c56-4f1d-bd14-522681f952be"
    )

    baseline_program = tmp_path / "baseline.rs"
    baseline_program.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    baseline_results = tmp_path / "baseline-results"
    EVALUATOR.main(str(baseline_program), str(baseline_results))
    assert json.loads(
        (baseline_results / "metrics.json").read_text(encoding="utf-8")
    )["combined_score"] == 100.0

    seed_results = tmp_path / "seed-results"
    EVALUATOR.main(str(seed_target), str(seed_results))
    seed_metrics = json.loads(
        (seed_results / "metrics.json").read_text(encoding="utf-8")
    )
    assert seed_metrics["combined_score"] == 102.0
    assert seed_metrics["public"]["submission_status"] == "seed-reference-no-submit"
    assert subprocess.run(
        ["git", "status", "--short"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""
