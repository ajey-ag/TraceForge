from uuid import UUID

from packages.core.contracts import Submission


class TraceForgeTools:
    """MCP/internal adapter over the same validated HTTP boundary and durable jobs."""

    def __init__(self, client):
        self.client = client

    def submit(self, body: dict):
        validated = Submission.model_validate(body)
        response = self.client.post("/investigations", json=validated.model_dump())
        response.raise_for_status()
        return response.json()

    def report(self, investigation_id: UUID):
        response = self.client.get(f"/investigations/{investigation_id}/report")
        response.raise_for_status()
        return response.json()

    def evidence(self, investigation_id: UUID, evidence_id: UUID):
        response = self.client.get(f"/investigations/{investigation_id}/evidence/{evidence_id}")
        response.raise_for_status()
        return response.text

    def patch(self, investigation_id: UUID, patch_id: UUID):
        response = self.client.get(f"/investigations/{investigation_id}/patches/{patch_id}")
        response.raise_for_status()
        return response.text
