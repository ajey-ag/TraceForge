import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Protocol


class ArtifactStore(Protocol):
    def put(self, content: bytes) -> str: ...
    def read(self, key: str) -> bytes: ...
    def probe(self) -> None: ...


class LocalArtifacts:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", key):
            raise ValueError("Artifact key must be a SHA-256 digest")
        path = (self.root / key[:2] / key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Artifact path escapes storage root")
        return path

    def put(self, content: bytes) -> str:
        key = hashlib.sha256(content).hexdigest()
        target = self._path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            self.read(key)  # Reconcile immutable results; detect corruption.
            return key
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                name = handle.name
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, target)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)
        return key

    def read(self, key: str) -> bytes:
        content = self._path(key).read_bytes()
        if hashlib.sha256(content).hexdigest() != key:
            raise ValueError("Artifact content hash mismatch")
        return content

    def probe(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=self.root) as handle:
            handle.write(b"ready")
            handle.flush()
