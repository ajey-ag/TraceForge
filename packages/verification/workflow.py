from uuid import uuid5

from pydantic import ValidationError

from packages.core.contracts import Stage
from packages.diagnosis.contracts import PatchProposal
from packages.models.providers import ProviderError
from packages.orchestration.runtime import BudgetExceeded
from packages.persistence.models import PatchCandidate, VerificationRun
from packages.persistence.queue import owned_job
from packages.runner.client import run_execution
from packages.verification.patches import validate_patch


def repair_workflow(runtime, report, context):
    runtime.stage(Stage.REPRODUCE, "Reproduce exact controlled commit in isolated Linux container")
    baseline = run_execution(runtime, "reproduce")
    report.reproduction = baseline
    report.reproduction_status = baseline["status"]
    if baseline["status"] != "REPRODUCED":
        report.outcome = (
            "NOT_REPRODUCED" if baseline["status"] == "NOT_REPRODUCED" else "NO_VERIFIED_REPAIR"
        )
        report.limitations.append("Original failure was not reproduced; no patch was verified.")
        return
    feedback = None
    original = {path: entry["text"] for path, entry in context["source"].items()}
    for attempt in range(runtime.policy["repair_attempts"]):
        runtime.stage(Stage.PROPOSE_PATCH, f"Generate candidate {attempt + 1}")
        try:
            result = runtime.model("patch", context, attempt=attempt, feedback=feedback)
            if result.get("error"):
                raise ProviderError(result["error"])
            proposal = PatchProposal.model_validate(result["payload"])
            changes, diff = validate_patch(proposal, original)
        except BudgetExceeded as exc:
            report.outcome = "BUDGET_EXHAUSTED"
            report.limitations.append(str(exc))
            return
        except (ValueError, SyntaxError, ValidationError, ProviderError) as exc:
            report.patches.append(
                {"attempt": attempt + 1, "status": "REJECTED", "reason": str(exc)[:1000]}
            )
            feedback = {"patch_rejected": str(exc)[:1000]}
            continue
        identity = uuid5(runtime.claim.investigation_id, f"patch:{attempt}")
        artifact = runtime.store.put(diff.encode())
        candidate = {
            "id": str(identity),
            "attempt": attempt + 1,
            "artifact": artifact,
            "changed_files": list(changes),
            "status": "PROPOSED",
            "explanation": proposal.explanation,
        }
        with runtime.sessions.begin() as session:
            owned_job(session, runtime.claim)
            if session.get(PatchCandidate, identity) is None:
                session.add(
                    PatchCandidate(
                        id=identity,
                        investigation_id=runtime.claim.investigation_id,
                        parent_commit=report.commit_sha,
                        artifact=artifact,
                        changed_files=list(changes),
                        attempt=attempt + 1,
                        status="PROPOSED",
                    )
                )
        report.patch_status = "PROPOSED"
        runtime.stage(
            Stage.VERIFY,
            "Independent fresh workspace: original targeted test and external regression checks",
        )
        verification = run_execution(runtime, "verify", changes, attempt)
        verification["patch_id"] = str(identity)
        verification["original_failure_reproduced"] = True
        verification["protected_path_validation"] = "PASSED"
        passed = verification["status"] == "PASSED"
        candidate["status"] = "VERIFIED" if passed else "UNSUCCESSFUL"
        report.patches.append(candidate)
        report.verification.append(verification)
        with runtime.sessions.begin() as session:
            owned_job(session, runtime.claim)
            session.get(PatchCandidate, identity).status = candidate["status"]
            verification_id = uuid5(identity, "verification")
            if session.get(VerificationRun, verification_id) is None:
                session.add(
                    VerificationRun(
                        id=verification_id,
                        patch_id=identity,
                        investigation_id=runtime.claim.investigation_id,
                        payload=verification,
                    )
                )
        if passed:
            report.outcome = "VERIFIED_REPAIR"
            report.patch_status = "VERIFIED"
            report.verification_status = "PASSED_TARGETED_AND_CONTROLLED_REGRESSION"
            report.limitations.append(
                "Verified only against the original test and seven external calculator checks."
            )
            return
        feedback = verification
    report.outcome = "NO_VERIFIED_REPAIR"
    report.verification_status = "NO_PASSING_CANDIDATE"
