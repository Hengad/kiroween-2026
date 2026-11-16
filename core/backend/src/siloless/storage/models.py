"""SQLAlchemy ORM models. These are storage shapes, not domain objects."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from siloless.storage.types import UtcDateTime

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}

WORK_ITEM_KINDS = ("question", "request", "incident", "action")
WORK_ITEM_STATUSES = (
    "awaiting_acceptance",
    "open",
    "assigned",
    "investigating",
    "blocked",
    "resolved",
    "reopened",
)


def _in_list(column: str, values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"{column} IN ({quoted})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PrincipalRow(Base):
    __tablename__ = "principals"
    __table_args__ = (
        CheckConstraint(_in_list("type", ("user", "group", "role")), name="type_valid"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)


class MembershipRow(Base):
    __tablename__ = "memberships"

    user_id: Mapped[str] = mapped_column(ForeignKey("principals.id"), primary_key=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("principals.id"), primary_key=True)


class RecordRow(Base):
    __tablename__ = "records"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(String)
    external_id: Mapped[str] = mapped_column(String)
    # Points at the newest version. Not a foreign key: it would be circular with
    # record_versions.record_id. The ingestor keeps it correct inside one transaction.
    current_version_id: Mapped[str | None] = mapped_column(String, nullable=True)


class RecordVersionRow(Base):
    __tablename__ = "record_versions"
    __table_args__ = (UniqueConstraint("record_id", "version"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("records.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", JSON)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime)
    ingested_at: Mapped[datetime] = mapped_column(UtcDateTime)
    content_hash: Mapped[str] = mapped_column(String)


class RecordVersionAclRow(Base):
    __tablename__ = "record_version_acl"

    version_id: Mapped[str] = mapped_column(ForeignKey("record_versions.id"), primary_key=True)
    principal_id: Mapped[str] = mapped_column(String, primary_key=True, index=True)


class EntityRow(Base):
    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("entity_type", "key"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String)
    key: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON)


class RelationRow(Base):
    """A typed, directed link. Each end is either a record version or an entity.

    Two nullable foreign keys per end, with a CHECK that exactly one is set, give
    referential integrity without a polymorphic reference.
    """

    __tablename__ = "relations"
    __table_args__ = (
        CheckConstraint(
            "(from_version_id IS NULL) <> (from_entity_id IS NULL)", name="from_one_node"
        ),
        CheckConstraint("(to_version_id IS NULL) <> (to_entity_id IS NULL)", name="to_one_node"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    relation_type: Mapped[str] = mapped_column(String)
    from_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("record_versions.id"), nullable=True, index=True
    )
    from_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )
    to_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("record_versions.id"), nullable=True, index=True
    )
    to_entity_id: Mapped[str | None] = mapped_column(
        ForeignKey("entities.id"), nullable=True, index=True
    )


# NULLs are distinct inside a UNIQUE constraint, so identity is enforced on an
# index that maps NULL to an empty string.
_relations = RelationRow.__table__
Index(
    "ux_relations_identity",
    _relations.c.relation_type,
    func.coalesce(_relations.c.from_version_id, ""),
    func.coalesce(_relations.c.from_entity_id, ""),
    func.coalesce(_relations.c.to_version_id, ""),
    func.coalesce(_relations.c.to_entity_id, ""),
    unique=True,
)


class WorkItemRow(Base):
    __tablename__ = "work_items"
    __table_args__ = (
        CheckConstraint(_in_list("kind", WORK_ITEM_KINDS), name="kind_valid"),
        CheckConstraint(_in_list("status", WORK_ITEM_STATUSES), name="status_valid"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    kind: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, index=True)
    owner: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String, index=True)
    due_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


class WorkItemEvidenceRow(Base):
    __tablename__ = "work_item_evidence"

    work_item_id: Mapped[str] = mapped_column(ForeignKey("work_items.id"), primary_key=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("record_versions.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class EventRow(Base):
    """Append-only log. `seq` gives the order; triggers block UPDATE and DELETE."""

    __tablename__ = "events"
    __table_args__ = (
        Index("ix_events_subject", "subject_type", "subject_id", "seq"),
        {"sqlite_autoincrement": True},
    )

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime)
    type: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    subject_type: Mapped[str] = mapped_column(String)
    subject_id: Mapped[str] = mapped_column(String)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
