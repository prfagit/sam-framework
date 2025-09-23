import json
import sys
import hashlib
from importlib.metadata import EntryPoints

import pytest

from sam.core.plugins import load_plugins
from sam.core.tools import ToolRegistry
from sam.commands.plugins import trust_plugin
from sam.config.plugin_policy import load_allowlist_document


PLUGIN_SOURCE = """
REGISTER_CALLS = []

def register(registry, agent=None):
    registry._test_markers.append("registered")
    REGISTER_CALLS.append(True)
"""


def _write_plugin(tmp_path, name="test_plugin"):
    module_path = tmp_path / f"{name}.py"
    module_path.write_text(PLUGIN_SOURCE)
    return module_path, name


def _blank_allowlist(tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(json.dumps({"modules": {}, "entry_points": {}}))
    return allowlist


def _patch_entry_points(monkeypatch):
    def _empty_entry_points(*, group=None):
        return EntryPoints([])

    monkeypatch.setattr("importlib.metadata.entry_points", _empty_entry_points)


@pytest.fixture(autouse=True)
def _restore_policy_env(monkeypatch):
    monkeypatch.delenv("SAM_ENABLE_PLUGINS", raising=False)
    monkeypatch.delenv("SAM_PLUGIN_ALLOW_UNVERIFIED", raising=False)
    monkeypatch.delenv("SAM_PLUGIN_ALLOWLIST_FILE", raising=False)
    monkeypatch.delenv("SAM_PLUGINS", raising=False)
    yield


def test_plugins_disabled_by_default(tmp_path, monkeypatch):
    _patch_entry_points(monkeypatch)
    _, module_name = _write_plugin(tmp_path)
    allowlist = _blank_allowlist(tmp_path)

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SAM_PLUGINS", module_name)
    monkeypatch.setenv("SAM_PLUGIN_ALLOWLIST_FILE", str(allowlist))

    registry = ToolRegistry()
    registry._test_markers = []

    load_plugins(registry, agent=None)

    assert registry._test_markers == []
    # plugin module should not be imported when disabled
    assert module_name not in sys.modules


def test_plugins_require_allowlist(tmp_path, monkeypatch):
    _patch_entry_points(monkeypatch)
    _, module_name = _write_plugin(tmp_path)
    allowlist = _blank_allowlist(tmp_path)

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SAM_PLUGINS", module_name)
    monkeypatch.setenv("SAM_PLUGIN_ALLOWLIST_FILE", str(allowlist))
    monkeypatch.setenv("SAM_ENABLE_PLUGINS", "true")

    registry = ToolRegistry()
    registry._test_markers = []

    load_plugins(registry, agent=None)

    assert registry._test_markers == []


def test_plugins_load_when_allowlisted(tmp_path, monkeypatch):
    _patch_entry_points(monkeypatch)
    plugin_file, module_name = _write_plugin(tmp_path)
    digest = hashlib.sha256(plugin_file.read_bytes()).hexdigest()

    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "modules": {
                    module_name: {"sha256": digest}
                },
                "entry_points": {}
            }
        )
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SAM_PLUGINS", module_name)
    monkeypatch.setenv("SAM_PLUGIN_ALLOWLIST_FILE", str(allowlist))
    monkeypatch.setenv("SAM_ENABLE_PLUGINS", "true")

    registry = ToolRegistry()
    registry._test_markers = []

    load_plugins(registry, agent=None)

    assert registry._test_markers == ["registered"]


def test_plugins_digest_mismatch_blocks(tmp_path, monkeypatch):
    _patch_entry_points(monkeypatch)
    plugin_file, module_name = _write_plugin(tmp_path)

    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        json.dumps(
            {
                "modules": {
                    module_name: {"sha256": "deadbeef"}
                },
                "entry_points": {}
            }
        )
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SAM_PLUGINS", module_name)
    monkeypatch.setenv("SAM_PLUGIN_ALLOWLIST_FILE", str(allowlist))
    monkeypatch.setenv("SAM_ENABLE_PLUGINS", "true")

    registry = ToolRegistry()
    registry._test_markers = []

    load_plugins(registry, agent=None)

    assert registry._test_markers == []


def test_trust_command_updates_allowlist(tmp_path, monkeypatch):
    _patch_entry_points(monkeypatch)
    plugin_file, module_name = _write_plugin(tmp_path, name="trusted_plugin")
    digest = hashlib.sha256(plugin_file.read_bytes()).hexdigest()

    allowlist = tmp_path / "allowlist.json"

    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("SAM_PLUGIN_ALLOWLIST_FILE", str(allowlist))
    monkeypatch.setenv("SAM_ENABLE_PLUGINS", "true")

    rc = trust_plugin(module_name, entry_point="trusted", label="Trusted")

    assert rc == 0

    doc = load_allowlist_document(allowlist)
    assert doc["modules"][module_name]["sha256"] == digest
    assert doc["entry_points"]["trusted"]["module"] == module_name
