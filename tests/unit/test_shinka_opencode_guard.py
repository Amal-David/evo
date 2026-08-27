from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy" / "render" / "shinka-flock" / "opencode-guard.sh"
ENTRYPOINT = ROOT / "deploy" / "render" / "shinka-flock" / "entrypoint.sh"
RUNNER = ROOT / "deploy" / "render" / "shinka-flock" / "run_evo.py"


def test_entrypoint_isolates_free_model_from_stale_zen_credentials() -> None:
    entrypoint = ENTRYPOINT.read_text(encoding="utf-8")

    assert 'readonly runtime_data_home="$runtime_home/.local/share-shinka-free"' in entrypoint
    assert 'XDG_DATA_HOME="$runtime_data_home"' in entrypoint
    assert 'OPENCODE_DATA_HOME="$runtime_data_home/opencode"' in entrypoint
    assert 'XDG_DATA_HOME="$runtime_home/.local/share"' not in entrypoint
    assert 'SHINKA_HEADLESS_TIMEOUT="${SHINKA_HEADLESS_TIMEOUT:-300}"' in entrypoint


def test_runner_uses_weighted_smoke_tested_free_pool() -> None:
    runner = RUNNER.read_text(encoding="utf-8")

    assert (
        "headless/opencode@opencode/muse-spark-1.2-contributor-free?effort=high"
        in runner
    )
    assert "headless/opencode@opencode/hy3-free?effort=high" in runner
    assert 'llm_dynamic_selection="fixed"' in runner
    assert 'llm_dynamic_selection_kwargs={"prior_probs": [0.65, 0.35]}' in runner
    assert "opencode/mimo-v2.5-free" not in runner


@pytest.mark.parametrize(
    "model",
    [
        "opencode/muse-spark-1.2-contributor-free",
        "opencode/hy3-free",
    ],
)
def test_wrapper_preserves_headless_high_for_free_pool(
    tmp_path: Path, model: str
) -> None:
    # The Docker build owns these paths. Local CI verifies the same guard by
    # substituting the literal executable and state directory in a temp copy.
    script = WRAPPER.read_text(encoding="utf-8").replace(
        "readonly real_opencode=/usr/local/bin/opencode",
        f"readonly real_opencode={tmp_path / 'real-opencode'}",
    ).replace(
        "readonly state_dir=/data/state",
        f"readonly state_dir={tmp_path / 'state'}",
    )
    local_wrapper = tmp_path / "opencode"
    local_wrapper.write_text(script, encoding="utf-8")
    local_wrapper.chmod(0o755)

    real = tmp_path / "real-opencode"
    real.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n", encoding="utf-8")
    real.chmod(0o755)
    completed = subprocess.run(
        [
            str(local_wrapper),
            "run",
            "--format",
            "json",
            "--model",
            model,
            "--variant",
            "high",
            "prompt",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout.splitlines() == [
        "run",
        "--format",
        "json",
        "--model",
        model,
        "--variant",
        "high",
        "prompt",
    ]


def test_wrapper_rejects_unsupported_variant(tmp_path: Path) -> None:
    script = WRAPPER.read_text(encoding="utf-8").replace(
        "readonly real_opencode=/usr/local/bin/opencode",
        f"readonly real_opencode={tmp_path / 'real-opencode'}",
    ).replace(
        "readonly state_dir=/data/state",
        f"readonly state_dir={tmp_path / 'state'}",
    )
    local_wrapper = tmp_path / "opencode"
    local_wrapper.write_text(script, encoding="utf-8")
    local_wrapper.chmod(0o755)
    real = tmp_path / "real-opencode"
    real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real.chmod(0o755)

    completed = subprocess.run(
        [
            str(local_wrapper),
            "run",
            "--model",
            "opencode/muse-spark-1.2-contributor-free",
            "--variant",
            "max",
            "prompt",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "unexpected variant" in completed.stderr


def test_wrapper_rejects_model_outside_free_pool(tmp_path: Path) -> None:
    script = WRAPPER.read_text(encoding="utf-8").replace(
        "readonly real_opencode=/usr/local/bin/opencode",
        f"readonly real_opencode={tmp_path / 'real-opencode'}",
    ).replace(
        "readonly state_dir=/data/state",
        f"readonly state_dir={tmp_path / 'state'}",
    )
    local_wrapper = tmp_path / "opencode"
    local_wrapper.write_text(script, encoding="utf-8")
    local_wrapper.chmod(0o755)
    real = tmp_path / "real-opencode"
    real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    real.chmod(0o755)

    completed = subprocess.run(
        [
            str(local_wrapper),
            "run",
            "--model",
            "opencode/nemotron-3-ultra-free",
            "--variant",
            "high",
            "prompt",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert "unexpected model" in completed.stderr
