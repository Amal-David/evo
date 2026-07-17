import io
import json
import tarfile
from argparse import Namespace
from pathlib import Path

import pytest

from evo import core
from evo.host_install import get, SUPPORTED_HOSTS
from evo.host_install import kimi as kimi_mod

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_kimi_is_supported():
    assert "kimi" in SUPPORTED_HOSTS
    assert "kimi" in core.SUPPORTED_HOSTS


def test_kimi_adapter_registered():
    module = get("kimi")
    assert hasattr(module, "install")
    assert hasattr(module, "uninstall")
    assert hasattr(module, "doctor")


@pytest.fixture
def fake_kimi_home(tmp_path, monkeypatch):
    home = tmp_path / "kimi-home"
    home.mkdir()
    monkeypatch.setenv("KIMI_CODE_HOME", str(home))
    return home


@pytest.fixture
def kimi_on_path(monkeypatch):
    monkeypatch.setattr(
        "shutil.which", lambda name: "/fake/kimi" if name == "kimi" else None
    )


def _install_from_checkout() -> int:
    return kimi_mod.install(
        Namespace(from_path=str(REPO_ROOT), version=None, force=False)
    )


def _installed_records(home: Path) -> list[dict]:
    return json.loads((home / "plugins" / "installed.json").read_text())["plugins"]


def test_kimi_base_honors_env_var(fake_kimi_home):
    assert kimi_mod._kimi_base() == fake_kimi_home


def test_kimi_base_defaults_to_kimi_code_home(monkeypatch):
    """kimi-code resolves its data dir as KIMI_CODE_HOME ?? ~/.kimi-code.
    Defaulting anywhere else installs into a directory kimi never reads."""
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    assert kimi_mod._kimi_base() == Path.home() / ".kimi-code"


def test_install_missing_kimi_binary(fake_kimi_home, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    rc = kimi_mod.install(Namespace(from_path=None, version=None, force=False))
    assert rc == 2


def test_kimi_binary_found_under_kimi_home_when_not_on_path(fake_kimi_home, monkeypatch):
    """install.sh drops the binary in <kimi-home>/bin without touching PATH."""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    binary = fake_kimi_home / "bin" / "kimi"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    assert kimi_mod._kimi_binary() == str(binary)


def test_install_copies_plugin(fake_kimi_home, kimi_on_path):
    assert _install_from_checkout() == 0
    manifest = fake_kimi_home / "plugins" / "managed" / "evo" / ".kimi-plugin" / "plugin.json"
    assert manifest.exists()


def test_install_registers_plugin_in_installed_json(fake_kimi_home, kimi_on_path):
    """Kimi builds its plugin records from installed.json alone and never
    scans the managed dir, so an unregistered copy loads nothing."""
    assert _install_from_checkout() == 0
    records = _installed_records(fake_kimi_home)
    evo = next(r for r in records if r["id"] == "evo")
    assert evo["enabled"] is True
    assert evo["source"] == "local-path"
    assert Path(evo["root"]) == (fake_kimi_home / "plugins" / "managed" / "evo").resolve()


def test_install_preserves_other_plugins(fake_kimi_home, kimi_on_path):
    registry = fake_kimi_home / "plugins" / "installed.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({
        "version": 1,
        "plugins": [{"id": "other", "root": "/somewhere", "enabled": True}],
    }))
    assert _install_from_checkout() == 0
    ids = {r["id"] for r in _installed_records(fake_kimi_home)}
    assert ids == {"other", "evo"}


def test_reinstall_does_not_duplicate_the_record(fake_kimi_home, kimi_on_path):
    assert _install_from_checkout() == 0
    first = _installed_records(fake_kimi_home)[0]["installedAt"]
    assert _install_from_checkout() == 0
    records = [r for r in _installed_records(fake_kimi_home) if r["id"] == "evo"]
    assert len(records) == 1
    assert records[0]["installedAt"] == first


def test_install_refuses_to_clobber_a_corrupt_registry(fake_kimi_home, kimi_on_path):
    registry = fake_kimi_home / "plugins" / "installed.json"
    registry.parent.mkdir(parents=True)
    registry.write_text("{not json")
    assert kimi_mod.install(
        Namespace(from_path=str(REPO_ROOT), version=None, force=False)
    ) == 2
    assert registry.read_text() == "{not json"


