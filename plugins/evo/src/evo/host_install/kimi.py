"""Kimi Code CLI host install adapter.

Kimi installs a local-path plugin in two steps, and both are required:

  1. Copy the plugin root into ``<kimi-home>/plugins/managed/<id>/``.
  2. Register a record for it in ``<kimi-home>/plugins/installed.json``.

Step 2 is what actually makes the plugin exist. Kimi's plugin store builds
its record set exclusively from ``installed.json`` and never scans the
managed directory, so a plugin copied into place but left unregistered loads
nothing: no skills, no commands, no hooks. Verified against kimi-code 0.26.0.

The kimi home is ``$KIMI_CODE_HOME``, falling back to ``~/.kimi-code``.

Hooks come from the plugin manifest's ``hooks`` array, so there is no
separate hook-wiring step and no ``evo-hook-drain`` binary in front —
``evo-drain --host kimi`` resolves the run dir and session from the hook
stdin payload, the same self-contained shape Cursor uses.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

_RELEASE_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.\-+a-zA-Z0-9]*)$")

_PLUGIN_ID = "evo"

# Kimi ships as a self-contained binary under its own home; the install
# script does not necessarily put it on PATH.
_INSTALL_HINT = (
    "  curl -fsSL https://code.kimi.com/install.sh | bash\n"
    "  (or: npm install -g @moonshot-ai/kimi-code)"
)


def _kimi_base() -> Path:
    home_override = os.environ.get("KIMI_CODE_HOME")
    return Path(home_override) if home_override else Path.home() / ".kimi-code"


def _kimi_plugin_dir() -> Path:
    return _kimi_base() / "plugins" / "managed" / _PLUGIN_ID


def _installed_json_path() -> Path:
    return _kimi_base() / "plugins" / "installed.json"


def _kimi_binary() -> str | None:
    """Kimi's install.sh drops the binary in <kimi-home>/bin/ and does not
    always add it to PATH, so fall back to that before declaring it absent."""
    found = shutil.which("kimi")
    if found:
        return found
    candidate = _kimi_base() / "bin" / "kimi"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return None


def _plugin_root(from_path: str | None = None) -> Path:
    if from_path:
        p = Path(from_path).resolve()
        candidate = p / "plugins" / "evo"
        if candidate.exists():
            return candidate
        if (p / ".kimi-plugin" / "plugin.json").exists() or (p / "kimi.plugin.json").exists():
            return p
        return candidate
    # Source-checkout location: plugins/evo, four levels above this file
    # (plugins/evo/src/evo/host_install/kimi.py). Only valid when evo runs
    # from a working-tree/editable install — a wheel puts this file under
    # site-packages, where `parents[3]` is the site-packages parent, not a
    # plugin root. install() guards this with _is_valid_plugin_root and
    # falls back to the GitHub tarball for wheel installs.
    here = Path(__file__).resolve().parent.parent.parent.parent  # plugins/evo
    return here


def _is_valid_plugin_root(path: Path) -> bool:
    """A directory is a usable plugin root only if it actually carries the
    Kimi manifest. Guards against `_plugin_root` resolving to an unrelated
    directory that merely exists (the site-packages parent on a wheel)."""
    return (path / ".kimi-plugin" / "plugin.json").exists()


def _github_tarball_url(version: str) -> str:
    ref = f"v{version}" if _RELEASE_VERSION_RE.match(version) else version
    if _RELEASE_VERSION_RE.match(version):
        return f"https://github.com/evo-hq/evo/archive/refs/tags/{ref}.tar.gz"
    return f"https://github.com/evo-hq/evo/archive/refs/heads/{ref}.tar.gz"


def _find_extracted_plugin_root(extracted: Path) -> Path | None:
    """Locate the evo plugin root inside an extracted GitHub archive."""
    direct = extracted / "plugins" / "evo"
    if (direct / ".kimi-plugin" / "plugin.json").exists():
        return direct
    for child in extracted.iterdir():
        if child.is_dir():
            candidate = child / "plugins" / "evo"
            if (candidate / ".kimi-plugin" / "plugin.json").exists():
                return candidate
    return None


def _copy_plugin_root(src: Path, dst: Path) -> None:
    """Copy the plugin root to the Kimi managed plugin directory."""
    if dst.exists():
        print(f"removing previous install at {dst}")
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"copying {src} -> {dst}")
    shutil.copytree(
        src, dst,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", "build", "dist",
            ".pytest_cache", "*.egg-info", "node_modules",
        ),
    )


def _read_installed() -> dict:
    """Read Kimi's plugin registry. Mirrors Kimi's own reader: a missing
    file is an empty registry, but a corrupt one is an error we refuse to
    clobber (Kimi would fail to load every plugin, not just evo)."""
    path = _installed_json_path()
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {"version": 1, "plugins": []}
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise ValueError(f"{path} is not a valid installed.json object")
    return data


def _write_installed(data: dict) -> None:
    """Write via tmp+rename, matching Kimi's own writeInstalled so a
    concurrent read never sees a half-written registry."""
    path = _installed_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _register(managed_root: Path, original_source: Path) -> None:
    """Upsert evo's record in installed.json, preserving other plugins and
    evo's original installedAt across re-installs."""
    data = _read_installed()
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    plugins = [p for p in data["plugins"] if not (isinstance(p, dict) and p.get("id") == _PLUGIN_ID)]
    previous = next(
        (p for p in data["plugins"] if isinstance(p, dict) and p.get("id") == _PLUGIN_ID),
        {},
    )
    plugins.append({
        "id": _PLUGIN_ID,
        "root": str(managed_root.resolve()),
        "source": "local-path",
        "originalSource": str(original_source.resolve()),
        "enabled": True,
        "installedAt": previous.get("installedAt", now),
        "updatedAt": now,
    })
    data["plugins"] = plugins
    data["version"] = data.get("version", 1)
    _write_installed(data)
    print(f"registered '{_PLUGIN_ID}' in {_installed_json_path()}")


