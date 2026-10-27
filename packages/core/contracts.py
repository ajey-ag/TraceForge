from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    execution_policy: Literal["saved_evidence_only", "diagnose", "repair"] = "saved_evidence_only"
    max_attempts: int = Field(default=3, ge=1, le=10)
    max_model_calls: int = Field(default=0, ge=0, le=10)
    max_spend_usd: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)
    provider: Literal["fake", "openai"] = "fake"
    strategy: Literal["cheap", "strong", "rule_based"] = "rule_based"
    repair_attempts: int = Field(default=2, ge=1, le=3)

    @model_validator(mode="after")
    def validate_policy(self):
        if self.execution_policy == "saved_evidence_only" and (
            self.max_model_calls or self.max_spend_usd
        ):
            raise ValueError("Saved-evidence policy cannot request model calls or spend")
        if self.execution_policy != "saved_evidence_only" and self.max_model_calls < 1:
            raise ValueError("Diagnosis/repair requires an explicit positive model-call budget")
        if self.provider == "openai" and self.max_spend_usd <= 0:
            raise ValueError("OpenAI requires an explicit positive spend budget")
        return self


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
    source: Literal["fixture", "github"] = "fixture"
    fixture_id: str
    commit_sha: str
    outcome: Literal[
        "DIAGNOSED",
        "UNSUPPORTED",
        "VERIFIED_REPAIR",
        "NO_VERIFIED_REPAIR",
        "NOT_REPRODUCED",
        "BUDGET_EXHAUSTED",
    ]
    summary: str
    parsed: ParsedLog
    evidence: list[EvidenceRef]
    reproduction_status: str = "NOT_RUN_SAVED_LOG_ONLY"
    patch_status: str = "NOT_PROPOSED"
    verification_status: str = "NOT_RUN"
    model_calls: int = 0
    observed_model_cost_usd: float | None = 0
    estimated_model_cost_usd: float = 0
    provider: str | None = None
    diagnosis: dict | None = None
    reproduction: dict | None = None
    patches: list[dict] = Field(default_factory=list)
    verification: list[dict] = Field(default_factory=list)
    routing: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
