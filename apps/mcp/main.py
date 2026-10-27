import os
from typing import Literal
from uuid import UUID

import httpx
from mcp.server.fastmcp import FastMCP

from packages.tools.client import TraceForgeTools

mcp = FastMCP("TraceForge")


def tools():
    return httpx.Client(base_url=os.environ.get("TRACEFORGE_API_URL", "http://127.0.0.1:8000"), timeout=15)


@mcp.tool()
def read_report(investigation_id: UUID) -> dict:
    """Read a persisted failure/diagnosis/reproduction/verification report."""
    with tools() as client:
        return TraceForgeTools(client).report(investigation_id)


@mcp.tool()
def inspect_evidence(investigation_id: UUID, evidence_id: UUID) -> str:
    """Inspect cited logs, source, or metadata within one investigation."""
    with tools() as client:
        return TraceForgeTools(client).evidence(investigation_id, evidence_id)


@mcp.tool()
def inspect_patch(investigation_id: UUID, patch_id: UUID) -> str:
    """Retrieve a candidate's reviewable unified diff; not a host filesystem path."""
    with tools() as client:
        return TraceForgeTools(client).patch(investigation_id, patch_id)


@mcp.tool()
def request_reproduction(fixture_id: str = "calculator-add") -> dict:
    """Queue model-free reproduction of an explicitly supported owned fixture."""
    with tools() as client:
        return TraceForgeTools(client).submit({"fixture_id": fixture_id, "execution_policy": "reproduce"})


@mcp.tool()
def request_verified_repair(
    fixture_id: str = "calculator-add", provider: Literal["fake", "openai"] = "fake",
    strategy: Literal["cheap", "strong", "rule_based"] = "rule_based",
    max_model_calls: int = 3, max_spend_usd: float = 0,
) -> dict:
    """Queue a budgeted controlled repair including original reproduction and independent verification.

    Fake means deterministic demonstration. OpenAI needs credentials and a positive spend limit.
    This returns a job identity, never an immediate claim of verified repair.
    """
    with tools() as client:
        return TraceForgeTools(client).submit({
            "fixture_id": fixture_id, "execution_policy": "repair", "provider": provider,
            "strategy": strategy, "max_model_calls": max_model_calls, "max_spend_usd": max_spend_usd,
        })


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
