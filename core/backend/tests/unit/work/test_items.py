from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select

from siloless.access.acl import Acl
from siloless.access.principals import ResolvedPrincipal
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from siloless.storage.models import WORK_ITEM_STATUSES, WorkItemRow
from siloless.work.domain import NewWorkItem, WorkItem
from siloless.work.history import replay
from siloless.work.lifecycle import STATUSES
from tests.helpers import Services, build_services


@pytest.fixture
def svc() -> Services:
    return build_services()


@pytest.fixture
def anna(svc: Services) -> ResolvedPrincipal:
    return svc.add_user("user:anna", ["group:maintenance"])


@pytest.fixture
def bo(svc: Services) -> ResolvedPrincipal:
    return svc.add_user("user:bo", ["group:sales"])


@pytest.fixture
def cy(svc: Services) -> ResolvedPrincipal:
    return svc.add_user("user:cy", ["group:maintenance"])


def make_record(**overrides: Any) -> NewRecord:
    base = NewRecord(
        source_id="wiki",
        external_id="doc",
        kind="procedure",
        title="Seal replacement",
        content="Replace the hydraulic seal.",
        metadata={},
        acl=Acl.of("group:maintenance"),
        occurred_at=datetime(2026, 11, 1, 8, 0, tzinfo=UTC),
    )
    return replace(base, **overrides)


def make_item(svc: Services, who: ResolvedPrincipal, **overrides: Any) -> WorkItem:
    fields: dict[str, Any] = {"kind": "question", "title": "Why is Press 3 slow?"}
    fields.update(overrides)
    return svc.items.create(who, NewWorkItem(**fields))


def code_of(call: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(DomainError) as error:
        call(*args, **kwargs)
    return error.value.code


def row_count(svc: Services) -> int:
    with svc.db.transaction(write=False) as session:
        return session.execute(select(func.count()).select_from(WorkItemRow)).scalar_one()


def event_types(svc: Services, who: ResolvedPrincipal, item_id: str) -> list[str]:
    return [event.type for event in svc.items.history(who, item_id)]


def assert_structure(item: WorkItem) -> None:
    """The ownership rules every Work Item obeys, whatever happened to it."""
    if item.status in ("assigned", "investigating", "blocked"):
        assert item.owner is not None, item
    if item.status in ("open", "awaiting_acceptance"):
        assert item.owner is None, item


def test_the_status_lists_in_storage_and_lifecycle_agree() -> None:
    assert set(STATUSES) == set(WORK_ITEM_STATUSES)


# -- creating -----------------------------------------------------------------------


def test_a_new_item_is_open_and_unowned_by_default(svc: Services, anna: ResolvedPrincipal) -> None:
    due = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)

    item = make_item(svc, anna, description="Since Monday.", due_at=due)

    assert len(item.id) == 26
    assert item.kind == "question"
    assert item.title == "Why is Press 3 slow?"
    assert item.description == "Since Monday."
    assert item.status == "open"
    assert item.owner is None
    assert item.created_by == "user:anna"
    assert item.due_at == due
    assert item.resolution is None
    assert item.created_at == svc.clock.now()
    assert event_types(svc, anna, item.id) == ["work_item.created"]


def test_an_item_created_with_an_owner_starts_assigned(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna, kind="action", owner="user:bo")

    assert item.status == "assigned"
    assert item.owner == "user:bo"


def test_an_item_may_start_awaiting_acceptance(svc: Services, anna: ResolvedPrincipal) -> None:
    item = make_item(svc, anna, status="awaiting_acceptance")

    assert item.status == "awaiting_acceptance"
    assert item.owner is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "resolved"},
        {"status": "investigating"},
        {"status": "open", "owner": "user:bo"},
        {"status": "awaiting_acceptance", "owner": "user:bo"},
        {"kind": "chore"},
        {"title": "   "},
        {"due_at": datetime(2026, 11, 20, 9, 0)},  # no time zone
    ],
)
def test_invalid_new_items_are_rejected_and_nothing_is_stored(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal, overrides: dict[str, Any]
) -> None:
    assert code_of(make_item, svc, anna, **overrides) == "work_item_invalid"
    assert row_count(svc) == 0


def test_the_owner_must_be_an_existing_user(svc: Services, anna: ResolvedPrincipal) -> None:
    assert code_of(make_item, svc, anna, owner="user:ghost") == "owner_unknown"
    assert code_of(make_item, svc, anna, owner="group:maintenance") == "owner_must_be_user"
    assert row_count(svc) == 0


