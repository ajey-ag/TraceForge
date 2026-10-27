"""Reconstruct the owned fixture commit and explicitly run its failing test.

This developer utility is not the isolated execution runner planned for Phase 3.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURE = Path(__file__).parent / "fixtures" / "calculator-add"
COMMAND = ["python", "-m", "pytest", "-q", "--tb=short", "--color=no", "test_calculator.py"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="store_true", help="Regenerate manifest and saved log")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="traceforge-fixture-") as directory:
        root = Path(directory)
        for source in (FIXTURE / "source").glob("*.py"):
            # Canonical bytes ensure the reconstructed commit is stable across OSes.
            (root / source.name).write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        env = os.environ | {
            "GIT_AUTHOR_NAME": "TraceForge",
            "GIT_AUTHOR_EMAIL": "fixture@traceforge.local",
            "GIT_COMMITTER_NAME": "TraceForge",
            "GIT_COMMITTER_EMAIL": "fixture@traceforge.local",
            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
            "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONHASHSEED": "0",
        }
        for command in (
            ["git", "init", "--initial-branch=main", "--object-format=sha1"],
            ["git", "-c", "core.autocrlf=false", "add", "calculator.py", "test_calculator.py"],
            [
                "git",
                "-c",
                "commit.gpgsign=false",
                "commit",
                "-m",
                "Intentional addition regression",
            ],
        ):
            subprocess.run(command, cwd=root, env=env, check=True, capture_output=True)
        sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, env=env, text=True
        ).strip()
        if not args.record:
            manifest = json.loads((FIXTURE / "manifest.json").read_text())
            if sha != manifest["commit_sha"]:
                raise RuntimeError(f"Fixture source drift: reconstructed {sha}")
        result = subprocess.run(
            [sys.executable, *COMMAND[1:]],
            cwd=root,
            env=env,
            capture_output=True,
            timeout=30,
        )
        # Saved evidence uses canonical LF so a fresh Windows/Linux checkout retains its hash.
        output = (result.stdout + result.stderr).replace(b"\r\n", b"\n")
        sys.stdout.buffer.write(output)
        if args.record:
            if result.returncode != 1 or b"assert -1 == 5" not in output:
                raise RuntimeError("Expected assertion failure was not reproduced")
            (FIXTURE / "pytest.txt").write_bytes(output)
            manifest = {
                "id": "calculator-add",
                "repository": "owned-fixture://calculator-add",
                "commit_sha": sha,
                "test_command": COMMAND,
                "setup_command": [],
                "expected_exit_code": 1,
                "expected_failure": "test_calculator.py::test_add_positive_numbers: AssertionError",
                "expected_outcome": "DIAGNOSED",
                "log_sha256": hashlib.sha256(output).hexdigest(),
                "provenance": "Original synthetic fixture authored for TraceForge; CC0-1.0",
                "python_version": sys.version.split()[0],
                "pytest_version": subprocess.check_output(
                    [sys.executable, "-m", "pytest", "--version"],
                    text=True,
                ).strip(),
                "platform": sys.platform,
            }
            (FIXTURE / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
            )
        return result.returncode


if __name__ == "__main__":
    if not shutil.which("git"):
        raise SystemExit("Git is required to reconstruct the fixture commit")
    raise SystemExit(main())
