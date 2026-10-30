"""
TERMIQ FastAPI application.

Endpoints:
- GET  /health                            — health check
- GET  /api/v1/system/summary             — live CPU/RAM/disk
- GET  /api/v1/system/diagnostics         — diagnostic findings
- GET  /api/v1/system/processes           — top processes
- GET  /api/v1/system/failed-services     — failed systemd services
- GET  /api/v1/system/report              — full system report

- POST /api/v1/assistant/ask              — AI assistant
- POST /api/v1/assistant/approve          — approve/reject a diagnostic plan
- POST /api/v1/assistant/execute          — execute an approved diagnostic action
- GET  /api/v1/assistant/plan/{plan_id}   — retrieve a plan
- GET  /api/v1/assistant/verify/{plan_id} — verify execution result
- GET  /api/v1/assistant/audit            — system copilot audit log

- POST /api/v1/files/task/create          — create/parse natural language file task
- POST /api/v1/files/task/{task_id}/clarify — submit clarification answers
- GET  /api/v1/files/task/{task_id}       — retrieve file task
- POST /api/v1/files/task/{task_id}/approve — approve/reject file task
- POST /api/v1/files/task/{task_id}/execute — execute approved file task
- POST /api/v1/files/task/{task_id}/reject  — reject file task
- GET  /api/v1/files/roots                — list approved user directory roots
- GET  /api/v1/files/list                 — safe directory listing
- GET  /api/v1/files/search               — safe filename search
- GET  /api/v1/files/read                 — safe text file read (64KB limit)
- GET  /api/v1/files/audit                — file copilot audit log
"""

import platform
import shutil
from pathlib import Path
from typing import Optional

import psutil
from fastapi import FastAPI, HTTPException, Query

from app.models import (
    ApproveFileTaskRequest,
    ApproveRequest,
    AskRequest,
    ClarifyFileTaskRequest,
    CreateFileTaskRequest,
)
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
from app.services.file_copilot import (
    approve_file_task,
    clarify_task,
    execute_file_task,
    get_file_audit_log,
    get_task,
    parse_file_request,
)
from app.services.file_security import (
    get_approved_roots,
    safe_list_dir,
    safe_read_text_file,
    safe_search_files,
)
from app.services.process_monitor import get_top_processes
from app.services.report_service import build_system_report
from app.services.service_monitor import get_failed_services

app = FastAPI(
    title="TERMIQ API",
    description="AI-powered Linux copilot & File Copilot",
    version="2.0.0",
)


# ── System Diagnostic Endpoints ────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "application": "TERMIQ",
        "version": "2.0.0",
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


# ── System Copilot Assistant Endpoints ─────────────────────────────────

@app.post("/api/v1/assistant/ask")
def assistant_ask(request: AskRequest):
    return answer_question(request.question)


@app.post("/api/v1/assistant/approve")
def assistant_approve(request: ApproveRequest):
    """Approve or reject a proposed diagnostic action."""
    if request.approved:
        success, message = approve_action(request.plan_id, request.action_id)
    else:
        success, message = reject_action(request.plan_id, request.action_id)

    return {"success": success, "message": message}


@app.post("/api/v1/assistant/execute")
def assistant_execute(request: ApproveRequest):
    """Execute a previously approved diagnostic action."""
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
    """Verify the result of an executed diagnostic action."""
    return verify_action(plan_id)


@app.get("/api/v1/assistant/audit")
def assistant_audit():
    """Return the audit trail for system copilot actions."""
    return {"entries": get_audit_log()}


# ── File & Folder Copilot Endpoints (V2.0) ─────────────────────────────

@app.post("/api/v1/files/task/create")
def file_task_create(request: CreateFileTaskRequest):
    """Parse a natural-language file request and create a structured task."""
    task = parse_file_request(
        request_text=request.request,
        context_directory=request.context_directory,
    )
    return task.model_dump(mode="json")


@app.post("/api/v1/files/task/{task_id}/clarify")
def file_task_clarify(task_id: str, request: ClarifyFileTaskRequest):
    """Submit clarification answers for missing parameters."""
    ok, msg, task = clarify_task(
        task_id=task_id,
        answers=request.answers,
        text=request.text,
    )
    if task is None:
        raise HTTPException(status_code=404, detail=msg)

    return {
        "success": ok,
        "message": msg,
        "task": task.model_dump(mode="json"),
    }


@app.get("/api/v1/files/task/{task_id}")
def file_task_get(task_id: str):
    """Retrieve the current state of a file task."""
    task = get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="File task not found.")
    return task.model_dump(mode="json")


@app.post("/api/v1/files/task/{task_id}/approve")
def file_task_approve(task_id: str, request: ApproveFileTaskRequest):
    """Approve or reject a file task."""
    ok, msg, task = approve_file_task(
        task_id=task_id,
        approved=request.approved,
        approval_token=request.approval_token,
    )
    if task is None:
        raise HTTPException(status_code=404, detail=msg)

    return {
        "success": ok,
        "message": msg,
        "task": task.model_dump(mode="json"),
    }


@app.post("/api/v1/files/task/{task_id}/execute")
def file_task_execute(task_id: str, request: ApproveFileTaskRequest):
    """Execute an approved file task."""
    if not request.approved:
        return {"success": False, "error": "Execution requires approved=true."}

    ok, msg, task = execute_file_task(
        task_id=task_id,
        approval_token=request.approval_token,
    )
    if task is None:
        raise HTTPException(status_code=404, detail=msg)

    return {
        "success": ok,
        "message": msg,
        "task": task.model_dump(mode="json"),
    }


@app.post("/api/v1/files/task/{task_id}/reject")
def file_task_reject(task_id: str):
    """Reject and cancel a file task."""
    ok, msg, task = approve_file_task(task_id=task_id, approved=False)
    if task is None:
        raise HTTPException(status_code=404, detail=msg)

    return {
        "success": ok,
        "message": msg,
        "task": task.model_dump(mode="json"),
    }


@app.get("/api/v1/files/roots")
def file_roots():
    """Return the list of approved user directory roots."""
    roots = get_approved_roots()
    return {
        "roots": [
            {"name": r.name, "path": str(r)}
            for r in roots
        ]
    }


@app.get("/api/v1/files/list")
def file_list(
    path: str = Query(..., description="Target directory path"),
    max_items: int = Query(100, ge=1, le=500),
):
    """List non-hidden files and folders within an approved directory."""
    result = safe_list_dir(Path(path), max_items=max_items)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/api/v1/files/search")
def file_search(
    path: str = Query(..., description="Base directory to search"),
    pattern: str = Query(..., description="Filename pattern or keyword"),
    max_items: int = Query(100, ge=1, le=500),
):
    """Search filenames within an approved directory."""
    result = safe_search_files(Path(path), pattern=pattern, max_items=max_items)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/api/v1/files/read")
def file_read(
    path: str = Query(..., description="Target text file path"),
    max_bytes: int = Query(65536, ge=1, le=262144),
):
    """Read a text file with size limit (64KB default)."""
    result = safe_read_text_file(Path(path), max_bytes=max_bytes)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@app.get("/api/v1/files/audit")
def file_audit():
    """Return the audit log for file copilot operations."""
    return {"entries": get_file_audit_log()}
