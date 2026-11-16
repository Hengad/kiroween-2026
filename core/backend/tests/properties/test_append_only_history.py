"""The Event Log only ever grows: nothing already written is changed or removed."""

from datetime import UTC, datetime

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select

from siloless.access.acl import Acl
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from siloless.storage.models import EventRow
from siloless.work.domain import NewWorkItem
from tests.helpers import Services, fresh_services

OPS = st.lists(
    st.tuples(
        st.sampled_from(["ingest", "create", "claim", "resolve", "reopen", "assign"]),
        st.integers(min_value=0, max_value=2),
    ),
    min_size=1,
    max_size=25,
)


def snapshot(svc: Services) -> list[tuple[object, ...]]:
    with svc.db.transaction(write=False) as session:
        rows = session.execute(select(EventRow).order_by(EventRow.seq)).scalars()
        return [
            (r.seq, r.id, r.occurred_at, r.type, r.actor, r.subject_id, str(r.payload))
            for r in rows
        ]


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=OPS)
def test_earlier_events_never_change_and_sequence_numbers_only_grow(
    ops: list[tuple[str, int]],
) -> None:
    svc = fresh_services()
    try:
        anna = svc.add_user("user:anna")
        svc.add_user("user:bo")
        public = svc.ingestor.ingest(
            NewRecord(
                source_id="s",
                external_id="seed",
                kind="doc",
                title="t",
                content="c",
                metadata={},
                acl=Acl.of("group:everyone"),
                occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
            )
        )
        item_ids: list[str] = []
        previous = snapshot(svc)

        for op, index in ops:
            try:
                if op == "ingest":
                    svc.ingestor.ingest(
                        NewRecord(
                            source_id="s",
                            external_id=f"r{index}",
                            kind="doc",
                            title="t",
                            content=f"version {len(previous)}",
                            metadata={},
                            acl=Acl.of("group:everyone"),
                            occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
                        )
                    )
                elif op == "create":
                    item = svc.items.create(
                        anna,
                        NewWorkItem(kind="action", title="A", evidence=(public.version_id,)),
                    )
                    item_ids.append(item.id)
                elif item_ids:
                    item_id = item_ids[index % len(item_ids)]
                    if op == "claim":
                        svc.items.claim(anna, item_id)
                    elif op == "resolve":
                        svc.items.transition(anna, item_id, "resolved", "done")
                    elif op == "reopen":
                        svc.items.transition(anna, item_id, "reopened")
                    elif op == "assign":
                        svc.items.assign(anna, item_id, "user:bo")
            except DomainError:
                pass  # rejected operations are allowed; they must not touch the log

            current = snapshot(svc)
            assert current[: len(previous)] == previous
            assert [row[0] for row in current] == sorted({row[0] for row in current})
            previous = current
    finally:
        svc.db.dispose()
