from fastapi import APIRouter

from siloless.api.deps import ContainerDep, PrincipalDep
from siloless.api.schemas import RecordVersionOut

router = APIRouter(tags=["records"])


@router.get("/records/{record_id}")
def get_record(record_id: str, who: PrincipalDep, container: ContainerDep) -> RecordVersionOut:
    """The current version of a Record."""
    return RecordVersionOut.from_domain(container.reader.get_current(who, record_id))


@router.get("/records/{record_id}/versions")
def list_record_versions(
    record_id: str, who: PrincipalDep, container: ContainerDep
) -> list[RecordVersionOut]:
    """Every version you may read, newest first. The newest has `is_current` set."""
    return [
        RecordVersionOut.from_domain(version)
        for version in container.reader.list_versions(who, record_id)
    ]


@router.get("/record-versions/{version_id}")
def get_record_version(
    version_id: str, who: PrincipalDep, container: ContainerDep
) -> RecordVersionOut:
    return RecordVersionOut.from_domain(container.reader.get_version(who, version_id))
