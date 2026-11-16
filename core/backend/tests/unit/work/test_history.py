from datetime import UTC, datetime
from typing import Any

import pytest

from siloless.events.log import Event
from siloless.work.history import replay

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def event(seq: int, type_: str, changes: dict[str, Any], **extra: Any) -> Event:
    return Event(
        seq=seq,
        id=f"e{seq}",
        occurred_at=NOW,
        type=type_,
        actor="user:anna",
        subject_type="work_item",
        subject_id="w1",
        payload={"changes": changes, **extra},
    )


CREATED = event(
    1,
    "work_item.created",
    {
        "kind": "question",
        "title": "Why is Press 3 slow?",
        "description": "Since Monday.",
        "status": "open",
        "owner": None,
        "resolution": None,
        "due_at": None,
        "created_by": "user:anna",
        "evidence": ["v1"],
    },
)


def test_replaying_the_creation_event_gives_the_initial_state() -> None:
    state = replay([CREATED])

    assert state.kind == "question"
    assert state.title == "Why is Press 3 slow?"
    assert state.status == "open"
    assert state.owner is None
    assert state.resolution is None
    assert state.created_by == "user:anna"
    assert state.evidence == ("v1",)


def test_later_events_overwrite_only_the_fields_they_changed() -> None:
    state = replay(
        [
            CREATED,
            event(2, "work_item.claimed", {"owner": "user:bo", "status": "investigating"}),
            event(3, "work_item.status_changed", {"status": "blocked"}),
        ]
    )

    assert state.status == "blocked"
    assert state.owner == "user:bo"
    assert state.title == "Why is Press 3 slow?"


def test_resolving_stores_the_resolution() -> None:
    state = replay(
        [
            CREATED,
            event(2, "work_item.claimed", {"owner": "user:bo", "status": "investigating"}),
            event(
                3,
                "work_item.status_changed",
                {"status": "resolved", "resolution": "Worn seal replaced."},
            ),
        ]
    )

    assert state.status == "resolved"
    assert state.resolution == "Worn seal replaced."


def test_reopening_clears_the_current_resolution_but_the_event_keeps_it() -> None:
    resolved = event(
        3,
        "work_item.status_changed",
        {"status": "resolved", "resolution": "Worn seal replaced."},
    )
    reopened = event(4, "work_item.status_changed", {"status": "reopened", "resolution": None})

    state = replay([CREATED, resolved, reopened])

    assert state.status == "reopened"
    assert state.resolution is None
    assert resolved.payload["changes"]["resolution"] == "Worn seal replaced."


def test_reassignment_changes_the_owner() -> None:
    state = replay(
        [
            CREATED,
            event(
                2,
                "work_item.assigned",
                {"owner": "user:bo", "status": "assigned"},
                before={"owner": None},
            ),
            event(3, "work_item.assigned", {"owner": "user:cy"}, before={"owner": "user:bo"}),
        ]
    )

    assert state.owner == "user:cy"
    assert state.status == "assigned"


def test_replay_needs_a_creation_event_first() -> None:
    with pytest.raises(ValueError):
        replay([event(2, "work_item.claimed", {"owner": "user:bo"})])

    with pytest.raises(ValueError):
        replay([])
