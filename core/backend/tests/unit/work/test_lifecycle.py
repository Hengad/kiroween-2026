from itertools import product

import pytest

from siloless.errors import DomainError
from siloless.work.lifecycle import STATUSES, TRANSITIONS, check_transition

# Requirement 9.1, written out independently of the implementation.
ALLOWED = {
    ("awaiting_acceptance", "resolved"),
    ("awaiting_acceptance", "open"),
    ("open", "investigating"),
    ("open", "assigned"),
    ("open", "resolved"),
    ("assigned", "investigating"),
    ("investigating", "blocked"),
    ("investigating", "resolved"),
    ("blocked", "investigating"),
    ("resolved", "reopened"),
    ("reopened", "investigating"),
    ("reopened", "assigned"),
}


def test_there_are_seven_statuses() -> None:
    assert set(STATUSES) == {
        "awaiting_acceptance",
        "open",
        "assigned",
        "investigating",
        "blocked",
        "resolved",
        "reopened",
    }


@pytest.mark.parametrize(("old", "new"), sorted(ALLOWED))
def test_every_allowed_transition_is_accepted(old: str, new: str) -> None:
    check_transition(old, new)  # must not raise


@pytest.mark.parametrize(
    ("old", "new"),
    sorted(set(product(STATUSES, STATUSES)) - ALLOWED),
)
def test_every_other_transition_is_rejected(old: str, new: str) -> None:
    with pytest.raises(DomainError) as error:
        check_transition(old, new)

    assert error.value.code == "invalid_transition"
    assert error.value.status == 409


def test_the_transition_table_matches_the_requirement_exactly() -> None:
    table = {(old, new) for old, targets in TRANSITIONS.items() for new in targets}

    assert table == ALLOWED


def test_a_resolved_item_can_only_be_reopened() -> None:
    assert TRANSITIONS["resolved"] == frozenset({"reopened"})
