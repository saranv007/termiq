"""
Safe, approval-based execution engine for TERMIQ.

Security design:
- Server-side allowlist maps action types to fixed (executable, args) pairs.
- No shell=True, no bash -c, no eval, no arbitrary commands.
- Approval is bound to (plan_id, action_id) and consumed on first use.
- Approvals expire after APPROVAL_TTL_SECONDS.
- Only RiskLevel.SAFE (read-only) actions can execute in v1.
- Output is capped at MAX_OUTPUT_BYTES.
- Commands run with a fixed timeout, restricted env, and /tmp cwd.
- Full audit trail for every state transition.
"""

import logging
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models import (
    ActionType,
    AuditEntry,
    PlanStatus,
    ProposedAction,
    RiskLevel,
    TroubleshootingPlan,
)

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────
APPROVAL_TTL_SECONDS = 300        # 5 minutes
COMMAND_TIMEOUT_SECONDS = 15
MAX_OUTPUT_BYTES = 8192

# ── Server-side command allowlist ──────────────────────────────────────
# Security: each entry maps an ActionType to a fixed (executable, args)
# tuple.  No user input is interpolated into arguments.  Entries are
# tuples, not strings, so subprocess receives a list — never a shell
# command line.
COMMAND_ALLOWLIST: dict[ActionType, tuple[str, ...]] = {
    ActionType.CHECK_UPTIME: ("/usr/bin/uptime",),
    ActionType.CHECK_MEMORY: ("/usr/bin/free", "-h"),
    ActionType.CHECK_DISK: ("/usr/bin/df", "-h", "/"),
    ActionType.CHECK_PROCESSES: ("/usr/bin/ps", "aux", "--sort=-pcpu"),
    ActionType.CHECK_FAILED_SERVICES: (
        "/usr/bin/systemctl", "--failed", "--no-legend", "--no-pager",
    ),
    ActionType.CHECK_JOURNAL_ERRORS: (
        "/usr/bin/journalctl", "-p", "err", "-n", "20", "--no-pager",
    ),
    ActionType.CHECK_NETWORK: ("/usr/bin/ss", "-tulnp"),
    ActionType.CHECK_TEMPERATURE: ("/usr/bin/sensors",),
}

# ── Restricted environment for child processes ─────────────────────────
_SAFE_ENV: dict[str, str] = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "HOME": "/tmp",
}

# ── In-memory stores (single-process FastAPI server) ───────────────────
_plans: dict[str, TroubleshootingPlan] = {}
_audit_log: list[AuditEntry] = []
_lock = threading.Lock()


# ── Audit helpers ──────────────────────────────────────────────────────
def _audit(event: str, plan_id: str = "", action_id: str = "", detail: str = "") -> None:
    """Append an immutable audit entry.  Never logs secrets."""
    entry = AuditEntry(
        event=event, plan_id=plan_id, action_id=action_id, detail=detail,
    )
    _audit_log.append(entry)
    logger.info("AUDIT %s plan=%s action=%s %s", event, plan_id, action_id, detail)


def get_audit_log() -> list[dict]:
    """Return the audit trail as serialisable dicts."""
    return [entry.model_dump(mode="json") for entry in _audit_log]


# ── Plan management ───────────────────────────────────────────────────
def store_plan(plan: TroubleshootingPlan) -> None:
    """Persist a plan and record the proposal event."""
    with _lock:
        if plan.expires_at is None:
            plan.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=APPROVAL_TTL_SECONDS
            )
        _plans[plan.plan_id] = plan
    action_id = plan.proposed_action.action_id if plan.proposed_action else ""
    _audit("PROPOSED", plan.plan_id, action_id,
           plan.proposed_action.action_type.value if plan.proposed_action else "no_action")


def get_plan(plan_id: str) -> Optional[TroubleshootingPlan]:
    with _lock:
        return _plans.get(plan_id)


def _expire_if_needed(plan: TroubleshootingPlan) -> bool:
    """Mark plan expired if past its TTL.  Returns True if expired."""
    if plan.expires_at and datetime.now(timezone.utc) > plan.expires_at:
        if plan.status in (PlanStatus.PROPOSED, PlanStatus.APPROVED):
            plan.status = PlanStatus.EXPIRED
            _audit("EXPIRED", plan.plan_id,
                   plan.proposed_action.action_id if plan.proposed_action else "")
            return True
    return False


# ── Approval ──────────────────────────────────────────────────────────
def approve_action(plan_id: str, action_id: str) -> tuple[bool, str]:
    """
    Approve a proposed action.

    Returns (success, message).
    Security: approval is bound to exact (plan_id, action_id).
    """
    with _lock:
        plan = _plans.get(plan_id)
        if plan is None:
            _audit("APPROVE_REJECTED", plan_id, action_id, "unknown_plan")
            return False, "Unknown plan."

        if _expire_if_needed(plan):
            return False, "This proposal has expired."

        if plan.status != PlanStatus.PROPOSED:
            _audit("APPROVE_REJECTED", plan_id, action_id,
                   f"invalid_status:{plan.status.value}")
            return False, f"Plan is {plan.status.value}, not proposed."

        action = plan.proposed_action
        if action is None or action.action_id != action_id:
            _audit("APPROVE_REJECTED", plan_id, action_id, "action_mismatch")
            return False, "Action ID does not match the proposal."

        plan.status = PlanStatus.APPROVED
        _audit("APPROVED", plan_id, action_id)
        return True, "Action approved."


