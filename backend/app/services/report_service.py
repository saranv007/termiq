
from datetime import datetime, timezone

from app.services.diagnostics import collect_diagnostics
from app.services.process_monitor import get_top_processes
from app.services.service_monitor import get_failed_services


def build_system_report():
    diagnostics = collect_diagnostics()
    processes = get_top_processes()
    services = get_failed_services()

    findings = list(diagnostics.get("findings", []))

    if services.get("available"):
        for service in services.get("services", []):
            if service.get("sub") == "failed":
                findings.append({
                    "severity": "warning",
                    "issue": f"Service {service['unit']} is in a failed state",
                    "evidence": service,
                    "recommendation": (
                        "Inspect the service logs and configuration "
                        "before attempting a restart."
                    ),
                })
    else:
        findings.append({
            "severity": "info",
            "issue": "Failed-service status could not be retrieved",
            "evidence": services.get("error", "Unknown error"),
        })

    recommendations = []

    for finding in findings:
        if finding.get("recommendation"):
            recommendations.append(finding["recommendation"])

    if not recommendations:
        recommendations.append(
            "No automatic corrective action is needed based on "
            "the current findings. Continue monitoring system health."
        )

    return {
        "application": "TERMIQ",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "system_diagnostics": diagnostics,
        "top_processes": processes,
        "failed_services": services,
        "findings": findings,
        "recommendations": recommendations,
    }