def _deregister() -> None:
    try:
        data = _read_installed()
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return
    before = len(data["plugins"])
    data["plugins"] = [
        p for p in data["plugins"]
        if not (isinstance(p, dict) and p.get("id") == _PLUGIN_ID)
    ]
    if len(data["plugins"]) != before:
        _write_installed(data)
        print(f"deregistered '{_PLUGIN_ID}' from {_installed_json_path()}")


def _install_plugin(src: Path) -> int:
    dst = _kimi_plugin_dir()
    _copy_plugin_root(src, dst)
    try:
        _register(dst, src)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not register the plugin with Kimi: {exc}", file=sys.stderr)
        return 2
    print(
        "\n✓ evo installed for kimi.\n"
        "  Start a new Kimi session (or run /plugins reload) to load the plugin."
    )
    return 0


def _install_from_github(version: str) -> int:
    """Download the evo plugin source from GitHub and install it for Kimi."""
    url = _github_tarball_url(version)
    print(f"downloading {url}")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            tarball_bytes = response.read()
    except urllib.error.URLError as exc:
        print(f"ERROR: could not download {url}: {exc}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory() as tmp:
        tarball_path = Path(tmp) / "evo.tar.gz"
        tarball_path.write_bytes(tarball_bytes)
        extract_dir = Path(tmp) / "extracted"
        extract_dir.mkdir()
        with tarfile.open(tarball_path, "r:gz") as tar:
            # `filter` was added in Python 3.12; keep compatibility with 3.10/3.11.
            extract_kwargs = {"filter": "data"} if sys.version_info >= (3, 12) else {}
            tar.extractall(path=extract_dir, **extract_kwargs)

        src = _find_extracted_plugin_root(extract_dir)
        if src is None:
            print(
                "ERROR: downloaded archive does not contain a valid evo plugin root "
                "(expected .../plugins/evo/.kimi-plugin/plugin.json)",
                file=sys.stderr,
            )
            return 2

        return _install_plugin(src)


def install(args: argparse.Namespace) -> int:
    if _kimi_binary() is None:
        print(
            "ERROR: `kimi` binary not found. Install Kimi Code CLI first:\n"
            f"{_INSTALL_HINT}",
            file=sys.stderr,
        )
        return 2

    version = getattr(args, "version", None)
    from_path = getattr(args, "from_path", None)

    if version:
        return _install_from_github(version)

    if from_path:
        src = _plugin_root(from_path)
        if not _is_valid_plugin_root(src):
            print(
                f"ERROR: no evo plugin root (.kimi-plugin/plugin.json) at {src}",
                file=sys.stderr,
            )
            return 2
        return _install_plugin(src)

    # Bare `evo install kimi`. The plugin files sit next to the CLI only in a
    # source/editable checkout; the published wheel ships none of them, and
    # `_plugin_root(None)` would resolve to the tool's site-packages parent.
    # Use the local tree when it's genuinely a checkout, otherwise fetch the
    # GitHub tarball at the running version — the same bare-case behaviour as
    # the codex, cursor, and hermes adapters.
    src = _plugin_root(None)
    if _is_valid_plugin_root(src):
        return _install_plugin(src)

    from evo import __version__
    return _install_from_github(__version__)


def uninstall(args: argparse.Namespace) -> int:
    _deregister()
    dst = _kimi_plugin_dir()
    if dst.exists():
        shutil.rmtree(dst)
        print(f"removed {dst}")
    else:
        print("evo plugin not installed for kimi")
    return 0


def doctor(args: argparse.Namespace) -> int:
    binary = _kimi_binary()
    if binary is None:
        print("✗ `kimi` binary not found")
        print(f"  Install:\n{_INSTALL_HINT}")
        return 1
    print(f"✓ kimi binary: {binary}")

    dst = _kimi_plugin_dir()
    manifest = dst / ".kimi-plugin" / "plugin.json"
    if not manifest.exists():
        manifest = dst / "kimi.plugin.json"
    if not manifest.exists():
        print(f"✗ evo plugin not found at {dst}")
        print("  Run: evo install kimi")
        return 1
    print(f"✓ evo plugin manifest at {manifest}")

    try:
        data = json.loads(manifest.read_text())
    except json.JSONDecodeError as exc:
        print(f"✗ could not parse manifest: {exc}")
        return 1
    if data.get("name") != _PLUGIN_ID:
        print(f"✗ manifest name mismatch: {data.get('name')!r}")
        return 1
    print(f"✓ manifest name is '{_PLUGIN_ID}'")

    # The manifest on disk is inert until Kimi has a record for it. Without
    # this check doctor passes on a plugin Kimi cannot see.
    try:
        installed = _read_installed()
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"✗ could not read {_installed_json_path()}: {exc}")
        return 1
    record = next(
        (p for p in installed["plugins"] if isinstance(p, dict) and p.get("id") == _PLUGIN_ID),
        None,
    )
    if record is None:
        print(f"✗ evo not registered in {_installed_json_path()}")
        print("  Kimi loads plugins from that file only — run: evo install kimi")
        return 1
    if not record.get("enabled", False):
        print("✗ evo is registered but disabled")
        print("  Enable it from Kimi: /plugins")
        return 1
    if Path(record.get("root", "")).resolve() != dst.resolve():
        print(f"✗ registered root {record.get('root')!r} does not match {dst}")
        print("  Run: evo install kimi")
        return 1
    print(f"✓ evo registered and enabled in {_installed_json_path()}")
    return 0
