"""Initial schema: memory, work items, the search index and the event log.

Revision ID: 0001
Revises:
Create Date: 2026-11-14

The baseline builds the schema with the same helper the application uses, so a
database made by either route is identical. It is safe to run on a database the
application already created. Every later schema change gets its own revision that
alters the tables explicitly; do not edit this one.
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from siloless.storage.models import Base
from siloless.storage.schema import install_schema

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    install_schema(op.get_bind())


def downgrade() -> None:
    bind = op.get_bind()
    for statement in (
        "DROP TRIGGER IF EXISTS events_no_update",
        "DROP TRIGGER IF EXISTS events_no_delete",
        "DROP TABLE IF EXISTS record_fts",
    ):
        bind.execute(text(statement))
    Base.metadata.drop_all(bind)
