"""Run Alembic migrations from code, without an alembic.ini file."""

from pathlib import Path

from alembic import command
from alembic.config import Config

_SCRIPT_LOCATION = Path(__file__).parent / "migrations"


def _config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    # Alembic reads the URL through configparser, where a literal % must be doubled.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Bring the database at `url` up to `revision`. A database created by the
    application without migrations is adopted: nothing in it changes."""
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(_config(url), revision)
