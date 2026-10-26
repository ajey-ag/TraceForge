"""Conservative parser for pytest short/long tracebacks and short summaries."""

import re

from packages.core.contracts import Failure, ParsedLog, TraceEntry

PARSER_VERSION = "pytest-text-v1"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
SUMMARY = re.compile(r"^(FAILED|ERROR) (\S+)(?: - (.*))?$", re.MULTILINE)
FRAME = re.compile(r"^(.+?\.py):(\d+):\s*(.*)$", re.MULTILINE)
EXCEPTION = re.compile(
    r"^E\s+([\w.]+(?:Error|Exception)|Failed|SystemExit):?\s*(.*)$", re.MULTILINE
)
SECTION = re.compile(r"^_{3,}\s+(.+?)\s+_{3,}$", re.MULTILINE)


def parse_pytest_log(text: str) -> ParsedLog:
    text = ANSI.sub("", text.replace("\r\n", "\n"))
    limitations = [
        "Deterministic text parsing only; category is a heuristic, not a proven root cause.",
        "Saved fixture evidence was parsed; this investigation did not execute tests.",
    ]
    summaries = list(SUMMARY.finditer(text))
    sections = list(SECTION.finditer(text))
    failures = []
    for summary in summaries:
        test_id, message = summary.group(2), summary.group(3)
        # Associate blocks by test name, never assign a global exception to every test.
        leaf = test_id.split("::")[-1]
        candidates = [
            i
            for i, section in enumerate(sections)
            if section.group(1).split(".")[-1] == leaf
            or section.group(1) == f"ERROR collecting {test_id}"
            or section.group(1) in {f"ERROR at setup of {leaf}", f"ERROR at teardown of {leaf}"}
        ]
        block = ""
        if len(candidates) == 1:
            index = candidates[0]
            end = sections[index + 1].start() if index + 1 < len(sections) else summary.start()
            block = text[sections[index].end() : end]
        else:
            limitations.append(f"No unambiguous traceback section for {test_id}.")
        exceptions = list(EXCEPTION.finditer(block))
        exception_type = None
        if exceptions:
            exception_type, message = exceptions[-1].group(1, 2)
        elif re.search(r"^E\s+assert\b", block, re.MULTILINE) or (message or "").startswith(
            "assert "
        ):
            exception_type = "AssertionError"
        elif message:
            match = re.match(r"([\w.]+(?:Error|Exception)|Failed|SystemExit):\s*(.*)", message)
            if match:
                exception_type, message = match.group(1, 2)
        frames = [
            TraceEntry(path=m.group(1), line=int(m.group(2)), context=m.group(3) or None)
            for m in FRAME.finditer(block)
        ]
        failures.append(
            Failure(
                test_id=test_id,
                exception_type=exception_type,
                message=message,
                traceback=frames,
            )
        )
    types = {failure.exception_type for failure in failures}
    category = "UNKNOWN_OR_UNSUPPORTED"
    if types & {"ModuleNotFoundError", "ImportError"}:
        category = "DEPENDENCY_OR_IMPORT_FAILURE"
    elif "fixture '" in text and "not found" in text:
        category = "TEST_OR_ENVIRONMENT_CONFIGURATION"
    elif "ERROR: usage:" in text or "ERROR: file or directory not found:" in text:
        category = "TEST_OR_ENVIRONMENT_CONFIGURATION"
    elif failures and all(f.exception_type == "AssertionError" for f in failures):
        category = "APPLICATION_CODE_REGRESSION"
    if not summaries:
        limitations.append(
            "No pytest short failure summary found; log may be truncated/unsupported."
        )
    if any(f.exception_type is None for f in failures):
        limitations.append("Some exception types could not be extracted.")
    return ParsedLog(
        failure_category=category,
        failed_test_identifiers=list(dict.fromkeys(f.test_id for f in failures if f.test_id)),
        failures=failures,
        limitations=limitations,
    )
