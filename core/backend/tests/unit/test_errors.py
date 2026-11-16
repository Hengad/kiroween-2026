from siloless.errors import DomainError


def test_domain_error_carries_code_status_detail_and_extra_members() -> None:
    error = DomainError("already_owned", 409, "Already claimed.", {"owner": "user:anna"})

    assert error.code == "already_owned"
    assert error.status == 409
    assert error.detail == "Already claimed."
    assert error.extra == {"owner": "user:anna"}
    assert str(error) == "Already claimed."


def test_domain_error_extra_members_default_to_empty() -> None:
    error = DomainError("not_found", 404, "Not found.")

    assert error.extra == {}
