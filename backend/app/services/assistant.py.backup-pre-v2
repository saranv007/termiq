
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.services.diagnostics import collect_diagnostics
from app.services.process_monitor import get_top_processes
from app.services.service_monitor import get_failed_services


load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)


def _rule_based_answer(
    question,
    diagnostics,
    process_report,
    services,
):
    """Keep the existing diagnostic answers as a fallback."""

    q = question.lower()
    recommendations = []

    memory_processes = process_report["by_memory"]
    cpu_processes = process_report["by_cpu"]

    high_cpu = [
        process for process in cpu_processes
        if process.get("cpu_percent", 0) >= 50
    ]

    high_memory = [
        process for process in memory_processes
        if process.get("memory_percent", 0) >= 10
    ]

    failed_services = [
        service for service in services.get("services", [])
        if service.get("sub") == "failed"
    ]

    if any(word in q for word in ("ram", "memory")):
        answer = (
            f"Current memory usage is "
            f"{diagnostics['memory_percent']}%. "
        )

        if high_memory:
            names = ", ".join(p["name"] for p in high_memory)
            answer += f"High-memory processes: {names}."
        else:
            answer += "No sampled process uses at least 10% RAM."

        recommendations.append(
            "Review memory usage if the system becomes slow."
        )

    elif any(word in q for word in ("disk", "storage", "space")):
        usage = diagnostics["disk_percent"]
        answer = f"Current disk usage is {usage}%."

        recommendations.append(
            "Review large files before deleting anything."
            if usage >= 90
            else "Disk usage is below the 90% warning threshold."
        )

    elif any(word in q for word in ("cpu", "processor")):
        answer = (
            f"Current CPU usage is "
            f"{diagnostics['cpu_percent']}%. "
        )

        if high_cpu:
            names = ", ".join(
                f"{p['name']} ({p['cpu_percent']}%)"
                for p in high_cpu
            )
            answer += f"High-CPU processes: {names}."
        else:
            answer += "No sampled process meets the 50% CPU threshold."

        recommendations.append(
            "Inspect high-CPU processes before taking action."
        )

    elif any(word in q for word in ("service", "systemd", "failed")):
        if not services.get("available"):
            answer = "Failed-service information is unavailable."
        elif failed_services:
            names = ", ".join(
                service["unit"] for service in failed_services
            )
            answer = f"Failed services detected: {names}."
        else:
            answer = "No failed services were reported by the current query."

        recommendations.append(
            "Inspect service status and logs before restarting services."
        )

    elif any(word in q for word in ("slow", "performance", "lag", "freeze")):
        answer = (
            f"System snapshot: CPU {diagnostics['cpu_percent']}%, "
            f"RAM {diagnostics['memory_percent']}%, "
            f"disk {diagnostics['disk_percent']}%."
        )

        if high_cpu:
            names = ", ".join(p["name"] for p in high_cpu)
            answer += f" Potential CPU contributors: {names}."

        if high_memory:
            names = ", ".join(p["name"] for p in high_memory)
            answer += f" Higher-memory processes: {names}."

        if failed_services:
            names = ", ".join(
                service["unit"] for service in failed_services
            )
            answer += f" Failed services: {names}."

        answer += (
            " These observations may help narrow down the cause, "
            "but do not prove which process caused the slowdown."
        )

        recommendations.append(
            "Compare another snapshot and inspect relevant logs."
        )

    else:
        answer = (
            "I can help investigate Linux CPU, memory, disk, "
            "performance, and service issues."
        )
        recommendations.append(
            "Ask about your system or describe the problem you are seeing."
        )

    return answer, recommendations


def _compact_processes(processes):
    """Share only selected process metrics with the AI."""

    return [
        {
            "name": process.get("name"),
            "cpu_percent": process.get("cpu_percent"),
            "memory_percent": process.get("memory_percent"),
        }
        for process in processes[:5]
    ]


def _generate_ai_answer(
    question,
    diagnostics,
    process_report,
    services,
):
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is missing from backend/.env")

    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    failed_services = [
        {
            "unit": service.get("unit"),
            "state": service.get("sub"),
        }
        for service in services.get("services", [])
        if service.get("sub") == "failed"
    ]

    # Send a limited system snapshot rather than the full process report.
    snapshot = {
        "cpu_percent": diagnostics.get("cpu_percent"),
        "memory_percent": diagnostics.get("memory_percent"),
        "disk_percent": diagnostics.get("disk_percent"),
        "top_cpu_processes": _compact_processes(
            process_report["by_cpu"]
        ),
        "top_memory_processes": _compact_processes(
            process_report["by_memory"]
        ),
        "failed_services": failed_services,
        "findings": diagnostics.get("findings", [])[:8],
    }

    prompt = f"""
You are TERMIQ, an AI copilot for Ubuntu Linux.

Answer the user's question in clear, beginner-friendly language.
Use the supplied system snapshot when it is relevant.

Rules:
- Distinguish measured facts from possible causes.
- Never invent system metrics, processes, or service failures.
- Do not claim that you executed commands or changed the system.
- Explain proposed terminal commands before suggesting them.
- Never execute commands or recommend automatic destructive changes.
- If evidence is insufficient, clearly say so.
- Use plain text only. Do not use Markdown headings, **bold markers**,
  hashtags, tables, or code fences.
- Keep answers under 120 words whenever practical.
- Prefer this structure when useful:
  Summary:
  Possible causes:
  Recommended next step:
- Give practical advice suitable for a beginner using Ubuntu.

CURRENT SYSTEM SNAPSHOT:
{json.dumps(snapshot, ensure_ascii=False, default=str)}

USER QUESTION:
{question}
"""

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=60000),
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=600,
            ),
        )

        answer = (response.text or "").strip()

        if not answer:
            raise RuntimeError("Gemini returned an empty response.")

        return answer

    finally:
        client.close()


def answer_question(question: str) -> dict:
    # Collect live Linux information using the existing services.
    diagnostics = collect_diagnostics()
    process_report = get_top_processes(limit=5)
    services = get_failed_services()

    findings = diagnostics.get("findings", [])

    # Keep a working fallback if Gemini is unavailable.
    answer, recommendations = _rule_based_answer(
        question,
        diagnostics,
        process_report,
        services,
    )

    ai_enabled = False
    source = "live_system_diagnostics"

    try:
        answer = _generate_ai_answer(
            question,
            diagnostics,
            process_report,
            services,
        )
        ai_enabled = True
        source = "gemini_live_system_diagnostics"

    except Exception:
        logger.exception(
            "Gemini request failed; using the rule-based answer."
        )
        recommendations.append(
            "The AI service was unavailable for this request; "
            "the displayed answer uses the local diagnostic fallback."
        )

    return {
        "question": question,
        "answer": answer,
        "source": source,
        "diagnostics": diagnostics,
        "top_processes": process_report,
        "failed_services": services,
        "findings": findings,
        "recommendations": recommendations,
        "ai_enabled": ai_enabled,
    }
