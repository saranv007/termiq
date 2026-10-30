"""
Notification Center and System Alerts for TERMIQ.

Maintains notifications for:
- Task completions and failures
- Approval requests
- File conflict detection
- High resource warnings (CPU, RAM, Disk)
- Failed system services
"""

import logging
import shutil
import threading
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

import psutil

from app.models import NotificationItem, NotificationSeverity
from app.services.service_monitor import get_failed_services

logger = logging.getLogger(__name__)

_notif_lock = threading.Lock()
_notifications: list[NotificationItem] = []


def add_notification(
    title: str,
    message: str,
    severity: NotificationSeverity = NotificationSeverity.INFO,
    category: str = "system",
    task_id: Optional[str] = None,
) -> NotificationItem:
    """Add a new notification to the queue."""
    item = NotificationItem(
        id=uuid4().hex[:12],
        title=title,
        message=message,
        severity=severity,
        category=category,
        task_id=task_id,
        timestamp=datetime.now(timezone.utc),
        is_read=False,
    )
    with _notif_lock:
        # Prevent exact duplicate unread notifications
        for existing in _notifications:
            if not existing.is_read and existing.title == title and existing.message == message:
                return existing
        _notifications.insert(0, item)
        # Cap queue at 100 items
        if len(_notifications) > 100:
            _notifications.pop()
    logger.info("Notification added [%s]: %s - %s", severity.value, title, message)
    return item


def get_notifications(
    unread_only: bool = False,
    limit: int = 50,
) -> list[NotificationItem]:
    """Retrieve notifications sorted by newest first."""
    with _notif_lock:
        items = [
            n for n in _notifications
            if not unread_only or not n.is_read
        ]
        return items[:limit]


def mark_as_read(notification_id: str) -> bool:
    """Mark a notification as read."""
    with _notif_lock:
        for n in _notifications:
            if n.id == notification_id:
                n.is_read = True
                return True
    return False


def dismiss_notification(notification_id: str) -> bool:
    """Remove a notification."""
    with _notif_lock:
        for idx, n in enumerate(_notifications):
            if n.id == notification_id:
                _notifications.pop(idx)
                return True
    return False


def clear_all_notifications() -> int:
    """Clear all notifications."""
    with _notif_lock:
        count = len(_notifications)
        _notifications.clear()
        return count


def check_system_health_alerts() -> list[NotificationItem]:
    """
    Scan system metrics and generate alerts for any warning conditions.
    """
    alerts = []

    # Check RAM
    try:
        mem = psutil.virtual_memory()
        if mem.percent >= 90.0:
            alerts.append(add_notification(
                title="High Memory Alert",
                message=f"System RAM usage is critical at {mem.percent}%.",
                severity=NotificationSeverity.WARNING,
                category="system",
            ))
    except Exception:
        pass

    # Check Disk
    try:
        disk = shutil.disk_usage("/")
        used_pct = round(disk.used / disk.total * 100, 1)
        if used_pct >= 90.0:
            alerts.append(add_notification(
                title="Disk Space Warning",
                message=f"Root disk partition is {used_pct}% full ({round(disk.free / (1024**3), 1)} GB free).",
                severity=NotificationSeverity.WARNING,
                category="system",
            ))
    except Exception:
        pass

    # Check Failed Services
    try:
        failed = get_failed_services()
        if failed.get("available") and failed.get("failed_count", 0) > 0:
            units = ", ".join(s["unit"] for s in failed.get("services", [])[:3])
            alerts.append(add_notification(
                title="Failed System Services",
                message=f"{failed['failed_count']} service(s) failed on system: {units}",
                severity=NotificationSeverity.WARNING,
                category="system",
            ))
    except Exception:
        pass

    return alerts

