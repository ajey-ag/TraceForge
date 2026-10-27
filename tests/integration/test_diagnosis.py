from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from apps.api.main import create_app
from apps.worker.main import run_once
from packages.artifacts.local import LocalArtifacts
from packages.models.providers import FakeProvider, ModelResult, ProviderError
from packages.persistence.models import Operation

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("failure", [None, "malformed", "citation", "timeout"])
def test_grounded_diagnosis_and_recoverable_failures(db, postgres_settings, monkeypatch, failure):
    if failure:
        original = FakeProvider.generate

        def broken(self, task, context, model):
            if failure == "timeout":
                raise ProviderError("Provider request/output failed: ReadTimeout")
            if failure == "malformed":
                return ModelResult({"bad": "schema"})
            result = original(self, task, context, model)
            result.payload["observed_facts"][0]["evidence_ids"] = [
                "00000000-0000-0000-0000-000000000000"
            ]
            return result

        monkeypatch.setattr(FakeProvider, "generate", broken)
    with TestClient(create_app(postgres_settings)) as client:
        response = client.post(
            "/investigations",
            json={
                "fixture_id": "calculator-add",
                "execution_policy": "diagnose",
                "max_model_calls": 1,
            },
        )
        assert response.status_code == 202
        identity = response.json()["id"]
        run_once(
            db, LocalArtifacts(postgres_settings.artifact_root), postgres_settings, "diagnoser"
        )
        report = client.get(f"/investigations/{identity}/report").json()
        assert report["provider"] == "fake"
        assert report["model_calls"] == 1
        assert report["patch_status"] == "NOT_PROPOSED"
        if failure:
            assert report["diagnosis"]["status"] == "UNAVAILABLE"
        else:
            known = {e["id"] for e in report["evidence"]}
            for fact in report["diagnosis"]["observed_facts"]:
                assert set(fact["evidence_ids"]) <= known
    with db() as session:
        call = session.scalar(select(Operation).where(Operation.investigation_id == UUID(identity)))
        assert call.result is not None
        assert call.request["prompt_version"] == "grounded-engineer-v1"
