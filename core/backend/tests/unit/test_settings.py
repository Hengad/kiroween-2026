from typing import Any

import pytest

from siloless.settings import BUILTIN_RELATION_TYPES, Settings


def make_settings(**values: Any) -> Settings:
    """Build Settings without reading a developer's local .env file."""
    return Settings(_env_file=None, **values)


def test_defaults_match_the_design() -> None:
    settings = make_settings()

    assert settings.database_url == "sqlite:///siloless.db"
    assert settings.max_record_bytes == 262144
    assert settings.max_query_length == 256
    assert settings.authoritative_sources == []
    assert settings.authoritative_kinds == []
    assert settings.entity_types == []


def test_builtin_relation_types_are_registered_by_default() -> None:
    settings = make_settings()

    assert set(BUILTIN_RELATION_TYPES) <= set(settings.relation_types)
    assert "supersedes" in settings.relation_types


def test_configured_relation_types_are_added_to_the_builtin_ones() -> None:
    settings = make_settings(relation_types=["feeds"])

    assert "feeds" in settings.relation_types
    assert set(BUILTIN_RELATION_TYPES) <= set(settings.relation_types)


def test_settings_are_read_from_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SILOLESS_DATABASE_URL", "sqlite:///other.db")
    monkeypatch.setenv("SILOLESS_MAX_QUERY_LENGTH", "64")
    monkeypatch.setenv("SILOLESS_AUTHORITATIVE_KINDS", '["procedure", "policy"]')

    settings = make_settings()

    assert settings.database_url == "sqlite:///other.db"
    assert settings.max_query_length == 64
    assert settings.authoritative_kinds == ["procedure", "policy"]
