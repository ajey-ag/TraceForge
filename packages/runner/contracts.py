from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    fixture_id: Literal["calculator-add"]
    mode: Literal["reproduce", "verify"]
    changes: dict[str, str] = Field(default_factory=dict, max_length=1)
    timeout_seconds: int = Field(default=30, ge=1, le=60)


class ExecutionResult(BaseModel):
    status: Literal[
        "RUNNING",
        "REPRODUCED",
        "NOT_REPRODUCED",
        "PASSED",
        "FAILED",
        "SETUP_FAILED",
        "TIMED_OUT",
        "OUTPUT_LIMIT",
        "CANCELLED",
        "INTERRUPTED",
    ]
    environment: dict = Field(default_factory=dict)
    commands: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
