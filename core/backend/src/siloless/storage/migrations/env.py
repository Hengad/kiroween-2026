"""Alembic environment: runs migrations online against the configured URL."""

from alembic import context
from sqlalchemy import create_engine

from siloless.storage.models import Base

config = context.config
url = config.get_main_option("sqlalchemy.url")
assert url is not None, "sqlalchemy.url must be set"

engine = create_engine(url.replace("%%", "%"))
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
