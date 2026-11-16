"""The Work Item status graph. Pure: no database access."""

from siloless.errors import DomainError

STATUSES: tuple[str, ...] = (
    "awaiting_acceptance",
    "open",
    "assigned",
    "investigating",
    "blocked",
    "resolved",
    "reopened",
)

TRANSITIONS: dict[str, frozenset[str]] = {
    # The asker accepts the cited answer, or declines it and the question opens up.
    "awaiting_acceptance": frozenset({"resolved", "open"}),
    "open": frozenset({"investigating", "assigned", "resolved"}),
    "assigned": frozenset({"investigating"}),
    "investigating": frozenset({"blocked", "resolved"}),
    "blocked": frozenset({"investigating"}),
    "resolved": frozenset({"reopened"}),
    "reopened": frozenset({"investigating", "assigned"}),
}


def check_transition(old: str, new: str) -> None:
    """Raise `invalid_transition` unless `old` may move to `new`."""
    if new not in TRANSITIONS.get(old, frozenset()):
        raise DomainError("invalid_transition", 409, f"A work item cannot go from {old} to {new}.")
