import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST = REPO_ROOT / "plugins" / "evo" / ".kimi-plugin" / "plugin.json"


def test_manifest_exists_and_is_valid_json():
    assert MANIFEST.exists(), f"manifest not found at {MANIFEST}"
    data = json.loads(MANIFEST.read_text())
    assert data["name"] == "evo"
    assert "version" in data
    assert "skills" in data
    assert "commands" in data
    assert "hooks" in data


COMMANDS_DIR = REPO_ROOT / "plugins" / "evo" / "commands"


def test_discover_command_file_exists():
    assert (COMMANDS_DIR / "discover.md").exists()


def test_optimize_command_file_exists():
    assert (COMMANDS_DIR / "optimize.md").exists()


def test_manifest_declares_tools():
    data = json.loads(MANIFEST.read_text())
    tools = data.get("tools", [])
    names = {t["name"] for t in tools}
    assert "evo_spawn_subagent" in names
    assert "evo_wait_subagent" in names
