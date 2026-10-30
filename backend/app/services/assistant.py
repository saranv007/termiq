"""
TERMIQ AI assistant with Gemini integration and troubleshooting plans.

Preserves the rule-based fallback and adds structured diagnosis
with plan proposals for the approval-based execution engine.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.models import (
    ActionType,
    AskResponse,
    PlanStatus,
    ProposedAction,
    RiskLevel,
    TroubleshootingPlan,
)
from app.services.diagnostics import collect_diagnostics
from app.services.executor import store_plan
from app.services.process_monitor import get_top_processes
from app.services.service_monitor import get_failed_services

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger(__name__)

# Map of action keywords the AI may suggest to validated ActionType values.
_ACTION_KEYWORD_MAP: dict[str, ActionType] = {
    "check_uptime": ActionType.CHECK_UPTIME,
    "uptime": ActionType.CHECK_UPTIME,
    "check_memory": ActionType.CHECK_MEMORY,
    "memory": ActionType.CHECK_MEMORY,
    "free": ActionType.CHECK_MEMORY,
    "check_disk": ActionType.CHECK_DISK,
    "disk": ActionType.CHECK_DISK,
    "df": ActionType.CHECK_DISK,
    "check_processes": ActionType.CHECK_PROCESSES,
    "processes": ActionType.CHECK_PROCESSES,
    "ps": ActionType.CHECK_PROCESSES,
    "check_failed_services": ActionType.CHECK_FAILED_SERVICES,
    "failed_services": ActionType.CHECK_FAILED_SERVICES,
    "systemctl": ActionType.CHECK_FAILED_SERVICES,
    "check_journal_errors": ActionType.CHECK_JOURNAL_ERRORS,
    "journal": ActionType.CHECK_JOURNAL_ERRORS,
    "journalctl": ActionType.CHECK_JOURNAL_ERRORS,
    "check_network": ActionType.CHECK_NETWORK,
    "network": ActionType.CHECK_NETWORK,
    "ss": ActionType.CHECK_NETWORK,
    "check_temperature": ActionType.CHECK_TEMPERATURE,
    "temperature": ActionType.CHECK_TEMPERATURE,
    "sensors": ActionType.CHECK_TEMPERATURE,
}


def _rule_based_answer(
    question: str,
    diagnostics: dict,
    process_report: dict,
    services: dict,
) -> tuple[str, list[str]]:
    """Keep the existing diagnostic answers as a fallback."""

    q = question.lower()
    recommendations: list[str] = []

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


def _compact_processes(processes: list[dict]) -> list[dict]:
    """Share only selected process metrics with the AI."""

    return [
        {
            "name": process.get("name"),
            "cpu_percent": process.get("cpu_percent"),
            "memory_percent": process.get("memory_percent"),
        }
        for process in processes[:5]
    ]


# ── AI-suggested action extraction ────────────────────────────────────

def _parse_suggested_action(ai_text: str) -> Optional[ActionType]:
    """
    Attempt to extract a suggested diagnostic action from the AI response.

    The prompt asks Gemini to include a line like:
        Suggested action: check_memory

    We validate the suggestion against our known action types.
    The AI cannot invent new action types.
    """
    match = re.search(
        r"suggested\s+action:\s*(\S+)",
        ai_text,
        re.IGNORECASE,
    )
    if match:
        raw = match.group(1).strip().lower().rstrip(".")
        action_type = _ACTION_KEYWORD_MAP.get(raw)
        if action_type and action_type != ActionType.MANUAL_STEP:
            return action_type

    return None


def _clean_ai_text(text: str) -> str:
    """Remove the suggested-action metadata line and raw Markdown symbols from user-visible text."""
    cleaned = re.sub(
        r"\n?suggested\s+action:\s*\S+[^\n]*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    # Strip markdown headers (e.g. ### Header)
    cleaned = re.sub(r"#{1,6}\s*", "", cleaned)
    # Strip markdown bold/italics
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    # Strip markdown backticks
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    return cleaned.strip()


def _generate_ai_answer(
    question: str,
    diagnostics: dict,
    process_report: dict,
    services: dict,
) -> tuple[str, Optional[ActionType]]:
    """
    Call Gemini and return (answer_text, optional_suggested_action).

    The prompt asks the model to optionally suggest a diagnostic action
    from a fixed list.  We parse and validate the suggestion server-side.
    """
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

    allowed_actions = ", ".join(
        at.value for at in ActionType if at != ActionType.MANUAL_STEP
    )

    prompt = f"""\
