from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from packages.core.contracts import Stage
from packages.diagnosis.contracts import Diagnosis
from packages.models.providers import ProviderError
from packages.orchestration.runtime import BudgetExceeded


class State(TypedDict):
    report: object


def run_workflow(runtime, report, context):
    def diagnose(state):
        runtime.stage(Stage.DIAGNOSE, "Evidence-backed model diagnosis")
        try:
            result = runtime.model("diagnose", context)
            if result.get("error"):
                raise ProviderError(result["error"])
            diagnosis = Diagnosis.model_validate(result["payload"])
            diagnosis.validate_citations({e.id for e in report.evidence})
            report.diagnosis = diagnosis.model_dump(mode="json")
            if diagnosis.unsupported_explanation:
                report.outcome = "UNSUPPORTED"
        except BudgetExceeded as exc:
            report.outcome = "BUDGET_EXHAUSTED"
            report.limitations.append(str(exc))
        except (ValidationError, ValueError, ProviderError) as exc:
            report.diagnosis = {"status": "UNAVAILABLE", "reason": str(exc)[:1000]}
            report.limitations.append("Model diagnosis failed; saved evidence remains available.")
        return {"report": report}

    def repair(state):
        from packages.verification.workflow import repair_workflow

        if report.outcome not in {"BUDGET_EXHAUSTED", "UNSUPPORTED"}:
            repair_workflow(runtime, report, context)
        return {"report": report}

    graph = StateGraph(State)
    if runtime.policy["execution_policy"] == "reproduce":
        from packages.runner.client import run_execution

        def reproduce(state):
            runtime.stage(Stage.REPRODUCE, "Model-free controlled reproduction")
            result = run_execution(runtime, "reproduce")
            report.reproduction = result
            report.reproduction_status = result["status"]
            if result["status"] == "NOT_REPRODUCED":
                report.outcome = "NOT_REPRODUCED"
            elif result["status"] != "REPRODUCED":
                report.outcome = "NO_VERIFIED_REPAIR"
            return {"report": report}

        graph.add_node("reproduce", reproduce)
        graph.add_edge(START, "reproduce")
        graph.add_edge("reproduce", END)
        graph.compile().invoke({"report": report})
        report.summary = f"Controlled reproduction: {report.reproduction_status}; no patch requested."
        return report
    graph.add_node("diagnose", diagnose)
    graph.add_edge(START, "diagnose")
    if runtime.policy["execution_policy"] == "repair":
        graph.add_node("repair", repair)
        graph.add_edge("diagnose", "repair")
        graph.add_edge("repair", END)
    else:
        graph.add_edge("diagnose", END)
    graph.compile().invoke({"report": report})
    runtime.usage(report)
    report.summary = (
        f"{report.outcome}: {report.provider} provider; reproduction={report.reproduction_status}; "
        f"verification={report.verification_status}."
    )
    return report
