"""Bootstrap helper for Kimi plugin tools: locate the evo source tree."""

from __future__ import annotations

import sys
from pathlib import Path


def _find_evo_src(start: Path) -> Path | None:
    """Search upward from ``start`` for a directory containing
    ``src/evo/__init__.py``.

    Works both in the development repo (``repo/plugins/evo/kimi_tools``)
    and in Kimi's managed plugin directory
    (``KIMI_CODE_HOME/plugins/managed/evo/kimi_tools``), where the
    relative depth to the repo root differs.
    """
    for parent in [start, *start.parents]:
        src = parent / "src"
        if (src / "evo" / "__init__.py").exists():
            return src
    return None


def add_evo_src_to_path() -> None:
    """Insert the evo package ``src`` directory into ``sys.path``."""
    here = Path(__file__).resolve().parent
    src = _find_evo_src(here)
    if src is None:
        sys.stderr.write("ERROR: evo source tree not found\n")
        sys.exit(2)
    sys.path.insert(0, str(src))