def reject_action(plan_id: str, action_id: str) -> tuple[bool, str]:
    """Reject a proposed action."""
    with _lock:
        plan = _plans.get(plan_id)
        if plan is None:
            return False, "Unknown plan."

        if plan.status != PlanStatus.PROPOSED:
            return False, f"Plan is {plan.status.value}, not proposed."

        plan.status = PlanStatus.REJECTED
        _audit("REJECTED", plan_id, action_id)
        return True, "Action rejected."


# ── Execution ─────────────────────────────────────────────────────────
def execute_action(plan_id: str, action_id: str) -> dict:
    """
    Execute an approved action.

    Security invariants enforced here:
    1. Plan must exist and be APPROVED.
    2. Action ID must match exactly.
    3. Approval must not be expired (checked again).
    4. Only RiskLevel.SAFE actions run in v1.
    5. The command comes from the server-side allowlist — never from
       user input or model output.
    6. subprocess.run receives a list (no shell interpretation).
    7. Output is truncated to MAX_OUTPUT_BYTES.
    8. Approval is consumed (one-time use).
    """
    with _lock:
        plan = _plans.get(plan_id)
        if plan is None:
            _audit("EXEC_REJECTED", plan_id, action_id, "unknown_plan")
            return {"success": False, "error": "Unknown plan."}

        if _expire_if_needed(plan):
            return {"success": False, "error": "Approval has expired."}

        if plan.status != PlanStatus.APPROVED:
            _audit("EXEC_REJECTED", plan_id, action_id,
                   f"not_approved:{plan.status.value}")
            return {"success": False, "error": f"Plan is {plan.status.value}, not approved."}

        action = plan.proposed_action
        if action is None or action.action_id != action_id:
            _audit("EXEC_REJECTED", plan_id, action_id, "action_mismatch")
            return {"success": False, "error": "Action ID mismatch."}

        # ── v1: block anything above SAFE ──────────────────────────
        if action.risk_level != RiskLevel.SAFE:
            plan.status = PlanStatus.REJECTED
            _audit("EXEC_BLOCKED", plan_id, action_id,
                   f"risk:{action.risk_level.value}")
            return {
                "success": False,
                "error": (
                    f"Actions with risk level '{action.risk_level.value}' "
                    "are not available for automatic execution in this release. "
                    "The recommended manual steps are in the plan description."
                ),
            }

        # ── Look up the fixed command in the allowlist ─────────────
        cmd_tuple = COMMAND_ALLOWLIST.get(action.action_type)
        if cmd_tuple is None:
            plan.status = PlanStatus.FAILED
            _audit("EXEC_BLOCKED", plan_id, action_id,
                   f"no_allowlist_entry:{action.action_type.value}")
            return {
                "success": False,
                "error": "This action type has no server-side command mapping.",
            }

        # Consume the approval — mark executing.
        plan.status = PlanStatus.EXECUTING
        _audit("EXECUTING", plan_id, action_id, " ".join(cmd_tuple))

    # ── Run the command outside the lock ───────────────────────────
    try:
        result = subprocess.run(
            list(cmd_tuple),
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            cwd="/tmp",
            env=_SAFE_ENV,
            # Security: shell=False is the default for list args, but
            # we are explicit for auditability.
        )

        stdout = result.stdout[:MAX_OUTPUT_BYTES]
        stderr = result.stderr[:MAX_OUTPUT_BYTES]

        exec_result = {
            "success": result.returncode == 0,
            "exit_code": result.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "truncated": len(result.stdout) > MAX_OUTPUT_BYTES or len(result.stderr) > MAX_OUTPUT_BYTES,
        }

    except subprocess.TimeoutExpired:
        exec_result = {"success": False, "error": "Command timed out.", "exit_code": -1}
        _audit("EXEC_TIMEOUT", plan_id, action_id)

    except OSError as exc:
        exec_result = {"success": False, "error": str(exc), "exit_code": -1}
        _audit("EXEC_ERROR", plan_id, action_id, str(exc))

    # ── Update plan under lock ────────────────────────────────────
    with _lock:
        plan = _plans[plan_id]
        plan.execution_result = exec_result
        plan.status = PlanStatus.COMPLETED if exec_result.get("success") else PlanStatus.FAILED
        _audit(
            "COMPLETED" if exec_result.get("success") else "FAILED",
            plan_id, action_id,
            f"exit={exec_result.get('exit_code')}",
        )

    return exec_result


# ── Verification ──────────────────────────────────────────────────────
def verify_action(plan_id: str) -> dict:
    """
    Run a lightweight verification after execution.

    For read-only diagnostics the verification simply confirms the
    command produced output and exited cleanly.
    """
    with _lock:
        plan = _plans.get(plan_id)
        if plan is None:
            return {"verified": False, "detail": "Unknown plan."}

        if plan.status not in (PlanStatus.COMPLETED, PlanStatus.FAILED):
            return {"verified": False, "detail": f"Plan is {plan.status.value}."}

        result = plan.execution_result or {}
        if result.get("success") and result.get("stdout", "").strip():
            plan.verification_result = "Output received and exit code was 0."
            plan.status = PlanStatus.VERIFIED
            _audit("VERIFIED", plan.plan_id,
                   plan.proposed_action.action_id if plan.proposed_action else "")
            return {"verified": True, "detail": plan.verification_result}
        else:
            detail = result.get("error") or result.get("stderr", "No output.")
            plan.verification_result = f"Verification concern: {detail}"
            _audit("VERIFY_CONCERN", plan.plan_id,
                   plan.proposed_action.action_id if plan.proposed_action else "",
                   detail[:200])
            return {"verified": False, "detail": plan.verification_result}