You are TERMIQ, an AI copilot for Ubuntu Linux.

Answer the user's question in clear, beginner-friendly language.
Use the supplied system snapshot when it is relevant.

Rules:
- Distinguish measured facts from possible causes.
- Never invent system metrics, processes, or service failures.
- Do not claim that you executed commands or changed the system.
- If evidence is insufficient, clearly say so.
- Use plain text only. Do not use Markdown headings (###), **bold**, \
bullet points with *, tables, or code fences.
- Keep answers under 120 words whenever practical.
- Structure your answer with these labels on separate lines when useful:
  Summary:
  Evidence:
  Possible causes:
  Recommended next step:
- Give practical advice suitable for a beginner using Ubuntu.

If a deeper diagnostic would help, add exactly one line at the very end:
  Suggested action: <action_type>
where <action_type> is one of: {allowed_actions}
Only suggest an action if it would provide additional useful evidence. \
Do not suggest an action for simple informational questions.

CURRENT SYSTEM SNAPSHOT:
{json.dumps(snapshot, ensure_ascii=False, default=str)}

USER QUESTION:
{question}"""

    client = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=30000),
    )

    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=500,
            ),
        )

        raw_answer = (response.text or "").strip()

        if not raw_answer:
            raise RuntimeError("Gemini returned an empty response.")

        suggested = _parse_suggested_action(raw_answer)
        clean_answer = _clean_ai_text(raw_answer)

        return clean_answer, suggested

    finally:
        client.close()


# ── Plan construction ─────────────────────────────────────────────────

_ACTION_DESCRIPTIONS: dict[ActionType, str] = {
    ActionType.CHECK_UPTIME: "Check system uptime and load averages",
    ActionType.CHECK_MEMORY: "Show detailed memory usage (free -h)",
    ActionType.CHECK_DISK: "Show disk space usage (df -h /)",
    ActionType.CHECK_PROCESSES: "List running processes sorted by CPU usage",
    ActionType.CHECK_FAILED_SERVICES: "List failed systemd services",
    ActionType.CHECK_JOURNAL_ERRORS: "Show recent error-level journal entries",
    ActionType.CHECK_NETWORK: "Show listening network sockets",
    ActionType.CHECK_TEMPERATURE: "Read hardware temperature sensors",
}


def _build_plan(
    question: str,
    answer: str,
    diagnostics: dict,
    suggested_action: Optional[ActionType],
) -> Optional[TroubleshootingPlan]:
    """
    Build a troubleshooting plan when the AI suggests a diagnostic action.

    Returns None if no action was suggested.
    """
    if suggested_action is None:
        return None

    evidence = []
    if diagnostics.get("findings"):
        evidence = [
            {"type": "diagnostic_finding", **f}
            for f in diagnostics["findings"]
        ]

    plan = TroubleshootingPlan(
        question=question,
        diagnosis_summary=answer[:300],
        evidence=evidence,
        possible_causes=[],
        proposed_action=ProposedAction(
            action_type=suggested_action,
            description=_ACTION_DESCRIPTIONS.get(
                suggested_action,
                f"Run diagnostic: {suggested_action.value}",
            ),
            risk_level=RiskLevel.SAFE,
            requires_approval=True,
        ),
        status=PlanStatus.PROPOSED,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )

    store_plan(plan)
    return plan


# ── Main entry point ──────────────────────────────────────────────────

def answer_question(question: str, mode: str = "beginner") -> dict:
    """
    Answer a user question with live diagnostics, AI analysis, and
    an optional troubleshooting plan.

    Returns a dict matching the AskResponse schema.
    All existing fields are preserved for backward compatibility.
    """
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
    suggested_action: Optional[ActionType] = None

    try:
        ai_answer, suggested_action = _generate_ai_answer(
            question,
            diagnostics,
            process_report,
            services,
        )
        answer = ai_answer
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

    # Build a troubleshooting plan if the AI suggested a diagnostic.
    plan = _build_plan(question, answer, diagnostics, suggested_action)

    response = AskResponse(
        question=question,
        answer=answer,
        source=source,
        diagnostics=diagnostics,
        top_processes=process_report,
        failed_services=services,
        findings=findings,
        recommendations=recommendations,
        ai_enabled=ai_enabled,
        plan=plan,
    )

    return response.model_dump(mode="json")