def test_doctor_after_install(fake_kimi_home, kimi_on_path):
    assert _install_from_checkout() == 0
    assert kimi_mod.doctor(Namespace()) == 0


def test_doctor_fails_when_plugin_copied_but_not_registered(fake_kimi_home, kimi_on_path):
    """The regression that shipped: files on disk, invisible to Kimi."""
    assert _install_from_checkout() == 0
    (fake_kimi_home / "plugins" / "installed.json").unlink()
    assert kimi_mod.doctor(Namespace()) == 1


def test_doctor_fails_when_plugin_disabled(fake_kimi_home, kimi_on_path):
    assert _install_from_checkout() == 0
    registry = fake_kimi_home / "plugins" / "installed.json"
    data = json.loads(registry.read_text())
    for record in data["plugins"]:
        record["enabled"] = False
    registry.write_text(json.dumps(data))
    assert kimi_mod.doctor(Namespace()) == 1


def test_uninstall_removes_and_deregisters(fake_kimi_home, kimi_on_path):
    assert _install_from_checkout() == 0
    assert kimi_mod.uninstall(Namespace()) == 0
    assert not (fake_kimi_home / "plugins" / "managed" / "evo").exists()
    assert _installed_records(fake_kimi_home) == []


def _build_fake_tarball(version: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        root = f"evo-{version}"
        manifest_content = b'{"name":"evo","version":"0.7.0"}'
        info = tarfile.TarInfo(name=f"{root}/plugins/evo/.kimi-plugin/plugin.json")
        info.size = len(manifest_content)
        tar.addfile(info, io.BytesIO(manifest_content))
    return buf.getvalue()


def test_install_version_downloads_and_registers_plugin(fake_kimi_home, kimi_on_path, monkeypatch):
    tarball = _build_fake_tarball("0.7.0")
    monkeypatch.setattr("urllib.request.urlopen", lambda url, **kwargs: io.BytesIO(tarball))
    rc = kimi_mod.install(Namespace(from_path=None, version="0.7.0", force=False))
    assert rc == 0
    assert (fake_kimi_home / "plugins" / "managed" / "evo" / ".kimi-plugin" / "plugin.json").exists()
    assert any(r["id"] == "evo" for r in _installed_records(fake_kimi_home))


def test_bare_install_on_wheel_falls_back_to_github(fake_kimi_home, kimi_on_path, monkeypatch):
    """Regression: on a `uv tool install evo-hq-cli` wheel the plugin files
    do not sit next to the CLI, so a bare install must fetch the GitHub
    tarball at the running version rather than copy the site-packages parent."""
    wheel_like = fake_kimi_home / "not-a-plugin-root"
    wheel_like.mkdir()
    monkeypatch.setattr(kimi_mod, "_plugin_root", lambda from_path=None: wheel_like)
    calls = []
    monkeypatch.setattr(kimi_mod, "_install_from_github", lambda v: calls.append(v) or 0)

    import evo
    rc = kimi_mod.install(Namespace(from_path=None, version=None, force=False))
    assert rc == 0
    assert calls == [evo.__version__], "bare wheel install should fetch the running version"


def test_bare_install_on_checkout_uses_local_tree(fake_kimi_home, kimi_on_path, monkeypatch):
    """From a real checkout the bare install copies the local tree and never
    hits the network."""
    monkeypatch.setattr(
        kimi_mod, "_install_from_github",
        lambda v: (_ for _ in ()).throw(AssertionError("must not download from a checkout")),
    )
    rc = kimi_mod.install(Namespace(from_path=None, version=None, force=False))
    assert rc == 0
    assert (fake_kimi_home / "plugins" / "managed" / "evo" / ".kimi-plugin" / "plugin.json").exists()


def test_install_from_invalid_path_is_rejected(fake_kimi_home, kimi_on_path, tmp_path):
    """A --from-path with no plugin root fails loudly instead of copying junk."""
    empty = tmp_path / "empty"
    empty.mkdir()
    rc = kimi_mod.install(Namespace(from_path=str(empty), version=None, force=False))
    assert rc == 2
    assert not (fake_kimi_home / "plugins" / "managed" / "evo").exists()
