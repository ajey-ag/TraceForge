import os
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from packages.core.config import Settings
from packages.persistence.database import make_engine, session_factory


@pytest.fixture(scope="session")
def postgres_settings(tmp_path_factory):
    url = os.environ.get("TRACEFORGE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TRACEFORGE_TEST_DATABASE_URL to run real PostgreSQL integration checks")
    # Create a disposable database; never truncate the supplied development database.
    admin = create_engine(url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 5})
    database = f"traceforge_test_{uuid4().hex}"
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    test_url = make_url(url).set(database=database).render_as_string(hide_password=False)
    settings = Settings(database_url=test_url, artifact_root=tmp_path_factory.mktemp("artifacts"))
    previous = os.environ.get("TRACEFORGE_DATABASE_URL")
    os.environ["TRACEFORGE_DATABASE_URL"] = test_url
    try:
        command.upgrade(Config("alembic.ini"), "head")
        yield settings
    finally:
        if previous is None:
            os.environ.pop("TRACEFORGE_DATABASE_URL", None)
        else:
            os.environ["TRACEFORGE_DATABASE_URL"] = previous
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def db(postgres_settings):
    engine = make_engine(postgres_settings)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE investigations CASCADE"))
    yield session_factory(engine)
    engine.dispose()
