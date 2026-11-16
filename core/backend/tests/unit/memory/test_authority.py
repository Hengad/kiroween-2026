import pytest

from siloless.memory.authority import is_authoritative


def _check(**overrides: object) -> bool:
    values: dict[str, object] = {
        "source_id": "wiki",
        "kind": "procedure",
        "is_current": True,
        "authoritative_sources": ["wiki"],
        "authoritative_kinds": [],
    }
    values.update(overrides)
    return is_authoritative(**values)  # type: ignore[arg-type]


def test_a_current_version_from_an_authoritative_source_is_authoritative() -> None:
    assert _check()


def test_a_current_version_of_an_authoritative_kind_is_authoritative() -> None:
    assert _check(source_id="chat", authoritative_sources=[], authoritative_kinds=["procedure"])


def test_a_superseded_version_is_never_authoritative() -> None:
    assert not _check(is_current=False)


def test_a_record_from_another_source_and_kind_is_not_authoritative() -> None:
    assert not _check(source_id="chat", kind="message")


@pytest.mark.parametrize("is_current", [True, False])
def test_nothing_is_authoritative_when_nothing_is_configured(is_current: bool) -> None:
    assert not _check(is_current=is_current, authoritative_sources=[], authoritative_kinds=[])
