import math
from statistics import median


def summarize(records: list[dict]) -> dict:
    count = len(records)
    success = sum(row.get("outcome") == "VERIFIED_REPAIR" for row in records)
    reproduced = sum(row.get("reproduction_status") == "REPRODUCED" for row in records)
    costs = sum(row.get("estimated_model_cost_usd", 0) for row in records)
    latencies = sorted(row["wall_seconds"] for row in records)
    unsupported = sum(row.get("outcome") == "UNSUPPORTED" for row in records)
    regressions = sum(any(
        run.get("commands", [{}])[0].get("exit_code") == 0
        and any(c.get("exit_code") != 0 for c in run.get("commands", [])[1:])
        for run in row.get("verification", []) if run.get("commands")
    ) for row in records)
    return {
        "tasks": count, "verified_repairs": success,
        "verified_repair_rate": success / count if count else None,
        "reproduction_rate": reproduced / count if count else None,
        "unsupported_rate": unsupported / count if count else None,
        "unresolved_rate": (count - success - unsupported) / count if count else None,
        "regression_rate": regressions / count if count else None,
        "total_estimated_model_cost_usd": costs,
        "estimated_cost_per_verified_repair_usd": costs / success if success else None,
        "model_calls": sum(row.get("model_calls", 0) for row in records),
        "median_seconds": median(latencies) if latencies else None,
        "p95_seconds": latencies[max(0, math.ceil(count * .95) - 1)] if latencies else None,
    }
