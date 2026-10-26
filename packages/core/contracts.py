from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Status(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    NEEDS_INPUT = "NEEDS_INPUT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Stage(StrEnum):
    INGEST = "INGEST"
    DIAGNOSE = "DIAGNOSE"
    REPRODUCE = "REPRODUCE"
    PROPOSE_PATCH = "PROPOSE_PATCH"
    VERIFY = "VERIFY"
    REPORT = "REPORT"


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["fixture"] = "fixture"
    fixture_id: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    execution_policy: Literal["saved_evidence_only"] = "saved_evidence_only"
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_model_calls: Literal[0] = 0
    max_spend_usd: Literal[0] = 0


class TraceEntry(BaseModel):
    path: str
    line: int
    context: str | None = None


class Failure(BaseModel):
    test_id: str | None
    exception_type: str | None
    message: str | None
    traceback: list[TraceEntry] = Field(default_factory=list)


class ParsedLog(BaseModel):
    failure_category: Literal[
        "APPLICATION_CODE_REGRESSION",
        "DEPENDENCY_OR_IMPORT_FAILURE",
        "TEST_OR_ENVIRONMENT_CONFIGURATION",
        "UNKNOWN_OR_UNSUPPORTED",
    ]
    failed_test_identifiers: list[str]
    failures: list[Failure]
    limitations: list[str]


class EvidenceRef(BaseModel):
    id: UUID
    type: str
    sha256: str
    artifact: str


class Report(BaseModel):
    schema_version: Literal["1"] = "1"
    investigation_id: UUID
    source: Literal["fixture"] = "fixture"
    fixture_id: str
    commit_sha: str
    outcome: Literal["DIAGNOSED", "UNSUPPORTED"]
    summary: str
    parsed: ParsedLog
    evidence: list[EvidenceRef]
    reproduction_status: Literal["NOT_RUN_SAVED_LOG_ONLY"] = "NOT_RUN_SAVED_LOG_ONLY"
    patch_status: Literal["NOT_PROPOSED"] = "NOT_PROPOSED"
    verification_status: Literal["NOT_RUN"] = "NOT_RUN"
    model_calls: Literal[0] = 0
    observed_model_cost_usd: Literal[0] = 0
