import io
import json
import re
import zipfile
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from packages.core.config import Settings

MAX_LOG_BYTES = 2_000_000


class GitHubRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", max_length=200)
    run_id: int = Field(gt=0)
    attempt: int = Field(default=1, ge=1, le=100)


class GitHubError(Exception):
    pass


def allowed_repository(settings: Settings, repository: str):
    allowed = {
        name.strip().lower() for name in settings.github_repositories.split(",") if name.strip()
    }
    if repository.lower() not in allowed:
        raise GitHubError("Repository is not configured in TRACEFORGE_GITHUB_REPOSITORIES")


def unpack_logs(content: bytes) -> str:
    if len(content) > MAX_LOG_BYTES:
        raise GitHubError("Log archive exceeds controlled ingestion size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 1000 or sum(item.file_size for item in entries) > MAX_LOG_BYTES:
                raise GitHubError("Expanded logs exceed controlled ingestion size limit")
            output = []
            for entry in sorted(entries, key=lambda item: item.filename):
                if not entry.is_dir():
                    # No extraction onto the filesystem, including malicious archive paths.
                    text = archive.read(entry).decode("utf-8", "replace")
                    text = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z\s+", "", text, flags=re.MULTILINE)
                    output.append(f"Log entry: {entry.filename}\n{text}")
            return "\n".join(output)
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise GitHubError("GitHub returned an unreadable log archive") from exc


def download_run(settings: Settings, request: GitHubRun) -> dict:
    allowed_repository(settings, request.repository)
    if not settings.github_token or not settings.github_token.get_secret_value():
        raise GitHubError("GitHub token is not configured")
    headers = {
        "Authorization": f"Bearer {settings.github_token.get_secret_value()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    path = f"/repos/{request.repository}/actions/runs/{request.run_id}/attempts/{request.attempt}"
    try:
        with httpx.Client(
            base_url="https://api.github.com", headers=headers, timeout=30, trust_env=False
        ) as client:
            response = client.get(path)
            response.raise_for_status()
            metadata = response.json()
            if metadata.get("status") != "completed" or metadata.get("conclusion") not in {
                "failure",
                "timed_out",
            }:
                raise GitHubError("Expected a completed failed workflow run")
            commit = metadata.get("head_sha", "")
            if not re.fullmatch(r"[0-9a-f]{40}", commit):
                raise GitHubError("Workflow run is missing an exact commit SHA")
            source_repo = (metadata.get("head_repository") or {}).get("full_name")
            if not source_repo:
                raise GitHubError("Workflow run is missing its source repository")
            logs = client.get(path + "/logs", follow_redirects=False)
            if logs.status_code in {404, 410}:
                raise GitHubError("Workflow logs are missing or expired")
            if logs.status_code not in {301, 302, 307}:
                logs.raise_for_status()
                archive = logs.content
            else:
                url = logs.headers.get("location", "")
                parsed = urlparse(url)
                if parsed.scheme != "https" or not parsed.hostname or parsed.username:
                    raise GitHubError("Invalid log download redirect")
                # Signed storage URL receives no GitHub Authorization header.
                with httpx.stream("GET", url, timeout=30, trust_env=False) as stream:
                    stream.raise_for_status()
                    archive = bytearray()
                    for chunk in stream.iter_bytes():
                        archive.extend(chunk)
                        if len(archive) > MAX_LOG_BYTES:
                            raise GitHubError("Log download exceeds size limit")
            return {
                "log": unpack_logs(bytes(archive)),
                "metadata": {
                    "repository": source_repo,
                    "workflow_repository": request.repository,
                    "commit_sha": commit,
                    "run_id": request.run_id,
                    "attempt": request.attempt,
                    "url": metadata.get("html_url"),
                    "conclusion": metadata.get("conclusion"),
                    "collection": "GitHub REST workflow attempt metadata/logs",
                },
            }
    except httpx.HTTPStatusError as exc:
        raise GitHubError(
            f"GitHub HTTP {exc.response.status_code}; check token permissions/run visibility"
        ) from exc
    except httpx.HTTPError as exc:
        raise GitHubError(f"GitHub connection failed: {type(exc).__name__}") from exc


def encoded_metadata(result: dict) -> bytes:
    return json.dumps(result["metadata"], sort_keys=True).encode()
