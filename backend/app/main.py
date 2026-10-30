"""
TERMIQ FastAPI application V2.1.

Comprehensive AI-powered Linux Copilot backend:
- System diagnostics, performance monitoring, process inspection, hardware sensors
- AI Assistant with Gemini and local rule-based fallback
- Approval-based execution engine with single-use tokens & TTL expiry
- File & Folder Copilot with safe creation, editing, trash, organize, diffs, backups
- Developer Copilot with error analysis, venv creation, unit testing, Git status, VS Code opener
- Multi-step Task Management & Audit History
- Automation Center with user-runnable workflows
- Notification Center with system health alerts
- Full TERMIQ Workspace served at /workspace/
"""

import os
import platform
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psutil
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.models import (
    ApproveFileTaskRequest,
    ApproveRequest,
    AskRequest,
    ClarifyFileTaskRequest,
    CopyMoveFileRequest,
    CreateFileTaskRequest,
    CreateVenvRequest,
    EditFileRequest,
    ExplainErrorRequest,
    GitStatusRequest,
    OpenEditorRequest,
    OrganizeFolderRequest,
    RiskLevel,
    RunTestsRequest,
    TaskCategory,
    TrashFileRequest,
    UserSettings,
    WorkflowRunRequest,
)
from app.services.assistant import answer_question
from app.services.automation_service import (
    execute_workflow,
    get_execution_history,
    list_workflows,
)
from app.services.developer_service import (
    create_virtualenv,
    explain_python_error,
    get_git_status,
    open_in_editor,
    run_project_tests,
)
from app.services.diagnostics import (
    collect_diagnostics,
    diagnose_network,
    diagnose_slowdown,
    get_system_journal_errors,
)
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
    safe_copy_file,
    safe_edit_file,
    safe_find_duplicates,
    safe_find_large_files,
    safe_get_metadata,
    safe_list_dir,
    safe_move_file,
    safe_organize_folder,
    safe_read_text_file,
    safe_search_files,
    safe_trash_file,
)
from app.services.notification_service import (
    add_notification,
    check_system_health_alerts,
    clear_all_notifications,
    dismiss_notification,
    get_notifications,
    mark_as_read,
)
from app.services.process_monitor import get_top_processes
from app.services.report_service import build_system_report
from app.services.service_monitor import get_failed_services
from app.services.task_manager import (
    cancel_task,
    clear_task_history,
    list_tasks,
    record_task,
    update_task_status,
)
from app.services.temperature_monitor import get_temperatures

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

app = FastAPI(
    title="TERMIQ API",
    description="AI-powered Linux copilot & File Copilot",
    version="2.1.0",
)

# CORS middleware for local frontend / extension integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory user settings
_user_settings = UserSettings(
    approved_roots=[str(r) for r in get_approved_roots()],
    refresh_interval_seconds=5,
    mode="beginner",
    notifications_enabled=True,
    retention_days=30,
    theme="dark",
)

WORKSPACE_DIR = Path(__file__).resolve().parent / "workspace"


# ── Health & System Endpoints ──────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "application": "TERMIQ",
        "version": "2.1.0",
    }


@app.get("/api/v1/system/summary")
def system_summary():
    """Live system overview preserved for GNOME top-panel and dashboard."""
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    uptime_sec = time.time() - psutil.boot_time()

    return {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "uptime_seconds": round(uptime_sec, 0),
        "cpu": {
            "logical_cores": psutil.cpu_count(),
            "usage_percent": psutil.cpu_percent(interval=0.2),
        },
        "memory": {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "used_percent": memory.percent,
            "available_gb": round(memory.available / (1024 ** 3), 2),
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_percent": round(disk.used / disk.total * 100, 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
        },
    }


