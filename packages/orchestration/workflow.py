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
