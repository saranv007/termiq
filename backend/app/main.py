"""
TERMIQ FastAPI application.

Endpoints:
- GET  /health                          — health check
- GET  /api/v1/system/summary           — live CPU/RAM/disk
- GET  /api/v1/system/diagnostics       — diagnostic findings
- GET  /api/v1/system/processes         — top processes
- GET  /api/v1/system/failed-services   — failed systemd services
- GET  /api/v1/system/report            — full system report
- POST /api/v1/assistant/ask            — AI assistant
- POST /api/v1/assistant/approve        — approve/reject a plan
- POST /api/v1/assistant/execute        — execute an approved action
- GET  /api/v1/assistant/plan/{plan_id} — retrieve a plan
- GET  /api/v1/assistant/verify/{plan_id} — verify execution result
- GET  /api/v1/assistant/audit          — audit log
"""

import platform
import shutil

import psutil
from fastapi import FastAPI

from app.models import AskRequest, ApproveRequest
from app.services.assistant import answer_question
from app.services.diagnostics import collect_diagnostics
from app.services.executor import (
    approve_action,
    execute_action,
    get_audit_log,
    get_plan,
    reject_action,
    verify_action,
)
from app.services.process_monitor import get_top_processes
from app.services.report_service import build_system_report
from app.services.service_monitor import get_failed_services

app = FastAPI(
    title="TERMIQ API",
    description="AI-powered Linux copilot",
    version="0.3.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "application": "TERMIQ",
    }


@app.get("/api/v1/system/summary")
def system_summary():
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("/")

    return {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "cpu": {
            "logical_cores": psutil.cpu_count(),
            "usage_percent": psutil.cpu_percent(interval=0.5),
        },
        "memory": {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "used_percent": memory.percent,
            "available_gb": round(
                memory.available / (1024 ** 3), 2
            ),
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_percent": round(
                disk.used / disk.total * 100, 2
            ),
            "free_gb": round(disk.free / (1024 ** 3), 2),
        },
    }


@app.get("/api/v1/system/diagnostics")
def system_diagnostics():
    return collect_diagnostics()


@app.get("/api/v1/system/processes")
def system_processes():
    return {
        "processes": get_top_processes()
    }


@app.get("/api/v1/system/failed-services")
def failed_services():
    return get_failed_services()


@app.get("/api/v1/system/report")
def system_report():
    return build_system_report()


# ── Assistant endpoints ───────────────────────────────────────────────

@app.post("/api/v1/assistant/ask")
def assistant_ask(request: AskRequest):
    return answer_question(request.question)


@app.post("/api/v1/assistant/approve")
def assistant_approve(request: ApproveRequest):
    """Approve or reject a proposed action."""
    if request.approved:
        success, message = approve_action(request.plan_id, request.action_id)
    else:
        success, message = reject_action(request.plan_id, request.action_id)

    return {"success": success, "message": message}


@app.post("/api/v1/assistant/execute")
def assistant_execute(request: ApproveRequest):
    """Execute a previously approved action."""
    if not request.approved:
        return {"success": False, "error": "Execution requires approved=true."}

    return execute_action(request.plan_id, request.action_id)


@app.get("/api/v1/assistant/plan/{plan_id}")
def assistant_get_plan(plan_id: str):
    """Retrieve a troubleshooting plan by ID."""
    plan = get_plan(plan_id)
    if plan is None:
        return {"error": "Plan not found."}
    return plan.model_dump(mode="json")


@app.get("/api/v1/assistant/verify/{plan_id}")
def assistant_verify(plan_id: str):
    """Verify the result of an executed action."""
    return verify_action(plan_id)


@app.get("/api/v1/assistant/audit")
def assistant_audit():
    """Return the audit trail (no secrets logged)."""
    return {"entries": get_audit_log()}

