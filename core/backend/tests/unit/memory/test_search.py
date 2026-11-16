from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from siloless.memory.search import SearchQuery
from tests.helpers import Services, build_services


@pytest.fixture
def svc() -> Services:
    return build_services(authoritative_sources=["wiki"], max_query_length=60)


def make_record(**overrides: Any) -> NewRecord:
    base = NewRecord(
        source_id="wiki",
        external_id="doc",
        kind="procedure",
        title="Document",
        content="Some text.",
        metadata={},
        acl=Acl.of("group:everyone"),
        occurred_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
    )
    return replace(base, **overrides)


def titles(hits: list[Any]) -> list[str]:
    return [hit.title for hit in hits]


def test_a_search_matches_title_and_content(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    svc.ingestor.ingest(make_record(external_id="a", title="Hydraulic seal", content="Unrelated."))
    svc.ingestor.ingest(
        make_record(external_id="b", title="Other", content="Check the hydraulic line.")
    )
    svc.ingestor.ingest(make_record(external_id="c", title="Fire drill", content="Assembly point."))

    hits = svc.search.search(anna, SearchQuery("hydraulic"))

    assert sorted(titles(hits)) == ["Hydraulic seal", "Other"]


def test_a_hit_carries_ids_passage_source_and_authority(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    result = svc.ingestor.ingest(
        make_record(title="Seal", content="Replace the hydraulic seal every 500 hours.")
    )

    (hit,) = svc.search.search(anna, SearchQuery("hydraulic"))

    assert hit.record_id == result.record_id
    assert hit.version_id == result.version_id
    assert hit.version == 1
    assert hit.source_id == "wiki"
    assert hit.kind == "procedure"
    assert "hydraulic" in hit.passage
    assert hit.is_authoritative


def test_results_are_ranked_by_relevance(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    svc.ingestor.ingest(
        make_record(external_id="weak", title="Notes", content="One mention of seal here.")
    )
    svc.ingestor.ingest(
        make_record(external_id="strong", title="Seal seal seal", content="Seal seal seal seal.")
    )

    hits = svc.search.search(anna, SearchQuery("seal"))

    assert titles(hits) == ["Seal seal seal", "Notes"]


def test_only_the_current_version_can_be_found(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    svc.ingestor.ingest(make_record(content="Replace the old gasket."))
    svc.ingestor.ingest(make_record(content="Replace the new gasket."))

    assert svc.search.search(anna, SearchQuery("old")) == []
    (hit,) = svc.search.search(anna, SearchQuery("gasket"))
    assert hit.version == 2


def test_filters_narrow_by_source_kind_and_time(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    svc.ingestor.ingest(
        make_record(external_id="a", title="A seal", source_id="wiki", kind="procedure")
    )
    svc.ingestor.ingest(
        make_record(
            external_id="b",
            title="B seal",
            source_id="chat",
            kind="message",
            occurred_at=datetime(2026, 11, 10, tzinfo=UTC),
        )
    )

    def search(**kwargs: Any) -> list[str]:
        return titles(svc.search.search(anna, SearchQuery("seal", **kwargs)))

    assert sorted(search()) == ["A seal", "B seal"]
    assert search(source_id="chat") == ["B seal"]
    assert search(kind="procedure") == ["A seal"]
    assert search(occurred_from=datetime(2026, 11, 5, tzinfo=UTC)) == ["B seal"]
    assert search(occurred_to=datetime(2026, 11, 5, tzinfo=UTC)) == ["A seal"]


def test_unreadable_records_are_never_returned(svc: Services) -> None:
    anna = svc.add_user("user:anna", ["group:maintenance"])
    bo = svc.add_user("user:bo", ["group:sales"])
    svc.ingestor.ingest(make_record(title="Secret seal", acl=Acl.of("group:maintenance")))

    assert titles(svc.search.search(anna, SearchQuery("seal"))) == ["Secret seal"]
    assert svc.search.search(bo, SearchQuery("seal")) == []


def test_no_match_is_an_empty_list_not_an_error(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    svc.ingestor.ingest(make_record())

    assert svc.search.search(anna, SearchQuery("zebra")) == []


@pytest.mark.parametrize("text", ["", "   ", "***", "- ()", "x" * 61])
def test_empty_or_overlong_queries_are_rejected(svc: Services, text: str) -> None:
    anna = svc.add_user("user:anna")

    with pytest.raises(DomainError) as error:
        svc.search.search(anna, SearchQuery(text))

    assert error.value.code == "query_invalid"
    assert error.value.status == 422


@pytest.mark.parametrize(
    "text",
    [
        '"unbalanced',
        "seal AND",
        "OR seal",
        "NEAR(seal",
        "seal*",
        "title:seal",
        "seal -gasket",
        "(seal",
    ],
)
def test_search_syntax_in_user_text_is_treated_as_plain_words(svc: Services, text: str) -> None:
    anna = svc.add_user("user:anna")
    svc.ingestor.ingest(make_record(content="Replace the seal and the gasket."))

    svc.search.search(anna, SearchQuery(text))  # must not raise


def test_the_result_limit_is_applied(svc: Services) -> None:
    anna = svc.add_user("user:anna")
    for index in range(5):
        svc.ingestor.ingest(make_record(external_id=f"d{index}", title=f"Seal {index}"))

    assert len(svc.search.search(anna, SearchQuery("seal", limit=3))) == 3
