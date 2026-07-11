import os
from pathlib import Path
from unittest.mock import patch

import pytest

from evo import core
from evo.host_install import get, SUPPORTED_HOSTS
from evo.host_install import kimi as kimi_mod


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


def test_kimi_base_honors_env_var(fake_kimi_home):
    assert kimi_mod._kimi_base() == fake_kimi_home


def test_kimi_base_defaults_to_home(monkeypatch):
    monkeypatch.delenv("KIMI_CODE_HOME", raising=False)
    assert kimi_mod._kimi_base() == Path.home() / ".kimi"


def test_install_missing_kimi_binary(fake_kimi_home, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _name: None)
    from argparse import Namespace
    rc = kimi_mod.install(Namespace(from_path=None, version=None, force=False))
    assert rc == 2


def test_install_copies_plugin(fake_kimi_home, tmp_path, monkeypatch):
    # Use the real plugin root from this checkout
    here = Path(__file__).resolve().parents[2] / "plugins" / "evo"
    monkeypatch.setattr("shutil.which", lambda name: "/fake/kimi" if name == "kimi" else None)
    from argparse import Namespace
    rc = kimi_mod.install(Namespace(from_path=str(here.parent.parent), version=None, force=False))
    assert rc == 0
    assert (fake_kimi_home / "plugins" / "managed" / "evo" / ".kimi-plugin" / "plugin.json").exists()


def test_doctor_after_install(fake_kimi_home, tmp_path, monkeypatch):
    here = Path(__file__).resolve().parents[2] / "plugins" / "evo"
    monkeypatch.setattr("shutil.which", lambda name: "/fake/kimi" if name == "kimi" else None)
    from argparse import Namespace
    kimi_mod.install(Namespace(from_path=str(here.parent.parent), version=None, force=False))
    rc = kimi_mod.doctor(Namespace())
    assert rc == 0
