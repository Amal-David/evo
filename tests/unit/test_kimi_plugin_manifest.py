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
