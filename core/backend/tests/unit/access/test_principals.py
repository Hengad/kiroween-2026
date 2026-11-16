import pytest

from siloless.access.principals import (
    EVERYONE,
    SYSTEM,
    ResolvedPrincipal,
    is_valid_principal_id,
)


def test_a_user_expands_to_itself_its_groups_its_roles_and_everyone() -> None:
    who = ResolvedPrincipal.for_user("user:anna", ["group:maintenance", "role:shift-lead"])

    assert who.id == "user:anna"
    assert who.ids == frozenset(
        {"user:anna", "group:maintenance", "role:shift-lead", "group:everyone"}
    )
    assert not who.is_system


def test_every_user_belongs_to_everyone_even_without_memberships() -> None:
    who = ResolvedPrincipal.for_user("user:bo", [])

    assert EVERYONE in who.ids


def test_the_system_principal_is_flagged_and_has_its_own_id() -> None:
    who = ResolvedPrincipal.system()

    assert who.id == SYSTEM
    assert who.is_system


@pytest.mark.parametrize(
    "value",
    ["user:anna", "group:maintenance", "role:shift-lead", "user:a.b_c-1", "group:everyone"],
)
def test_well_formed_principal_ids_are_accepted(value: str) -> None:
    assert is_valid_principal_id(value)


@pytest.mark.parametrize(
    "value",
    ["", "anna", "user:", "team:x", "user:has space", "user:-leading", "system", "USER:anna"],
)
def test_malformed_principal_ids_are_rejected(value: str) -> None:
    assert not is_valid_principal_id(value)
