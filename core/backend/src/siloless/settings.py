"""Engine settings, read from SILOLESS_* environment variables and `.env`."""

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BUILTIN_RELATION_TYPES: tuple[str, ...] = (
    "mentions",
    "about",
    "caused_by",
    "resolves",
    "answers",
    "supersedes",
    "duplicate_of",
    "located_at",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SILOLESS_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///siloless.db"
    max_record_bytes: int = 262144
    max_query_length: int = 256
    authoritative_sources: list[str] = []
    authoritative_kinds: list[str] = []
    entity_types: list[str] = []
    relation_types: list[str] = list(BUILTIN_RELATION_TYPES)

    @field_validator("relation_types")
    @classmethod
    def _always_include_builtin_types(cls, value: list[str]) -> list[str]:
        merged = list(BUILTIN_RELATION_TYPES)
        merged.extend(item for item in value if item not in merged)
        return merged
