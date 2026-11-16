"""SQL read filters. Every query that returns protected data uses one of these.

They are the SQL counterpart of `Acl.allows`. Principal ids are always bound
parameters, never formatted into SQL text.
"""

from sqlalchemy import ColumnElement, and_, not_, or_, select, true
from sqlalchemy.orm import InstrumentedAttribute, aliased
from sqlalchemy.orm.util import AliasedClass

from siloless.access.principals import ResolvedPrincipal
from siloless.storage.models import (
    RecordRow,
    RecordVersionAclRow,
    RecordVersionRow,
    RelationRow,
    WorkItemEvidenceRow,
    WorkItemRow,
)


def record_version_readable(
    who: ResolvedPrincipal,
    version: type[RecordVersionRow] | AliasedClass[RecordVersionRow] = RecordVersionRow,
    record: type[RecordRow] | AliasedClass[RecordRow] = RecordRow,
) -> ColumnElement[bool]:
    """True for a version the principal may read.

    The principal must satisfy the version's own ACL and also the ACL of the Record's
    current version. So when a Source tightens access, people who lost access also
    lose every older version, and the current version is subject to one check only.
    """
    if who.is_system:
        return true()
    ids = sorted(who.ids)
    current_acl = aliased(RecordVersionAclRow)
    own_acl = aliased(RecordVersionAclRow)
    satisfies_own = (
        select(1).where(own_acl.version_id == version.id, own_acl.principal_id.in_(ids)).exists()
    )
    satisfies_current = (
        select(1)
        .where(
            current_acl.version_id == record.current_version_id, current_acl.principal_id.in_(ids)
        )
        .exists()
    )
    return and_(satisfies_own, satisfies_current)


def _endpoint_readable(
    who: ResolvedPrincipal,
    version_id: InstrumentedAttribute[str | None],
    entity_id: InstrumentedAttribute[str | None],
) -> ColumnElement[bool]:
    version = aliased(RecordVersionRow)
    record = aliased(RecordRow)
    record_readable = (
        select(1)
        .select_from(version)
        .join(record, record.id == version.record_id)
        .where(version.id == version_id, record_version_readable(who, version, record))
        .exists()
    )
    return or_(entity_id.is_not(None), record_readable)


def relation_readable(who: ResolvedPrincipal) -> ColumnElement[bool]:
    """True for a Relation whose Record endpoints the principal can both read.

    Entity endpoints are always readable, so a Relation between two Entities is
    visible to everyone."""
    if who.is_system:
        return true()
    return and_(
        _endpoint_readable(who, RelationRow.from_version_id, RelationRow.from_entity_id),
        _endpoint_readable(who, RelationRow.to_version_id, RelationRow.to_entity_id),
    )


def work_item_readable(who: ResolvedPrincipal) -> ColumnElement[bool]:
    """True for a Work Item the principal may read.

    Its creator and its owner can always read it. Anyone else can read it only if it
    has evidence and they can read every Record version it cites. An item with no
    evidence is therefore private to its creator and owner."""
    if who.is_system:
        return true()
    has_evidence = select(1).where(WorkItemEvidenceRow.work_item_id == WorkItemRow.id).exists()
    unreadable_evidence = (
        select(1)
        .select_from(WorkItemEvidenceRow)
        .join(RecordVersionRow, RecordVersionRow.id == WorkItemEvidenceRow.version_id)
        .join(RecordRow, RecordRow.id == RecordVersionRow.record_id)
        .where(
            WorkItemEvidenceRow.work_item_id == WorkItemRow.id,
            not_(record_version_readable(who)),
        )
        .exists()
    )
    return or_(
        WorkItemRow.created_by == who.id,
        WorkItemRow.owner == who.id,
        and_(has_evidence, not_(unreadable_evidence)),
    )
