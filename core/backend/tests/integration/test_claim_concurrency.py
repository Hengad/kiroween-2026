"""Real concurrency: several threads race to claim the same Work Item."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from siloless.storage.db import Database
from siloless.work.domain import NewWorkItem
from tests.helpers import build_services

THREADS = 8
ROUNDS = 20


def test_of_many_simultaneous_claims_exactly_one_wins(tmp_path: Path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'race.db'}")
    database.create_schema()
    svc = build_services(database)
    users = [svc.add_user(f"user:racer{n}") for n in range(THREADS)]
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

    try:
        for _ in range(ROUNDS):
            item = svc.items.create(
                users[0], NewWorkItem(kind="question", title="Q", evidence=(public.version_id,))
            )
            start = Barrier(THREADS)

            def race(
                user_index: int, item_id: str = item.id, start: Barrier = start
            ) -> tuple[str, str]:
                start.wait()
                try:
                    claimed = svc.items.claim(users[user_index], item_id)
                    return ("won", str(claimed.owner))
                except DomainError as error:
                    return (error.code, str(error.extra.get("owner")))

            with ThreadPoolExecutor(max_workers=THREADS) as pool:
                results = list(pool.map(race, range(THREADS)))

            winners = [owner for outcome, owner in results if outcome == "won"]
            losers = [(outcome, owner) for outcome, owner in results if outcome != "won"]
            assert len(winners) == 1, results
            assert len(losers) == THREADS - 1
            assert {outcome for outcome, _ in losers} == {"already_owned"}
            assert {owner for _, owner in losers} == {winners[0]}

            final = svc.items.get(users[0], item.id)
            assert final.owner == winners[0]
            history = [e.type for e in svc.items.history(users[0], item.id)]
            assert history.count("work_item.claimed") == 1
    finally:
        database.dispose()