@app.get("/api/v1/system/monitor")
def system_monitor():
    """Complete hardware, resource, and process metrics for System Monitor."""
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = shutil.disk_usage("/")
    boot_time_ts = psutil.boot_time()
    uptime_sec = time.time() - boot_time_ts

    hours = int(uptime_sec // 3600)
    minutes = int((uptime_sec % 3600) // 60)
    uptime_str = f"{hours}h {minutes}m"

    # CPU per core
    per_core = psutil.cpu_percent(interval=0.2, percpu=True)

    # Battery
    battery_info = {"available": False, "percent": None, "power_plugged": None}
    try:
        b = psutil.sensors_battery()
        if b is not None:
            battery_info = {
                "available": True,
                "percent": b.percent,
                "power_plugged": b.power_plugged,
                "secsleft": b.secsleft if b.secsleft != psutil.POWER_TIME_UNLIMITED else None,
            }
    except Exception:
        pass

    # Network rates & interfaces
    net_io = psutil.net_io_counters()
    net_diag = diagnose_network()

    # Partitions
    partitions = []
    try:
        for part in psutil.disk_partitions(all=False):
            if "snap" in part.mountpoint or "docker" in part.mountpoint:
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions.append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "total_gb": round(usage.total / (1024 ** 3), 2),
                    "used_percent": usage.percent,
                    "free_gb": round(usage.free / (1024 ** 3), 2),
                })
            except Exception:
                continue
    except Exception:
        pass

    return {
        "os": platform.platform(),
        "uptime_seconds": round(uptime_sec, 0),
        "uptime_human": uptime_str,
        "boot_time": datetime.fromtimestamp(boot_time_ts, tz=timezone.utc).isoformat(),
        "cpu": {
            "overall_percent": psutil.cpu_percent(interval=None),
            "logical_cores": psutil.cpu_count(),
            "per_core_percent": per_core,
            "load_average": os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0),
        },
        "memory": {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "used_gb": round((memory.total - memory.available) / (1024 ** 3), 2),
            "available_gb": round(memory.available / (1024 ** 3), 2),
            "used_percent": memory.percent,
        },
        "swap": {
            "total_gb": round(swap.total / (1024 ** 3), 2),
            "used_gb": round(swap.used / (1024 ** 3), 2),
            "free_gb": round(swap.free / (1024 ** 3), 2),
            "used_percent": swap.percent,
        },
        "disk": {
            "root_total_gb": round(disk.total / (1024 ** 3), 2),
            "root_used_percent": round(disk.used / disk.total * 100, 2),
            "root_free_gb": round(disk.free / (1024 ** 3), 2),
            "partitions": partitions,
        },
        "network": {
            "bytes_sent": net_io.bytes_sent,
            "bytes_recv": net_io.bytes_recv,
            "status": net_diag.get("status"),
            "summary": net_diag.get("summary"),
            "active_interfaces": net_diag.get("active_interfaces", []),
        },
        "battery": battery_info,
        "temperatures": get_temperatures(),
        "processes": get_top_processes(limit=15).get("by_cpu", []),
        "failed_services": get_failed_services(),
    }


@app.get("/api/v1/system/diagnostics")
def system_diagnostics():
    return collect_diagnostics()


@app.get("/api/v1/system/diagnostics/slowdown")
def system_diag_slowdown():
    return diagnose_slowdown()


@app.get("/api/v1/system/diagnostics/network")
def system_diag_network():
    return diagnose_network()


@app.get("/api/v1/system/diagnostics/journal-errors")
def system_diag_journal(line_count: int = Query(20, ge=5, le=100)):
    return get_system_journal_errors(line_count=line_count)


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


# ── AI Assistant Endpoints ─────────────────────────────────────────────

@app.post("/api/v1/assistant/ask")
def assistant_ask(request: AskRequest):
    res = answer_question(request.question, mode=request.mode)
    # Record task in workflow engine
    record_task(
        title=f"Assistant: {request.question[:40]}",
        category=TaskCategory.SYSTEM_DIAGNOSTIC,
        request_text=request.question,
        status="completed" if not res.get("plan") else "ready_for_review",
        risk_level=RiskLevel.SAFE,
        requires_approval=bool(res.get("plan")),
        summary=res.get("answer", "")[:120],
        details={"response": res},
    )
    return res


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


# ── File & Folder Copilot Endpoints ────────────────────────────────────

