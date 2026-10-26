from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from packages.core.config import Settings

SCHEMA_REVISION = "0001_foundation"


def make_engine(settings: Settings):
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 3, "options": "-c statement_timeout=10000"},
    )


def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)


def check_database(engine) -> None:
    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if version != SCHEMA_REVISION:
            raise RuntimeError("Database migrations are not current")
