from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
PATCH_PATH = (
    ROOT / "deploy" / "render" / "shinka-flock" / "patch_headless.py"
)
SPEC = importlib.util.spec_from_file_location("shinka_headless_patch", PATCH_PATH)
assert SPEC is not None and SPEC.loader is not None
PATCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PATCHER)


def upstream_fixture() -> str:
    return f'''function buildOpencode(options) {{
    const args = ["run", "--format", "json"];
{PATCHER.OPENCODE_BUILD_OLD}

export const agentHarnesses = {{
{PATCHER.OPENCODE_MODE_OLD}
        configRelDir: ".config/opencode",
    }},
}};
'''


def test_patch_streams_opencode_prompt_files_over_stdin() -> None:
    patched = PATCHER.patch_source(upstream_fixture())

    assert PATCHER.OPENCODE_BUILD_NEW in patched
    assert PATCHER.OPENCODE_MODE_NEW in patched
    assert 'stdinFile: options.promptFile' in patched
    assert PATCHER.OPENCODE_BUILD_OLD not in patched
    assert PATCHER.OPENCODE_MODE_OLD not in patched


def test_patch_fails_closed_when_pinned_headless_layout_changes() -> None:
    with pytest.raises(ValueError, match="OpenCode command builder"):
        PATCHER.patch_source("unexpected upstream source")
