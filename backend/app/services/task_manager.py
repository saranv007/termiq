"""
Universal Task Management and Workflow Engine for TERMIQ.

Maintains multi-step tasks across:
- System Diagnostics
- File & Folder Operations
- Developer Tools
- Automation Workflows
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.models import (
    RiskLevel,
    TaskCategory,
    UnifiedTask,
)

logger = logging.getLogger(__name__)

_tasks_lock = threading.Lock()
_unified_tasks: dict[str, UnifiedTask] = {}


def record_task(
    title: str,
    category: TaskCategory,
    request_text: str,
    status: str = "draft",
    risk_level: RiskLevel = RiskLevel.SAFE,
    requires_approval: bool = True,
    approval_token: Optional[str] = None,
    summary: str = "",
    details: Optional[dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> UnifiedTask:
    """Record a new unified task in the workflow engine."""
    tid = task_id or uuid4().hex[:16]
    now = datetime.now(timezone.utc)
    task = UnifiedTask(
        task_id=tid,
        category=category,
        title=title,
        request_text=request_text,
        status=status,
        risk_level=risk_level,
        requires_approval=requires_approval,
        approval_token=approval_token,
        summary=summary,
        details=details or {},
        created_at=now,
        updated_at=now,
    )
    with _tasks_lock:
        _unified_tasks[tid] = task
    logger.info("Task recorded [%s]: %s (%s)", tid, title, status)
    return task


def update_task_status(
    task_id: str,
    status: str,
    summary: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    verification_result: Optional[str] = None,
) -> Optional[UnifiedTask]:
    """Update task lifecycle state and output."""
    with _tasks_lock:
        task = _unified_tasks.get(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = datetime.now(timezone.utc)
        if summary is not None:
            task.summary = summary
        if details is not None:
            task.details.update(details)
        if verification_result is not None:
            task.verification_result = verification_result
        return task


def get_task(task_id: str) -> Optional[UnifiedTask]:
    """Retrieve task by ID."""
    with _tasks_lock:
        return _unified_tasks.get(task_id)


def list_tasks(
    status: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
) -> list[UnifiedTask]:
    """
    List tasks matching filter criteria sorted by most recent.
    """
    with _tasks_lock:
        tasks = list(_unified_tasks.values())

    # Sort descending by updated_at
    tasks.sort(key=lambda t: t.updated_at, reverse=True)

    filtered = []
    for t in tasks:
        if status and t.status.lower() != status.lower():
            continue
        if category and t.category.value.lower() != category.lower():
            continue
        if search:
            query = search.lower()
            if query not in t.title.lower() and query not in t.request_text.lower():
                continue
        filtered.append(t)
        if len(filtered) >= limit:
            break

    return filtered


def cancel_task(task_id: str) -> tuple[bool, str]:
    """Cancel a pending or awaiting-approval task."""
    with _tasks_lock:
        task = _unified_tasks.get(task_id)
        if not task:
            return False, "Task not found."
        if task.status in ("completed", "verified"):
            return False, "Cannot cancel already completed task."
        task.status = "cancelled"
        task.updated_at = datetime.now(timezone.utc)
        return True, "Task cancelled."


def clear_task_history() -> int:
    """Clear in-memory task history."""
    with _tasks_lock:
        count = len(_unified_tasks)
        _unified_tasks.clear()
        return count