@app.post("/api/v1/files/task/create")
def file_task_create(request: CreateFileTaskRequest):
    """Parse a natural-language file request and create a structured task."""
    task = parse_file_request(
        request_text=request.request,
        context_directory=request.context_directory,
    )
    # Record in universal task engine
    record_task(
        task_id=task.task_id,
        title=f"File: {task.target_name or task.operation.value}",
        category=TaskCategory.FILE_OPERATION,
        request_text=task.request_text,
        status=task.status.value,
        risk_level=RiskLevel.CAUTION,
        requires_approval=task.requires_approval,
        approval_token=task.approval_token,
        summary=task.summary or task.request_text[:80],
        details={"planned_files": [f.relative_path for f in task.planned_files]},
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

    update_task_status(
        task_id=task.task_id,
        status=task.status.value,
        summary=task.summary,
    )

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

    update_task_status(
        task_id=task.task_id,
        status=task.status.value,
    )

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

    update_task_status(
        task_id=task.task_id,
        status=task.status.value,
        verification_result=task.verification_result,
        details={"result": task.execution_result},
    )

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

    update_task_status(task_id=task_id, status="rejected")
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


@app.post("/api/v1/files/edit")
def file_edit(req: EditFileRequest):
    """Safely edit a file with backup and diff generation."""
    res = safe_edit_file(Path(req.path), req.new_content, create_backup=req.create_backup)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/v1/files/trash")
def file_trash(req: TrashFileRequest):
    """Safely move a file or folder into desktop trash."""
    if not req.approved:
        return {
            "success": False,
            "requires_approval": True,
            "message": f"Moving '{Path(req.path).name}' to Trash requires explicit approval.",
        }
    res = safe_trash_file(Path(req.path))
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/v1/files/copy")
def file_copy(req: CopyMoveFileRequest):
    """Copy a file or directory safely within approved roots."""
    res = safe_copy_file(Path(req.source_path), Path(req.destination_path))
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/v1/files/move")
def file_move(req: CopyMoveFileRequest):
    """Move or rename a file or directory safely."""
    res = safe_move_file(Path(req.source_path), Path(req.destination_path))
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.get("/api/v1/files/duplicates")
def file_duplicates(
    path: str = Query(..., description="Directory to search for duplicates"),
    min_bytes: int = Query(100, ge=1),
    max_items: int = Query(50, ge=1, le=200),
):
    """Detect duplicate files by size and SHA-256 hash."""
    res = safe_find_duplicates(Path(path), min_bytes=min_bytes, max_items=max_items)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.get("/api/v1/files/large")
def file_large(
    path: str = Query(..., description="Directory to search for large files"),
    min_bytes: int = Query(10485760, ge=1024),
    max_items: int = Query(50, ge=1, le=200),
):
    """Find files exceeding the size threshold."""
    res = safe_find_large_files(Path(path), min_bytes=min_bytes, max_items=max_items)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/v1/files/organize")
def file_organize(req: OrganizeFolderRequest):
    """Organize folder into category subdirectories."""
    res = safe_organize_folder(Path(req.path), dry_run=req.dry_run)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.get("/api/v1/files/metadata")
def file_metadata(path: str = Query(..., description="Target file path")):
    """Get metadata for file or directory."""
    res = safe_get_metadata(Path(path))
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.get("/api/v1/files/audit")
def file_audit():
    """Return the audit log for file copilot operations."""
    return {"entries": get_file_audit_log()}


# ── Developer Copilot Endpoints ────────────────────────────────────────

@app.post("/api/v1/dev/explain-error")
def dev_explain_error(req: ExplainErrorRequest):
    """Explain a Python traceback or error in beginner or advanced mode."""
    return explain_python_error(req.error_text, context_code=req.context_code, mode=req.mode)


@app.post("/api/v1/dev/venv/create")
def dev_create_venv(req: CreateVenvRequest):
    """Create a Python virtual environment in an approved project directory."""
    res = create_virtualenv(req.directory, venv_name=req.venv_name)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res


@app.post("/api/v1/dev/tests/run")
def dev_run_tests(req: RunTestsRequest):
    """Run project test suite with fixed policy and timeout."""
    return run_project_tests(req.project_directory)


@app.get("/api/v1/dev/git/status")
def dev_git_status(path: str = Query(..., description="Git project directory")):
    """Inspect Git repository status and recent commits."""
    return get_git_status(path)


@app.post("/api/v1/dev/open-editor")
def dev_open_editor(req: OpenEditorRequest):
    """Open project in VS Code or system editor."""
    return open_in_editor(req.target_path, editor_preference=req.editor)


# ── Task Management & Workflow History Endpoints ───────────────────────

@app.get("/api/v1/tasks")
def tasks_list(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List tasks matching query filters."""
    return {"tasks": [t.model_dump(mode="json") for t in list_tasks(status=status, category=category, search=search, limit=limit)]}


@app.post("/api/v1/tasks/{task_id}/cancel")
def tasks_cancel(task_id: str):
    """Cancel a pending task."""
    ok, msg = cancel_task(task_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/v1/tasks/clear")
def tasks_clear():
    """Clear all task history."""
    count = clear_task_history()
    return {"success": True, "cleared_count": count}


# ── Automation Center Endpoints ────────────────────────────────────────

@app.get("/api/v1/automation/workflows")
def auto_workflows():
    """List all available workflows."""
    return {"workflows": [w.model_dump(mode="json") for w in list_workflows()]}


@app.post("/api/v1/automation/run/{workflow_id}")
def auto_run(workflow_id: str, req: WorkflowRunRequest):
    """Run an automation workflow."""
    res = execute_workflow(workflow_id, parameters=req.parameters, approved=req.approved)
    return res


@app.get("/api/v1/automation/history")
def auto_history(limit: int = Query(50, ge=1, le=100)):
    """Retrieve automation execution records."""
    return {"history": get_execution_history(limit=limit)}


# ── Notification Center Endpoints ──────────────────────────────────────

@app.get("/api/v1/notifications")
def notifs_get(unread_only: bool = Query(False), limit: int = Query(50, ge=1, le=100)):
    """Retrieve notifications and check system health alerts."""
    check_system_health_alerts()
    items = get_notifications(unread_only=unread_only, limit=limit)
    return {"notifications": [n.model_dump(mode="json") for n in items]}


@app.post("/api/v1/notifications/{notif_id}/read")
def notifs_mark_read(notif_id: str):
    ok = mark_as_read(notif_id)
    return {"success": ok}


@app.post("/api/v1/notifications/{notif_id}/dismiss")
def notifs_dismiss(notif_id: str):
    ok = dismiss_notification(notif_id)
    return {"success": ok}


@app.post("/api/v1/notifications/clear")
def notifs_clear():
    count = clear_all_notifications()
    return {"success": True, "cleared_count": count}


# ── Settings Endpoints ─────────────────────────────────────────────────

@app.get("/api/v1/settings")
def settings_get():
    """Retrieve current user settings."""
    return _user_settings.model_dump(mode="json")


@app.post("/api/v1/settings")
def settings_update(settings: UserSettings):
    """Update user settings."""
    global _user_settings
    _user_settings = settings
    return {"success": True, "settings": _user_settings.model_dump(mode="json")}


@app.get("/api/v1/settings/gemini-status")
def settings_gemini_status():
    """Inspect Gemini configuration status without leaking API key."""
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    is_configured = bool(api_key and len(api_key.strip()) > 10)
    return {
        "configured": is_configured,
        "model": model,
        "provider": "Google Gemini",
        "key_hint": f"...{api_key[-4:]}" if is_configured and api_key else "Not configured",
    }


# ── Full TERMIQ Workspace Static Application ──────────────────────────

@app.get("/workspace")
@app.get("/workspace/")
def serve_workspace_root():
    """Serve the full TERMIQ workspace interface."""
    index_file = WORKSPACE_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h2>TERMIQ Workspace is initializing...</h2>")


if WORKSPACE_DIR.exists():
    app.mount("/workspace", StaticFiles(directory=str(WORKSPACE_DIR), html=True), name="workspace")
