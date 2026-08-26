from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "deploy" / "render" / "shinka-flock" / "opencode-guard.sh"


def test_wrapper_preserves_headless_high_for_mimo(tmp_path: Path) -> None:
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
            "opencode/mimo-v2.5-free",
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
        "opencode/mimo-v2.5-free",
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
            "opencode/mimo-v2.5-free",
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
