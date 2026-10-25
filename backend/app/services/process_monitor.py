
import psutil


def get_top_processes(limit: int = 5, sample_seconds: float = 0.5):
    processes = []

    # Prime CPU counters before measuring the sampling interval.
    for proc in psutil.process_iter(
        ["pid", "name", "memory_percent"]
    ):
        try:
            proc.cpu_percent(interval=None)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Measure CPU usage over a short interval.
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=sample_seconds)

    for proc in psutil.process_iter(
        ["pid", "name", "memory_percent"]
    ):
        try:
            info = proc.info

            processes.append({
                "pid": info["pid"],
                "name": info["name"] or "unknown",
                "cpu_percent": round(proc.cpu_percent(interval=None), 2),
                "memory_percent": round(
                    info["memory_percent"] or 0, 2
                ),
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Return separate rankings so CPU-heavy processes aren't hidden
    # by processes that only use a lot of memory.
    by_cpu = sorted(
        processes,
        key=lambda p: p["cpu_percent"],
        reverse=True,
    )[:limit]

    by_memory = sorted(
        processes,
        key=lambda p: p["memory_percent"],
        reverse=True,
    )[:limit]

    return {
        "by_cpu": by_cpu,
        "by_memory": by_memory,
        "sample_seconds": sample_seconds,
    }
