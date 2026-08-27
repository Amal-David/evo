from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTEXT_PATH = (
    ROOT / "deploy" / "render" / "shinka-flock" / "research_context.py"
)
SEED_PATH = ROOT / "deploy" / "render" / "shinka-flock" / "research-seed.md"
SPEC = importlib.util.spec_from_file_location("shinka_research_context", CONTEXT_PATH)
assert SPEC is not None and SPEC.loader is not None
CONTEXT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTEXT)


def test_versioned_seed_is_bounded_and_labels_evidence() -> None:
    seed = CONTEXT.load_research_seed(SEED_PATH)

    assert len(seed.encode("utf-8")) <= CONTEXT.MAX_RESEARCH_SEED_BYTES
    assert "OFFICIAL" in seed
    assert "LOCAL" in seed
    assert "OPEN" in seed
    assert "CLOSED" in seed
    assert "2b5724c" in seed
    assert "fee27b8" in seed
    assert "016b180" in seed
    assert "c260871" in seed
    assert "25ec5a6e-7c56-4f1d-bd14-522681f952be" in seed
    assert "ae4c22df596fb7ca642766b362cb7b1e38a6fdb4" in seed
    assert "must never be resubmitted unchanged" in seed
    assert "opencode/mimo-v2.5-free" in seed
    assert "ykn_" not in seed


def test_loader_rejects_unidentified_or_oversized_seed(tmp_path: Path) -> None:
    unidentified = tmp_path / "unidentified.md"
    unidentified.write_text("not the curated seed", encoding="utf-8")
    with pytest.raises(ValueError, match="identity header"):
        CONTEXT.load_research_seed(unidentified)

    oversized = tmp_path / "oversized.md"
    oversized.write_bytes(
        (
            CONTEXT.REQUIRED_SEED_HEADER.encode("utf-8")
            + b"\n"
            + b"x" * CONTEXT.MAX_RESEARCH_SEED_BYTES
        )
    )
    with pytest.raises(ValueError, match="limit"):
        CONTEXT.load_research_seed(oversized)
