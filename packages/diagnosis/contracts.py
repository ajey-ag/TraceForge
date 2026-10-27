from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=1, max_length=20)


class Hypothesis(Fact):
    rank: int = Field(ge=1, le=10)
    missing_or_contradictory_evidence: list[str] = Field(default_factory=list, max_length=10)


class Diagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_facts: list[Fact] = Field(min_length=1, max_length=20)
    hypotheses: list[Hypothesis] = Field(max_length=10)
    recommended_action: str = Field(min_length=1, max_length=2000)
    unsupported_explanation: str | None = None

    def validate_citations(self, known: set[UUID]) -> None:
        for item in [*self.observed_facts, *self.hypotheses]:
            if not set(item.evidence_ids) <= known:
                raise ValueError("Model cited nonexistent evidence")
        ranks = [h.rank for h in self.hypotheses]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("Hypotheses must have distinct consecutive ranks")


class FileChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=20000)


class PatchProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str = Field(min_length=1, max_length=2000)
    files: list[FileChange] = Field(min_length=1, max_length=5)
