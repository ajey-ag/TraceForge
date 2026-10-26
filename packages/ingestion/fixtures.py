import hashlib
from dataclasses import dataclass
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# An explicit registry, never a user-supplied filesystem path.
FIXTURE_IDS = ("calculator-add",)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    repository: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    test_command: list[str]
    setup_command: list[str]
    expected_exit_code: int
    expected_failure: str
    expected_outcome: Literal["DIAGNOSED"]
    log_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provenance: str
    python_version: str
    pytest_version: str
    platform: str


@dataclass(frozen=True)
class Fixture:
    manifest: Manifest
    manifest_bytes: bytes
    log: bytes


def load_fixture(identifier: str) -> Fixture:
    if identifier not in FIXTURE_IDS:
        raise KeyError(f"Unknown fixture '{identifier}'. Available: {', '.join(FIXTURE_IDS)}")
    root = files("benchmarks").joinpath("fixtures", identifier)
    manifest_bytes = root.joinpath("manifest.json").read_bytes()
    manifest = Manifest.model_validate_json(manifest_bytes)
    log = root.joinpath("pytest.txt").read_bytes()
    if manifest.id != identifier or hashlib.sha256(log).hexdigest() != manifest.log_sha256:
        raise ValueError("Fixture identity or log content hash mismatch")
    if len(log) > 2_000_000:
        raise ValueError("Fixture log exceeds 2 MB ingestion limit")
    return Fixture(manifest, manifest_bytes, log)
