import shutil
import psutil
import platform
from datetime import datetime, timezone


def collect_diagnostics():
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    cpu = psutil.cpu_percent(interval=1)

    findings = []

    if memory.percent >= 85:
        findings.append({
            "severity": "warning",
            "issue": "High memory usage",
            "value": memory.percent,
        })

    if disk.used / disk.total >= 0.90:
        findings.append({
            "severity": "warning",
            "issue": "Low disk space",
            "value": round(disk.used / disk.total * 100, 2),
        })

    if cpu >= 85:
        findings.append({
            "severity": "warning",
            "issue": "High CPU usage",
            "value": cpu,
        })

    if not findings:
        findings.append({
            "severity": "info",
            "issue": "No critical resource threshold exceeded",
        })

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": platform.system(),
        "cpu_percent": cpu,
        "memory_percent": memory.percent,
        "disk_percent": round(disk.used / disk.total * 100, 2),
        "findings": findings,
    }
