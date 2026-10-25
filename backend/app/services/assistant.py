
from app.services.diagnostics import collect_diagnostics
from app.services.process_monitor import get_top_processes
from app.services.service_monitor import get_failed_services


def answer_question(question: str) -> dict:
    diagnostics = collect_diagnostics()
    process_report = get_top_processes(limit=5)
    processes = process_report["by_memory"]
    cpu_processes = process_report["by_cpu"]
    services = get_failed_services()

    q = question.lower()
    findings = diagnostics.get("findings", [])
    recommendations = []

    # Identify processes with high CPU or memory usage.
    high_cpu = [
        process for process in cpu_processes
        if process.get("cpu_percent", 0) >= 50
    ]

    high_memory = [
        process for process in processes
        if process.get("memory_percent", 0) >= 10
    ]

    failed_services = [
        service for service in services.get("services", [])
        if service.get("sub") == "failed"
    ]

    # Answer questions about RAM.
    if any(word in q for word in ("ram", "memory")):
        answer = (
            f"Current memory usage is "
            f"{diagnostics['memory_percent']}%. "
            f"Available RAM information is based on a live snapshot."
        )

        if high_memory:
            names = ", ".join(p["name"] for p in high_memory)
            answer += f" Processes using at least 10% RAM: {names}."
        else:
            answer += " No process in the top-five sample uses 10% or more RAM."

        recommendations.append(
            "Review memory usage again if the system becomes slow."
        )

    # Answer questions about disk space.
    elif any(word in q for word in ("disk", "storage", "space")):
        usage = diagnostics["disk_percent"]
        answer = f"Current disk usage is {usage}%."

        if usage >= 90:
            recommendations.append(
                "Inspect disk usage and review large files before deleting anything."
            )
        else:
            recommendations.append(
                "Disk usage is below the 90% warning threshold."
            )

    # Answer questions about CPU usage.
    elif any(word in q for word in ("cpu", "processor")):
        answer = (
            f"Current CPU usage is {diagnostics['cpu_percent']}%. "
            "This is a snapshot and may change."
        )

        if high_cpu:
            names = ", ".join(
                f"{p['name']} ({p['cpu_percent']}%)"
                for p in high_cpu
            )
            answer += f" High-CPU processes in the sample: {names}."
        else:
            answer += " No sampled process currently meets the 50% CPU threshold."

        recommendations.append(
            "If CPU usage stays high, inspect the identified processes before taking action."
        )

    # Answer questions about failed services.
    elif any(word in q for word in ("service", "systemd", "failed")):
        if not services.get("available"):
            answer = "TERMIQ could not retrieve failed-service information."
            recommendations.append(
                "Check systemd access and inspect the backend logs."
            )
        elif failed_services:
            names = ", ".join(s["unit"] for s in failed_services)
            answer = f"Failed services detected: {names}."
            recommendations.append(
                "Inspect each service's status, logs, and configuration before restarting it."
            )
        else:
            answer = "The current systemd query reports no failed services."

    # Answer general performance questions.
    elif any(word in q for word in ("slow", "performance", "lag", "freeze")):
        answer = (
            f"System snapshot: CPU {diagnostics['cpu_percent']}%, "
            f"RAM {diagnostics['memory_percent']}%, "
            f"disk {diagnostics['disk_percent']}%."
        )

        if high_cpu:
            names = ", ".join(
                f"{p['name']} ({p['cpu_percent']}%)"
                for p in high_cpu
            )
            answer += f" Possible CPU contributors: {names}."
        else:
            answer += " No sampled process meets the high-CPU threshold."

        if high_memory:
            names = ", ".join(p["name"] for p in high_memory)
            answer += f" Higher-memory processes: {names}."

        if failed_services:
            names = ", ".join(s["unit"] for s in failed_services)
            answer += f" Failed services: {names}."

        answer += (
            " These observations can help narrow down the cause, "
            "but do not prove that a particular process caused the slowdown."
        )

        recommendations.append(
            "Compare another system snapshot and inspect relevant process or service logs."
        )

    else:
        answer = (
            "I can currently answer basic questions about CPU, RAM, disk, "
            "system performance, and failed services. "
            "Meta AI integration is not enabled yet."
        )
        recommendations.append(
            "Ask about CPU usage, memory, disk space, performance, or failed services."
        )

    return {
        "question": question,
        "answer": answer,
        "source": "live_system_diagnostics",
        "diagnostics": diagnostics,
        "top_processes": process_report,
        "failed_services": services,
        "findings": findings,
        "recommendations": recommendations,
        "ai_enabled": False,
    }
