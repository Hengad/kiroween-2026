"""One claim wins, and a Work Item never has more than one owner."""

from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from siloless.work.domain import NewWorkItem
from tests.helpers import fresh_services

USERS = ["user:u1", "user:u2", "user:u3", "user:u4"]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(claimers=st.lists(st.sampled_from(USERS), min_size=1, max_size=8))
def test_exactly_one_claim_succeeds_and_the_rest_are_told_who_won(claimers: list[str]) -> None:
    svc = fresh_services()
    try:
        people = {user: svc.add_user(user) for user in USERS}
        public = svc.ingestor.ingest(
            NewRecord(
                source_id="s",
                external_id="r",
                kind="doc",
                title="t",
                content="c",
                metadata={},
                acl=Acl.of("group:everyone"),
                occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        item = svc.items.create(
            people[USERS[0]],
            NewWorkItem(kind="question", title="Q", evidence=(public.version_id,)),
        )

        winners: list[str] = []
        for user in claimers:
            try:
                svc.items.claim(people[user], item.id)
                winners.append(user)
            except DomainError as error:
                assert error.code == "already_owned"
                assert error.extra == {"owner": winners[0]}

        assert winners == [claimers[0]]
        final = svc.items.get(people[USERS[0]], item.id)
        assert final.owner == claimers[0]
        assert final.status == "investigating"
    finally:
        svc.db.dispose()
