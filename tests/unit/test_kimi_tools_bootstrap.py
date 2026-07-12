import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "evo" / "kimi_tools"))

from _bootstrap import _find_evo_src


def test_find_evo_src_in_dev_repo_layout():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        src = tmp / "plugins" / "evo" / "src"
        (src / "evo").mkdir(parents=True)
        (src / "evo" / "__init__.py").write_text("")
        here = tmp / "plugins" / "evo" / "kimi_tools"
        here.mkdir(parents=True)
        assert _find_evo_src(here) == src


def test_find_evo_src_in_installed_plugin_layout():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Simulates KIMI_CODE_HOME/plugins/managed/evo/kimi_tools
        plugin_root = tmp / "plugins" / "managed" / "evo"
        src = plugin_root / "src"
        (src / "evo").mkdir(parents=True)
        (src / "evo" / "__init__.py").write_text("")
        here = plugin_root / "kimi_tools"
        here.mkdir(parents=True)
        assert _find_evo_src(here) == src


def test_find_evo_src_missing_returns_none():
    with tempfile.TemporaryDirectory() as tmp:
        assert _find_evo_src(Path(tmp)) is None
