"""Hypothesis strategies for the core domain objects, shared by property tests.

The pools are small on purpose: with few principals and records, random worlds
collide often, which is what finds permission bugs.
"""

from dataclasses import dataclass

from hypothesis import strategies as st

USERS = ["user:u1", "user:u2", "user:u3"]
GROUPS = ["group:g1", "group:g2"]
ROLES = ["role:r1"]
EVERYONE = "group:everyone"
ACL_POOL = [*USERS, *GROUPS, *ROLES, EVERYONE]
RECORD_KEYS = ["a", "b", "c"]


@st.composite
def memberships(draw: st.DrawFn) -> dict[str, frozenset[str]]:
    """For each user, the groups and roles they belong to."""
    return {user: frozenset(draw(st.sets(st.sampled_from([*GROUPS, *ROLES])))) for user in USERS}


acls = st.frozensets(st.sampled_from(ACL_POOL), min_size=1)


@dataclass(frozen=True)
class IngestOp:
    """Push the item `key` with this ACL and this text."""

    key: str
    acl: frozenset[str]
    variant: int


ingest_ops = st.builds(
    IngestOp,
    key=st.sampled_from(RECORD_KEYS),
    acl=acls,
    variant=st.integers(min_value=0, max_value=2),
)
