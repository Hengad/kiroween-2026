"""A model-based test of the Work Item lifecycle.

A small model, written independently of the service, predicts whether each operation
succeeds and what the item looks like afterwards. After every step the service must
agree with the model, the ownership rules must hold, and replaying the Event Log must
reproduce the current state.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from siloless.access.acl import Acl
from siloless.access.principals import ResolvedPrincipal
from siloless.errors import DomainError
from siloless.memory.domain import NewRecord
from siloless.work.domain import NewWorkItem, WorkItem
from siloless.work.history import replay
from tests.helpers import Services, fresh_services

USERS = ["user:u1", "user:u2", "user:u3"]

# Requirement 9.1, restated here independently of the implementation.
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


@dataclass
class Model:
    status: str
    owner: str | None = None
    resolution: str | None = None


@dataclass
class World:
    svc: Services
    users: dict[str, ResolvedPrincipal]
    evidence: tuple[str, ...]
    items: dict[str, Model] = field(default_factory=dict)


def build_world() -> World:
    svc = fresh_services()
    users = {user: svc.add_user(user) for user in USERS}
    public = svc.ingestor.ingest(
        NewRecord(
            source_id="s",
            external_id="public",
            kind="doc",
            title="t",
            content="c",
            metadata={},
            acl=Acl.of("group:everyone"),
            occurred_at=datetime(2026, 11, 1, tzinfo=UTC),
        )
    )
    return World(svc, users, (public.version_id,))


class WorkItemMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self.world = build_world()

    def teardown(self) -> None:
        self.world.svc.db.dispose()

    # -- helpers ----------------------------------------------------------------

    def _ids(self) -> list[str]:
        return sorted(self.world.items)

    def _attempt(
        self,
        call: Callable[[], WorkItem],
        expected_code: str | None,
        expected: Model | None,
        item_id: str,
    ) -> None:
        model = self.world.items[item_id]
        if expected_code is None:
            assert expected is not None
            result = call()
            self.world.items[item_id] = expected
            assert (result.status, result.owner, result.resolution) == (
                expected.status,
                expected.owner,
                expected.resolution,
            )
        else:
            try:
                call()
            except DomainError as error:
                assert error.code == expected_code, (error.code, expected_code)
                assert self.world.items[item_id] == model
            else:
                raise AssertionError(f"expected {expected_code}")

    # -- rules ------------------------------------------------------------------

    @rule(
        user=st.sampled_from(USERS),
        start=st.sampled_from([(None, None), (None, "awaiting_acceptance"), ("user:u2", None)]),
    )
    def create(self, user: str, start: tuple[str | None, str | None]) -> None:
        owner, status = start
        item = self.world.svc.items.create(
            self.world.users[user],
            NewWorkItem(
                kind="question",
                title="Q",
                owner=owner,
                status=status,
                evidence=self.world.evidence,
            ),
        )
        expected_status = status or ("assigned" if owner else "open")
        self.world.items[item.id] = Model(expected_status, owner)

    @rule(data=st.data(), user=st.sampled_from(USERS))
    def claim(self, data: st.DataObject, user: str) -> None:
        if not self.world.items:
            return
        item_id = data.draw(st.sampled_from(self._ids()))
        model = self.world.items[item_id]
        if model.status == "open" and model.owner is None:
            code, after = None, Model("investigating", user, model.resolution)
        else:
            code = "already_owned" if model.owner is not None else "invalid_transition"
            after = None
        who = self.world.users[user]
        self._attempt(lambda: self.world.svc.items.claim(who, item_id), code, after, item_id)

    @rule(data=st.data(), user=st.sampled_from(USERS), new_owner=st.sampled_from(USERS))
    def assign(self, data: st.DataObject, user: str, new_owner: str) -> None:
        if not self.world.items:
            return
        item_id = data.draw(st.sampled_from(self._ids()))
        model = self.world.items[item_id]
        if model.status in ("awaiting_acceptance", "resolved"):
            code, after = "not_assignable", None
        else:
            status = "assigned" if model.status in ("open", "reopened") else model.status
            code, after = None, Model(status, new_owner, model.resolution)
        who = self.world.users[user]
        self._attempt(
            lambda: self.world.svc.items.assign(who, item_id, new_owner), code, after, item_id
        )

    @rule(
        data=st.data(),
        user=st.sampled_from(USERS),
        to=st.sampled_from(
            [
                "awaiting_acceptance",
                "open",
                "assigned",
                "investigating",
                "blocked",
                "resolved",
                "reopened",
            ]
        ),
        resolution=st.sampled_from([None, "", "  ", "Fixed."]),
    )
    def transition(self, data: st.DataObject, user: str, to: str, resolution: str | None) -> None:
        if not self.world.items:
            return
        item_id = data.draw(st.sampled_from(self._ids()))
        model = self.world.items[item_id]
        old = model.status
        after: Model | None = None
        code: str | None
        if (
            to == "assigned"
            or (old == "open" and to == "investigating")
            or (old, to) not in ALLOWED
        ):
            code = "invalid_transition"
        elif to == "resolved" and not (resolution and resolution.strip()):
            code = "resolution_required"
        else:
            code = None
            owner = model.owner
            stored = model.resolution
            if to == "resolved":
                stored = resolution
            elif to == "reopened":
                stored = None
            if to == "investigating" and owner is None:
                owner = user
            after = Model(to, owner, stored)
        who = self.world.users[user]
        self._attempt(
            lambda: self.world.svc.items.transition(who, item_id, to, resolution),
            code,
            after,
            item_id,
        )

    # -- invariants -------------------------------------------------------------

    @invariant()
    def the_service_agrees_with_the_model_and_the_log_replays_to_it(self) -> None:
        system = ResolvedPrincipal.system()
        for item_id, model in self.world.items.items():
            item = self.world.svc.items.get(system, item_id)
            assert (item.status, item.owner, item.resolution) == (
                model.status,
                model.owner,
                model.resolution,
            )
            if item.status in ("assigned", "investigating", "blocked"):
                assert item.owner is not None
            if item.status in ("open", "awaiting_acceptance"):
                assert item.owner is None
            state = replay(self.world.svc.items.history(system, item_id))
            assert (state.status, state.owner, state.resolution) == (
                item.status,
                item.owner,
                item.resolution,
            )


WorkItemMachine.TestCase.settings = settings(
    max_examples=25,
    stateful_step_count=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestWorkItemLifecycle = WorkItemMachine.TestCase
