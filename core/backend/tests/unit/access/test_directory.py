import pytest

from siloless.access.principals import EVERYONE, PrincipalDirectory
from siloless.errors import DomainError
from siloless.storage.db import Database


def _seed(db: Database) -> PrincipalDirectory:
    directory = PrincipalDirectory()
    with db.transaction() as session:
        directory.put(session, "user:anna", "Anna")
        directory.put(session, "group:maintenance", "Maintenance")
        directory.put(session, "role:shift-lead", "Shift lead")
    return directory


def test_principals_can_be_created_and_listed(db: Database) -> None:
    directory = _seed(db)

    with db.transaction(write=False) as session:
        listed = {p.id: (p.type, p.name) for p in directory.list(session)}

    assert listed["user:anna"] == ("user", "Anna")
    assert listed["group:maintenance"] == ("group", "Maintenance")
    assert listed["role:shift-lead"] == ("role", "Shift lead")
    assert EVERYONE in listed


def test_putting_an_existing_principal_updates_its_name(db: Database) -> None:
    directory = _seed(db)

    with db.transaction() as session:
        directory.put(session, "user:anna", "Anna Virtanen")

    with db.transaction(write=False) as session:
        names = {p.id: p.name for p in directory.list(session)}

    assert names["user:anna"] == "Anna Virtanen"


@pytest.mark.parametrize("bad_id", ["anna", "team:x", "user:Has Space", "system", ""])
def test_malformed_principal_ids_are_rejected(db: Database, bad_id: str) -> None:
    directory = PrincipalDirectory()

    with pytest.raises(DomainError) as error, db.transaction() as session:
        directory.put(session, bad_id, "Nobody")

    assert error.value.code == "principal_invalid"


def test_a_user_resolves_to_its_memberships_and_everyone(db: Database) -> None:
    directory = _seed(db)
    with db.transaction() as session:
        directory.set_memberships(session, "user:anna", ["group:maintenance", "role:shift-lead"])

    with db.transaction(write=False) as session:
        who = directory.resolve(session, "user:anna")

    assert who.id == "user:anna"
    assert who.ids == frozenset({"user:anna", "group:maintenance", "role:shift-lead", EVERYONE})


def test_a_membership_change_applies_to_the_next_resolve(db: Database) -> None:
    directory = _seed(db)
    with db.transaction() as session:
        directory.set_memberships(session, "user:anna", ["group:maintenance"])
    with db.transaction(write=False) as session:
        assert "group:maintenance" in directory.resolve(session, "user:anna").ids

    with db.transaction() as session:
        directory.set_memberships(session, "user:anna", ["role:shift-lead"])

    with db.transaction(write=False) as session:
        ids = directory.resolve(session, "user:anna").ids
    assert "group:maintenance" not in ids
    assert "role:shift-lead" in ids


def test_resolving_an_unknown_principal_is_rejected(db: Database) -> None:
    directory = _seed(db)

    with pytest.raises(DomainError) as error, db.transaction(write=False) as session:
        directory.resolve(session, "user:ghost")

    assert error.value.code == "principal_unknown"
    assert error.value.status == 403


def test_a_group_cannot_act_as_a_requester(db: Database) -> None:
    directory = _seed(db)

    with pytest.raises(DomainError) as error, db.transaction(write=False) as session:
        directory.resolve(session, "group:maintenance")

    assert error.value.code == "principal_unknown"


def test_the_system_principal_cannot_be_resolved_from_storage(db: Database) -> None:
    directory = _seed(db)

    with pytest.raises(DomainError) as error, db.transaction(write=False) as session:
        directory.resolve(session, "system")

    assert error.value.code == "principal_unknown"


def test_memberships_must_name_existing_groups_or_roles(db: Database) -> None:
    directory = _seed(db)

    with pytest.raises(DomainError) as error, db.transaction() as session:
        directory.set_memberships(session, "user:anna", ["group:nowhere"])
    assert error.value.code == "principal_unknown"

    with pytest.raises(DomainError) as error, db.transaction() as session:
        directory.set_memberships(session, "user:anna", ["user:anna"])
    assert error.value.code == "principal_invalid"


def test_only_users_can_have_memberships(db: Database) -> None:
    directory = _seed(db)

    with pytest.raises(DomainError) as error, db.transaction() as session:
        directory.set_memberships(session, "group:maintenance", ["role:shift-lead"])

    assert error.value.code == "principal_invalid"
