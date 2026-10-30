"""
Automation Center service for TERMIQ.

Provides predefined, user-runnable workflows:
1. Organize Downloads Folder
2. Generate Project README
3. Run Project Test Suite
4. Audit Disk Space & Large Files
5. Inspect Failed Services & Logs
6. Complete System Health Diagnostic Report
"""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from app.models import (
    AutomationExecutionRecord,
    AutomationWorkflow,
    NotificationSeverity,
)
from app.services.developer_service import run_project_tests
from app.services.file_security import (
    get_approved_roots,
    safe_find_large_files,
    safe_organize_folder,
    validate_path,
)
from app.services.notification_service import add_notification
from app.services.report_service import build_system_report
from app.services.service_monitor import get_failed_services

logger = logging.getLogger(__name__)

_history_lock = threading.Lock()
_execution_history: list[AutomationExecutionRecord] = []

WORKFLOW_DEFINITIONS = [
    AutomationWorkflow(
        id="organize_downloads",
        name="Organize Downloads Folder",
        description="Categorize files in your Downloads directory into Documents, Images, Code, Archives, and Media subfolders.",
        category="file_management",
        requires_approval=True,
        is_enabled=True,
        parameters={"dry_run": True},
    ),
    AutomationWorkflow(
        id="check_disk_space",
        name="Audit Disk Space & Large Files",
        description="Inspect filesystem disk usage and locate files larger than 10MB across your home directories.",
        category="system_maintenance",
        requires_approval=False,
        is_enabled=True,
        parameters={"threshold_mb": 10},
    ),
    AutomationWorkflow(
        id="inspect_failed_services",
        name="Inspect Failed Services",
        description="Scan systemd services for any units in failed state and summarize recent error logs.",
        category="system_maintenance",
        requires_approval=False,
        is_enabled=True,
    ),
    AutomationWorkflow(
        id="generate_health_report",
        name="Generate System Health Report",
        description="Collect full diagnostic data: CPU load, memory breakdown, disk space, and process activity.",
        category="diagnostics",
        requires_approval=False,
        is_enabled=True,
    ),
    AutomationWorkflow(
        id="run_project_tests",
        name="Run Project Unit Tests",
        description="Execute pytest or unittest test suite inside an approved project directory and report results.",
        category="developer",
        requires_approval=False,
        is_enabled=True,
        parameters={"project_directory": "Projects"},
    ),
]


def list_workflows() -> list[AutomationWorkflow]:
    """Return all available automation workflows."""
    return WORKFLOW_DEFINITIONS


def get_workflow(workflow_id: str) -> Optional[AutomationWorkflow]:
    """Retrieve workflow by ID."""
    for wf in WORKFLOW_DEFINITIONS:
        if wf.id == workflow_id:
            return wf
    return None


def execute_workflow(
    workflow_id: str,
    parameters: Optional[dict[str, Any]] = None,
    approved: bool = False,
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Execute a specified automation workflow safely.
    """
    wf = get_workflow(workflow_id)
    if not wf:
        return {"success": False, "error": f"Workflow '{workflow_id}' not found."}

    if wf.requires_approval and not approved:
        return {
            "success": False,
            "error": "This workflow requires explicit user approval before execution.",
            "requires_approval": True,
        }

    params = parameters or wf.parameters
    run_id = uuid4().hex[:12]
    now = datetime.now(timezone.utc)
    rec = AutomationExecutionRecord(
        run_id=run_id,
        workflow_id=wf.id,
        workflow_name=wf.name,
        status="executing",
        started_at=now,
    )

    output_data = {}
    err_msg = None

    try:
        if wf.id == "organize_downloads":
            if approved_roots is None:
                approved_roots = get_approved_roots()
            downloads_dir = Path.home() / "Downloads"
            valid_dir, err = validate_path(downloads_dir, must_exist=True, approved_roots=approved_roots)
            if err or valid_dir is None:
                raise ValueError(f"Downloads path error: {err}")

            dry_run = params.get("dry_run", True)
            res = safe_organize_folder(valid_dir, dry_run=dry_run, approved_roots=approved_roots)
            output_data = res
            wf.last_status = "completed"

        elif wf.id == "check_disk_space":
            if approved_roots is None:
                approved_roots = get_approved_roots()
            target_dir = Path.home() / "Downloads"
            if not target_dir.exists() and approved_roots:
                target_dir = approved_roots[0]

            threshold_mb = int(params.get("threshold_mb", 10))
            res = safe_find_large_files(
                target_dir,
                min_bytes=threshold_mb * 1024 * 1024,
                approved_roots=approved_roots,
            )
            output_data = res
            wf.last_status = "completed"

        elif wf.id == "inspect_failed_services":
            failed = get_failed_services()
            output_data = failed
            wf.last_status = "completed"

        elif wf.id == "generate_health_report":
            report = build_system_report()
            output_data = report
            wf.last_status = "completed"

        elif wf.id == "run_project_tests":
            proj_name = params.get("project_directory", "Projects")
            proj_path = Path.home() / proj_name
            if not proj_path.exists() and approved_roots:
                proj_path = approved_roots[0]

            res_tests = run_project_tests(proj_path, approved_roots=approved_roots)
            output_data = res_tests.model_dump(mode="json")
            wf.last_status = "completed" if res_tests.success else "failed"

        rec.status = "completed"
        rec.completed_at = datetime.now(timezone.utc)
        rec.output = output_data

        add_notification(
            title=f"Workflow Completed: {wf.name}",
            message="Workflow executed successfully.",
            severity=NotificationSeverity.SUCCESS,
            category="task",
        )

    except Exception as exc:
        rec.status = "failed"
        rec.completed_at = datetime.now(timezone.utc)
        rec.error = str(exc)
        err_msg = str(exc)
        wf.last_status = "failed"

        add_notification(
            title=f"Workflow Failed: {wf.name}",
            message=str(exc),
            severity=NotificationSeverity.ERROR,
            category="task",
        )

    wf.last_run = datetime.now(timezone.utc)
    with _history_lock:
        _execution_history.insert(0, rec)
        if len(_execution_history) > 50:
            _execution_history.pop()

    return {
        "success": rec.status == "completed",
        "run_id": run_id,
        "workflow_id": wf.id,
        "status": rec.status,
        "output": output_data,
        "error": err_msg,
    }


def get_execution_history(limit: int = 50) -> list[dict]:
    """Return past automation execution records."""
    with _history_lock:
        return [r.model_dump(mode="json") for r in _execution_history[:limit]]

