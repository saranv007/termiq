"""
Intelligent Linux System Diagnostics service for TERMIQ.

Collects real system evidence for:
- System slowdowns
- High RAM / Swap usage
- Low disk space
- Network / Internet connectivity issues
- Failed services during boot
"""

import os
import platform
import shutil
import socket
import subprocess
from datetime import datetime, timezone

import psutil


def collect_diagnostics():
    """
    Core resource diagnostic baseline.
    Preserves exact keys for backward compatibility.
    """
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("/")
    cpu = psutil.cpu_percent(interval=0.5)

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


def diagnose_slowdown():
    """
    Diagnose why the laptop or system is running slowly.
    Inspects CPU utilization, load averages, memory pressure, and top consumers.
    """
    cpu_pct = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    load_avg = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)

    # Top CPU consumers
    top_cpu = []
    for p in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                    key=lambda x: x.info.get("cpu_percent") or 0, reverse=True)[:5]:
        top_cpu.append(p.info)

    bottlenecks = []
    if cpu_pct > 75:
        bottlenecks.append(f"High CPU usage ({cpu_pct}%). Top process: {top_cpu[0]['name'] if top_cpu else 'Unknown'}")
    if mem.percent > 85:
        bottlenecks.append(f"High RAM pressure ({mem.percent}% used).")
    if swap.percent > 50:
        bottlenecks.append(f"Heavy Swap thrashing ({swap.percent}% swap used), indicating memory exhaustion.")
    if load_avg[0] > (psutil.cpu_count() or 1) * 1.5:
        bottlenecks.append(f"High load average ({load_avg[0]:.2f}) relative to {psutil.cpu_count()} CPU cores.")

    if not bottlenecks:
        summary = "System responsiveness appears normal. CPU and RAM utilization are within healthy ranges."
    else:
        summary = "Performance bottleneck detected: " + "; ".join(bottlenecks)

    return {
        "summary": summary,
        "cpu_percent": cpu_pct,
        "load_average_1m": round(load_avg[0], 2),
        "memory_percent": mem.percent,
        "swap_percent": swap.percent,
        "top_cpu_processes": top_cpu,
        "bottlenecks": bottlenecks,
    }


def diagnose_network():
    """
    Diagnose network and internet connectivity.
    Performs DNS resolution test and gateway socket reachability test.
    """
    # 1. Check network interfaces
    interfaces = psutil.net_if_addrs()
    active_interfaces = []
    for iface, addrs in interfaces.items():
        if iface.startswith("lo"):
            continue
        ips = [a.address for a in addrs if a.family == socket.AF_INET]
        if ips:
            active_interfaces.append({"interface": iface, "ip": ips[0]})

    # 2. Test DNS resolution
    dns_ok = False
    dns_error = None
    try:
        socket.gethostbyname("archive.ubuntu.com")
        dns_ok = True
    except Exception as exc:
        dns_error = str(exc)

    # 3. Test Internet socket connection to public DNS
    internet_ok = False
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect(("1.1.1.1", 53))
        s.close()
        internet_ok = True
    except Exception:
        pass

    if internet_ok and dns_ok:
        status_msg = "Internet connectivity is active and DNS resolution is working properly."
    elif not active_interfaces:
        status_msg = "No active network interface with an IPv4 address found. Check Wi-Fi or Ethernet cable."
    elif active_interfaces and not internet_ok:
        status_msg = "Network interface has an IP address, but external internet gateway cannot be reached."
    elif not dns_ok:
        status_msg = f"Network is connected but DNS resolution failed: {dns_error}. Check DNS server configuration."
    else:
        status_msg = "Network diagnostic completed."

    return {
        "status": "connected" if internet_ok else "disconnected",
        "summary": status_msg,
        "internet_reachable": internet_ok,
        "dns_functional": dns_ok,
        "active_interfaces": active_interfaces,
    }


def get_system_journal_errors(line_count: int = 20):
    """
    Retrieve recent critical/error messages from systemd journal safely.
    Read-only, no-pager, capped output.
    """
    journalctl_bin = shutil.which("journalctl") or "/usr/bin/journalctl"
    try:
        res = subprocess.run(
            [journalctl_bin, "-p", "err", "-n", str(line_count), "--no-pager"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = [l.strip() for l in res.stdout.splitlines() if l.strip()]
        return {
            "available": True,
            "error_count": len(lines),
            "recent_errors": lines,
        }
    except Exception as exc:
        return {
            "available": False,
            "error_count": 0,
            "recent_errors": [],
            "message": f"Could not query journalctl: {exc}",
        }
