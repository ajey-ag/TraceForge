from uuid import uuid4

import pytest
from pydantic import ValidationError

from packages.core.config import Settings
from packages.diagnosis.contracts import Diagnosis
from packages.models.providers import FakeProvider, OpenAIProvider, ProviderError


def test_fake_provider_citations_are_validated():
    identity = uuid4()
    result = FakeProvider().generate(
        "diagnose",
        {
            "evidence": [{"id": str(identity), "type": "PYTEST_LOG"}],
        },
        "fake-cheap-v1",
    )
    diagnosis = Diagnosis.model_validate(result.payload)
    diagnosis.validate_citations({identity})
    with pytest.raises(ValueError, match="nonexistent"):
        diagnosis.validate_citations({uuid4()})


def test_malformed_diagnosis_is_rejected():
    with pytest.raises(ValidationError):
        Diagnosis.model_validate({"hypotheses": "trust me"})


def test_real_provider_missing_credentials_is_recoverable():
    with pytest.raises(ProviderError, match="credentials"):
        OpenAIProvider(Settings(openai_api_key=None)).generate("diagnose", {}, "gpt-4.1-mini")
