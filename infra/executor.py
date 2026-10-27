"""Trusted bootstrap inside a disposable, network-disabled repository job container."""

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path("/workspace")


def run(command, cwd, env):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=15)
    return {
        "argv": command,
        "exit_code": result.returncode,
        "stdout": result.stdout.decode("utf-8", "replace")[:100000],
        "stderr": result.stderr.decode("utf-8", "replace")[:100000],
    }


def main():
    body = json.load(sys.stdin)
    env = os.environ | {
        "GIT_AUTHOR_NAME": "TraceForge",
        "GIT_AUTHOR_EMAIL": "fixture@traceforge.local",
        "GIT_COMMITTER_NAME": "TraceForge",
        "GIT_COMMITTER_EMAIL": "fixture@traceforge.local",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONDONTWRITEBYTECODE": "1",
        "HOME": "/tmp",
    }
    source = ROOT / "repo"
    source.mkdir()
    for name, content in body["source"].items():
        (source / name).write_text(content, encoding="utf-8")
    setup = []
    for command in (
        ["git", "init", "--initial-branch=main", "--object-format=sha1"],
        ["git", "-c", "core.autocrlf=false", "add", "calculator.py", "test_calculator.py"],
        ["git", "-c", "commit.gpgsign=false", "commit", "-m", "Intentional addition regression"],
    ):
        setup.append(run(command, source, env))
        if setup[-1]["exit_code"]:
            print(json.dumps({"status": "SETUP_FAILED", "commands": setup}))
            return
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, env=env, text=True
    ).strip()
    if sha != body["commit_sha"]:
        print(json.dumps({"status": "SETUP_FAILED", "error": "Reconstructed commit mismatch"}))
        return
    protected_hash = hashlib.sha256((source / "test_calculator.py").read_bytes()).hexdigest()
    for name, content in body["changes"].items():
        (source / name).write_text(content, encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--tb=short",
        "--color=no",
        "-p",
        "no:cacheprovider",
    ]
    commands = [run([*command, "test_calculator.py"], source, env)]
    if body["mode"] == "verify":
        commands.append(run([*command, "/opt/checks/test_regression.py"], source, env))
        protected_ok = (
            hashlib.sha256((source / "test_calculator.py").read_bytes()).hexdigest()
            == protected_hash
        )
        status = (
            "PASSED" if protected_ok and all(c["exit_code"] == 0 for c in commands) else "FAILED"
        )
    else:
        status = (
            "REPRODUCED"
            if (
                commands[0]["exit_code"] == 1
                and "test_calculator.py::test_add_positive_numbers" in commands[0]["stdout"]
                and "assert -1 == 5" in commands[0]["stdout"]
            )
            else "NOT_REPRODUCED"
        )
        protected_ok = True
    print(
        json.dumps(
            {
                "status": status,
                "commands": commands,
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                    "commit_sha": sha,
                    "pytest": subprocess.check_output(
                        [sys.executable, "-m", "pytest", "--version"], text=True
                    ).strip(),
                    "git": subprocess.check_output(["git", "--version"], text=True).strip(),
                    "dependency_preparation": "Locked pytest installed at image build, no runtime downloads",
                    "setup_commands": setup,
                    "protected_files_unchanged": protected_ok,
                },
                "limitations": [
                    "Controlled calculator fixture only; passing these checks is not proof of general correctness."
                ],
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except subprocess.TimeoutExpired:
        print(json.dumps({"status": "TIMED_OUT", "error": "Individual approved command timed out"}))
