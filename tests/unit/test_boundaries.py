from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apps.api.main import create_app
from packages.artifacts.local import LocalArtifacts
from packages.core.config import Settings
from packages.core.contracts import Stage, Status, Submission
from packages.ingestion.fixtures import load_fixture
from packages.persistence.lifecycle import transition
from packages.persistence.models import Investigation


@pytest.mark.parametrize(
    "identifier", ["../calculator-add", "calculator-add/..", "C:\\secret", "unknown"]
)
def test_fixture_lookup_rejects_unregistered_paths(identifier):
    with pytest.raises(KeyError):
        load_fixture(identifier)


def test_artifact_integrity_and_traversal(tmp_path):
    store = LocalArtifacts(tmp_path)
    key = store.put(b"original evidence")
    assert store.put(b"original evidence") == key
    assert store.read(key) == b"original evidence"
    with pytest.raises(ValueError):
        store.read("../../secret")
    (tmp_path / key[:2] / key).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="hash mismatch"):
        store.read(key)


def test_no_execution_or_spend_can_be_requested():
    for body in ({"max_spend_usd": 1}, {"max_model_calls": 1}, {"command": "anything"}):
        with pytest.raises(ValidationError):
            Submission(fixture_id="calculator-add", **body)
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///not-postgres.db")


def test_terminal_state_cannot_be_reopened():
    row = Investigation(id=uuid4(), status="COMPLETED")
    with pytest.raises(ValueError, match="Invalid transition"):
        transition(None, row, Status.RUNNING, Stage.INGEST, "invalid")


def test_health_independent_of_database_and_readiness_fails(tmp_path):
    settings = Settings(
        database_url="postgresql+psycopg://none:none@127.0.0.1:1/none",
        artifact_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 503
        assert client.post("/investigations", json={"fixture_id": "unknown"}).status_code == 404
        assert client.post("/investigations", json={"fixture_id": "../secret"}).status_code == 422
