import pytest
from hypothesis import given
from hypothesis import strategies as st

from siloless.access.acl import Acl
from siloless.access.principals import ResolvedPrincipal
from siloless.errors import DomainError


def test_an_empty_acl_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        Acl(frozenset())

    assert error.value.code == "acl_empty"


def test_a_malformed_principal_id_in_an_acl_is_rejected() -> None:
    with pytest.raises(DomainError) as error:
        Acl.of("user:anna", "not a principal")

    assert error.value.code == "record_invalid"


def test_acl_allows_a_principal_who_shares_an_entry() -> None:
    acl = Acl.of("group:maintenance")
    who = ResolvedPrincipal.for_user("user:anna", ["group:maintenance"])

    assert acl.allows(who)


def test_acl_denies_a_principal_who_shares_no_entry() -> None:
    acl = Acl.of("group:management")
    who = ResolvedPrincipal.for_user("user:anna", ["group:maintenance"])

    assert not acl.allows(who)


def test_a_record_for_everyone_is_readable_by_any_user() -> None:
    acl = Acl.of("group:everyone")

    assert acl.allows(ResolvedPrincipal.for_user("user:anyone", []))


def test_the_system_principal_is_allowed_by_every_acl() -> None:
    assert Acl.of("user:anna").allows(ResolvedPrincipal.system())


_ids = st.sampled_from(
    ["user:anna", "user:bo", "group:a", "group:b", "role:x", "role:y", "group:everyone"]
)


@given(acl_ids=st.sets(_ids, min_size=1), user_ids=st.sets(_ids))
def test_allows_exactly_when_the_acl_and_the_principal_set_overlap(
    acl_ids: set[str], user_ids: set[str]
) -> None:
    who = ResolvedPrincipal.for_user("user:probe", user_ids)

    expected = bool(acl_ids & who.ids)

    assert Acl(frozenset(acl_ids)).allows(who) is expected
