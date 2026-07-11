from evo import core
from evo.host_install import get, SUPPORTED_HOSTS


def test_kimi_is_supported():
    assert "kimi" in SUPPORTED_HOSTS
    assert "kimi" in core.SUPPORTED_HOSTS


def test_kimi_adapter_registered():
    module = get("kimi")
    assert hasattr(module, "install")
    assert hasattr(module, "uninstall")
    assert hasattr(module, "doctor")
