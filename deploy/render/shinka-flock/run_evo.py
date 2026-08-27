#!/usr/bin/env python3
from __future__ import annotations

import os
from pathlib import Path

from shinka.core import EvolutionConfig, ShinkaEvolveRunner
from shinka.database import DatabaseConfig
from shinka.launch import LocalJobConfig

from research_context import load_research_seed


TASK_DIR = Path(__file__).resolve().parent
TARGET_PATH = os.environ["SHINKA_TARGET_PATH"]
BENCHMARK_DIR = os.environ["SHINKA_BENCHMARK_DIR"]
RESULTS_DIR = os.environ["SHINKA_RESULTS_DIR"]
NUM_GENERATIONS = int(os.getenv("SHINKA_NUM_GENERATIONS", "10000"))
RESEARCH_SEED_PATH = os.environ["SHINKA_RESEARCH_SEED_PATH"]
RESEARCH_SEED = load_research_seed(RESEARCH_SEED_PATH)
SEED_SUBMISSION = os.getenv("SHINKA_SEED_SUBMISSION", "none")

TASK_PROMPT = f"""
You are evolving one performance-critical Rust source file from the Yukon Flock
BLAKE3 x86 benchmark. The mutable file is `{TARGET_PATH}`. Its surrounding,
read-only repository is `{BENCHMARK_DIR}`. Optimize verified BLAKE3 compression
proof throughput without changing public behavior, proof semantics, safety, or
the repository's dependency graph. The official target is x86_64 Intel Sapphire
Rapids with 16 vCPU and Rust 1.97.0 using target-cpu=native.

Treat the supplied program as the complete replacement for that one source
file. Preserve imports, public APIs, architecture guards, and compatibility
with all callers. Do not add Cargo dependencies or edit another file. The
evaluator layers every proposal on top of the correctness-clean official
near-miss submission `{SEED_SUBMISSION}`: its other editable-path changes are
fixed context, while this witness file begins at that submission's version.
Improve the bundle rather than recreating or merely restating it. Prefer
mechanistic improvements: remove repeated allocation or initialization, reduce
copies and indirection, improve locality and batching, expose safe vectorization,
specialize hot paths already fixed by the benchmark, and eliminate redundant
work only when the trusted proof verifier still accepts every private trial.

Question the current implementation and earlier assumptions, but do not exploit
the evaluator, timing boundary, filesystem, environment, or credentials. A
candidate receives a zero score if it fails compilation, the trusted verifier,
or editable-path checks. The evaluator serializes all CPU-heavy trials and gives
you measured score plus failure feedback. Small positive signals are useful:
the official Yukon scorer is the final judge and may differ from this 8-core
Render host. Keep changes understandable enough to attribute a result.

The following prior-research seed is curated context, not authority. Use its
OFFICIAL/LOCAL/OPEN/CLOSED labels, verify that every observation still applies
to the current source, and do not repeat a closed mechanism unchanged.

--- BEGIN PRIOR RESEARCH SEED ---
{RESEARCH_SEED}
--- END PRIOR RESEARCH SEED ---
""".strip()


def main() -> None:
    job_config = LocalJobConfig(
        eval_program_path=str(TASK_DIR / "evaluate.py"),
        time=os.getenv("SHINKA_EVALUATION_TIMEOUT", "00:30:00"),
    )
    db_config = DatabaseConfig(
        db_path=str(Path(RESULTS_DIR) / "evolution_db.sqlite"),
        num_islands=int(os.getenv("SHINKA_NUM_ISLANDS", "4")),
        archive_size=int(os.getenv("SHINKA_ARCHIVE_SIZE", "32")),
        num_archive_inspirations=2,
        num_top_k_inspirations=2,
        migration_interval=8,
        migration_rate=0.15,
        enable_dynamic_islands=True,
        stagnation_threshold=24,
        island_spawn_strategy="best",
    )
    evo_config = EvolutionConfig(
        task_sys_msg=TASK_PROMPT,
        patch_types=["diff", "full"],
        patch_type_probs=[0.8, 0.2],
        num_generations=NUM_GENERATIONS,
        max_patch_resamples=2,
        max_patch_attempts=2,
        job_type="local",
        language="rust",
        llm_models=[
            "headless/opencode@opencode/mimo-v2.5-free?effort=high",
        ],
        llm_dynamic_selection="fixed",
        meta_rec_interval=None,
        embedding_model=None,
        init_program_path=str(TASK_DIR / "initial.rs"),
        results_dir=RESULTS_DIR,
        use_text_feedback=True,
        max_novelty_attempts=2,
    )
    runner = ShinkaEvolveRunner(
        evo_config=evo_config,
        job_config=job_config,
        db_config=db_config,
        max_evaluation_jobs=1,
        max_proposal_jobs=int(os.getenv("SHINKA_MAX_PROPOSAL_JOBS", "2")),
        max_db_workers=2,
        verbose=True,
    )
    runner.run()


if __name__ == "__main__":
    main()