def test_evidence_must_exist_and_be_readable_by_the_creator(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    secret = svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance")))

    assert code_of(make_item, svc, anna, evidence=("missing",)) == "node_not_found"
    # Bo cannot read it, so for Bo it is indistinguishable from a missing version.
    assert code_of(make_item, svc, bo, evidence=(secret.version_id,)) == "node_not_found"
    assert row_count(svc) == 0


# -- reading ------------------------------------------------------------------------


def test_the_creator_and_the_owner_can_always_read_an_item(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna, owner="user:bo")  # no evidence at all

    assert svc.items.get(anna, item.id).id == item.id
    assert svc.items.get(bo, item.id).id == item.id


def test_others_read_an_item_only_if_they_can_read_all_its_evidence(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    private = svc.ingestor.ingest(make_record(external_id="p", acl=Acl.of("group:maintenance")))
    public = svc.ingestor.ingest(make_record(external_id="q", acl=Acl.of("group:everyone")))
    mixed = make_item(svc, anna, evidence=(private.version_id, public.version_id))
    open_only = make_item(svc, anna, evidence=(public.version_id,))

    assert svc.items.get(cy, mixed.id).evidence == (private.version_id, public.version_id)
    assert code_of(svc.items.get, bo, mixed.id) == "not_found"
    assert svc.items.get(bo, open_only.id).id == open_only.id


def test_an_item_without_evidence_is_invisible_to_everyone_else(
    svc: Services, anna: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)

    assert code_of(svc.items.get, cy, item.id) == "not_found"
    assert svc.items.list(cy) == []


def test_an_unreadable_item_looks_exactly_like_a_missing_one(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)

    with pytest.raises(DomainError) as hidden:
        svc.items.get(bo, item.id)
    with pytest.raises(DomainError) as missing:
        svc.items.get(bo, "missing")

    assert (hidden.value.code, hidden.value.status, hidden.value.detail) == (
        missing.value.code,
        missing.value.status,
        missing.value.detail,
    )


def test_evidence_the_reader_can_no_longer_read_is_left_out(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    first = svc.ingestor.ingest(make_record(acl=Acl.of("group:maintenance")))
    item = make_item(svc, anna, evidence=(first.version_id,))
    assert svc.items.get(anna, item.id).evidence == (first.version_id,)

    svc.ingestor.ingest(make_record(acl=Acl.of("group:management")))  # Anna loses access

    # She created the item, so she still sees it, but not the evidence she lost.
    assert svc.items.get(anna, item.id).evidence == ()


def test_the_system_principal_creates_and_reads_everything(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    system = ResolvedPrincipal.system()
    item = make_item(svc, anna)

    assert svc.items.get(system, item.id).id == item.id
    assert make_item(svc, system, kind="incident").created_by == "system"


# -- listing ------------------------------------------------------------------------


def test_items_are_listed_newest_first_and_can_be_paged(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    made = [make_item(svc, anna, title=f"Item {n}") for n in range(5)]
    newest_first = [item.id for item in reversed(made)]

    assert [i.id for i in svc.items.list(anna)] == newest_first
    page_one = svc.items.list(anna, limit=2)
    page_two = svc.items.list(anna, limit=2, before=page_one[-1].id)
    assert [i.id for i in page_one] == newest_first[:2]
    assert [i.id for i in page_two] == newest_first[2:4]


def test_items_can_be_filtered_by_kind_status_and_owner(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    question = make_item(svc, anna, kind="question")
    action = make_item(svc, anna, kind="action", owner="user:bo")

    assert [i.id for i in svc.items.list(anna, kind="action")] == [action.id]
    assert [i.id for i in svc.items.list(anna, status="open")] == [question.id]
    assert [i.id for i in svc.items.list(anna, owner="user:bo")] == [action.id]
    assert svc.items.list(anna, kind="incident") == []


def test_a_list_contains_only_items_the_reader_may_read(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    public = svc.ingestor.ingest(make_record(acl=Acl.of("group:everyone")))
    visible = make_item(svc, anna, evidence=(public.version_id,))
    make_item(svc, anna)  # invisible to Bo

    assert [i.id for i in svc.items.list(bo)] == [visible.id]


# -- claiming -----------------------------------------------------------------------


def test_claiming_an_open_item_makes_the_claimant_the_owner(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)

    claimed = svc.items.claim(anna, item.id)

    assert claimed.owner == "user:anna"
    assert claimed.status == "investigating"
    assert event_types(svc, anna, item.id) == ["work_item.created", "work_item.claimed"]


def test_a_second_claim_fails_and_names_the_owner(
    svc: Services, anna: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)
    svc.items.claim(anna, item.id)
    public = svc.ingestor.ingest(make_record(acl=Acl.of("group:everyone")))
    shared = make_item(svc, anna, evidence=(public.version_id,))
    svc.items.claim(anna, shared.id)

    with pytest.raises(DomainError) as error:
        svc.items.claim(cy, shared.id)

    assert error.value.code == "already_owned"
    assert error.value.status == 409
    assert error.value.extra == {"owner": "user:anna"}
    assert svc.items.get(anna, shared.id).owner == "user:anna"


def test_only_open_items_can_be_claimed(svc: Services, anna: ResolvedPrincipal) -> None:
    waiting = make_item(svc, anna, status="awaiting_acceptance")
    assigned = make_item(svc, anna, owner="user:anna")

    assert code_of(svc.items.claim, anna, waiting.id) == "invalid_transition"
    # An assigned item has an owner, so a claim reports the owner.
    assert code_of(svc.items.claim, anna, assigned.id) == "already_owned"


def test_claiming_an_unreadable_item_is_not_found(
    svc: Services, anna: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)  # no evidence: only Anna can read it

    assert code_of(svc.items.claim, cy, item.id) == "not_found"
    assert svc.items.get(anna, item.id).owner is None


def test_the_system_principal_cannot_claim(svc: Services, anna: ResolvedPrincipal) -> None:
    item = make_item(svc, anna)

    assert code_of(svc.items.claim, ResolvedPrincipal.system(), item.id) == "owner_must_be_user"


# -- assigning ----------------------------------------------------------------------


def test_assigning_an_open_item_moves_it_to_assigned(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)

    assigned = svc.items.assign(anna, item.id, "user:bo")

    assert assigned.owner == "user:bo"
    assert assigned.status == "assigned"
    assert assigned.title == item.title
    assert assigned.description == item.description


def test_reassigning_replaces_the_owner_and_keeps_the_status(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)
    svc.items.claim(anna, item.id)

    moved = svc.items.assign(anna, item.id, "user:bo")

    assert moved.owner == "user:bo"
    assert moved.status == "investigating"
    last = svc.items.history(anna, item.id)[-1]
    assert last.type == "work_item.assigned"
    assert last.payload["before"]["owner"] == "user:anna"


def test_assigning_to_the_current_owner_changes_nothing(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna, owner="user:anna")
    before = event_types(svc, anna, item.id)

    svc.items.assign(anna, item.id, "user:anna")

    assert event_types(svc, anna, item.id) == before


@pytest.mark.parametrize("status", ["awaiting_acceptance", "resolved"])
def test_items_waiting_for_acceptance_or_resolved_cannot_be_assigned(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal, status: str
) -> None:
    item = make_item(svc, anna, status="awaiting_acceptance")
    if status == "resolved":
        item = svc.items.transition(anna, item.id, "resolved", "Answer accepted.")

    assert code_of(svc.items.assign, anna, item.id, "user:bo") == "not_assignable"
    assert svc.items.get(anna, item.id).owner is None


def test_the_new_owner_must_be_an_existing_user(svc: Services, anna: ResolvedPrincipal) -> None:
    item = make_item(svc, anna)

    assert code_of(svc.items.assign, anna, item.id, "user:ghost") == "owner_unknown"
    assert code_of(svc.items.assign, anna, item.id, "group:maintenance") == "owner_must_be_user"
    assert svc.items.get(anna, item.id).owner is None


# -- transitions --------------------------------------------------------------------


def test_resolving_requires_a_resolution_and_stores_it(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)

    assert code_of(svc.items.transition, anna, item.id, "resolved") == "resolution_required"
    assert code_of(svc.items.transition, anna, item.id, "resolved", "  ") == "resolution_required"
    assert svc.items.get(anna, item.id).status == "open"

    done = svc.items.transition(anna, item.id, "resolved", "Seal replaced.")

    assert done.status == "resolved"
    assert done.resolution == "Seal replaced."
    assert done.owner is None


def test_reopening_clears_the_resolution_but_history_keeps_it(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)
    svc.items.transition(anna, item.id, "resolved", "Seal replaced.")

    reopened = svc.items.transition(anna, item.id, "reopened")

    assert reopened.status == "reopened"
    assert reopened.resolution is None
    resolved_event = svc.items.history(anna, item.id)[1]
    assert resolved_event.payload["changes"]["resolution"] == "Seal replaced."


def test_investigating_a_reopened_item_without_an_owner_makes_the_actor_the_owner(
    svc: Services, anna: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)
    svc.items.transition(anna, item.id, "resolved", "Done.")
    svc.items.transition(anna, item.id, "reopened")

    working = svc.items.transition(anna, item.id, "investigating")

    assert working.owner == "user:anna"
    assert working.status == "investigating"


def test_an_item_can_be_blocked_and_resumed(svc: Services, anna: ResolvedPrincipal) -> None:
    item = make_item(svc, anna)
    svc.items.claim(anna, item.id)

    blocked = svc.items.transition(anna, item.id, "blocked")
    resumed = svc.items.transition(anna, item.id, "investigating")

    assert blocked.status == "blocked"
    assert blocked.owner == "user:anna"
    assert resumed.status == "investigating"


def test_declining_a_cited_answer_reopens_the_question_unowned(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna, status="awaiting_acceptance")

    declined = svc.items.transition(anna, item.id, "open")

    assert declined.status == "open"
    assert declined.owner is None


def test_accepting_a_cited_answer_resolves_the_question(
    svc: Services, anna: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna, status="awaiting_acceptance")

    accepted = svc.items.transition(anna, item.id, "resolved", "Answer accepted.")

    assert accepted.status == "resolved"


@pytest.mark.parametrize(
    ("setup", "target"),
    [
        ("open", "blocked"),
        ("open", "reopened"),
        ("open", "assigned"),  # assigning goes through assign()
        ("open", "investigating"),  # claiming goes through claim()
        ("open", "open"),
        ("resolved", "investigating"),
        ("investigating", "open"),
    ],
)
def test_invalid_transitions_are_rejected_and_change_nothing(
    svc: Services, anna: ResolvedPrincipal, setup: str, target: str
) -> None:
    item = make_item(svc, anna)
    if setup == "resolved":
        item = svc.items.transition(anna, item.id, "resolved", "Done.")
    elif setup == "investigating":
        item = svc.items.claim(anna, item.id)
    events_before = event_types(svc, anna, item.id)

    assert code_of(svc.items.transition, anna, item.id, target) == "invalid_transition"

    assert svc.items.get(anna, item.id) == item
    assert event_types(svc, anna, item.id) == events_before


# -- history ------------------------------------------------------------------------


def test_history_replays_to_the_current_state(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    public = svc.ingestor.ingest(make_record(acl=Acl.of("group:everyone")))
    item = make_item(
        svc, anna, evidence=(public.version_id,), due_at=datetime(2026, 11, 20, tzinfo=UTC)
    )
    svc.items.claim(anna, item.id)
    svc.items.assign(anna, item.id, "user:bo")
    svc.items.transition(anna, item.id, "blocked")
    svc.items.transition(anna, item.id, "investigating")
    svc.items.transition(anna, item.id, "resolved", "Fixed.")

    current = svc.items.get(anna, item.id)
    state = replay(svc.items.history(anna, item.id))

    assert (state.status, state.owner, state.resolution) == ("resolved", "user:bo", "Fixed.")
    assert (state.status, state.owner, state.resolution) == (
        current.status,
        current.owner,
        current.resolution,
    )
    assert state.evidence == current.evidence
    assert [e.type for e in svc.items.history(anna, item.id)] == [
        "work_item.created",
        "work_item.claimed",
        "work_item.assigned",
        "work_item.status_changed",
        "work_item.status_changed",
        "work_item.status_changed",
    ]


def test_history_records_who_did_what_and_when(
    svc: Services, anna: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    public = svc.ingestor.ingest(make_record(acl=Acl.of("group:everyone")))
    item = make_item(svc, anna, evidence=(public.version_id,))
    svc.clock.advance(timedelta(minutes=10))
    svc.items.claim(cy, item.id)

    created, claimed = svc.items.history(anna, item.id)

    assert (created.actor, claimed.actor) == ("user:anna", "user:cy")
    assert claimed.occurred_at == created.occurred_at + timedelta(minutes=10)
    assert claimed.payload["before"] == {"owner": None, "status": "open"}


def test_history_of_an_unreadable_item_is_not_found(
    svc: Services, anna: ResolvedPrincipal, cy: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)

    assert code_of(svc.items.history, cy, item.id) == "not_found"
    assert code_of(svc.items.history, anna, "missing") == "not_found"


def test_every_operation_keeps_the_ownership_rules(
    svc: Services, anna: ResolvedPrincipal, bo: ResolvedPrincipal
) -> None:
    item = make_item(svc, anna)
    steps = [
        lambda: svc.items.claim(anna, item.id),
        lambda: svc.items.transition(anna, item.id, "blocked"),
        lambda: svc.items.transition(anna, item.id, "investigating"),
        lambda: svc.items.assign(anna, item.id, "user:bo"),
        lambda: svc.items.transition(anna, item.id, "resolved", "ok"),
        lambda: svc.items.transition(anna, item.id, "reopened"),
        lambda: svc.items.assign(anna, item.id, "user:anna"),
    ]
    for step in steps:
        assert_structure(step())
