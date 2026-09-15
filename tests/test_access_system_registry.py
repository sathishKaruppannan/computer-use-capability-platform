import json

import pytest

from capability_platform.access.system_registry import JSONSystemRegistry, SystemNotRegisteredError


def _write_registry(path, systems):
    path.write_text(json.dumps({"systems": systems}), encoding="utf-8")


def test_resolve_known_system_identifier(tmp_path):
    path = tmp_path / "system_registry.json"
    _write_registry(
        path,
        [
            {
                "systemIdentifier": "legacy-member-servicing-demo",
                "baseUrl": "http://127.0.0.1:8001",
                "vendor": "Interface Demo",
                "product": "Legacy Member Servicing",
            }
        ],
    )
    registry = JSONSystemRegistry(path)

    entry = registry.resolve("legacy-member-servicing-demo")
    assert entry.base_url == "http://127.0.0.1:8001"
    assert entry.vendor == "Interface Demo"


def test_resolve_unknown_system_identifier_raises(tmp_path):
    path = tmp_path / "system_registry.json"
    _write_registry(path, [])
    registry = JSONSystemRegistry(path)

    with pytest.raises(SystemNotRegisteredError):
        registry.resolve("does-not-exist")


def test_missing_registry_file_is_an_empty_registry(tmp_path):
    registry = JSONSystemRegistry(tmp_path / "does-not-exist.json")
    assert registry.list() == []


def test_list_returns_every_registered_system(tmp_path):
    path = tmp_path / "system_registry.json"
    _write_registry(
        path,
        [
            {
                "systemIdentifier": "system-a",
                "baseUrl": "http://a.example",
                "vendor": "A",
                "product": "A",
            },
            {
                "systemIdentifier": "system-b",
                "baseUrl": "http://b.example",
                "vendor": "B",
                "product": "B",
            },
        ],
    )
    registry = JSONSystemRegistry(path)
    identifiers = {entry.system_identifier for entry in registry.list()}
    assert identifiers == {"system-a", "system-b"}
