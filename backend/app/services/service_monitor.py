
import subprocess


def get_failed_services():
    try:
        result = subprocess.run(
            [
                "systemctl", "--failed",
                "--no-legend", "--no-pager"
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode not in (0, 1):
            return {
                "available": False,
                "services": [],
                "error": result.stderr.strip()[:300],
            }

        services = []

        for line in result.stdout.splitlines():
            parts = line.split()

            # Skip systemd's decorative ● status marker.
            if parts and parts[0] == "●":
                parts = parts[1:]

            if not parts:
                continue

            services.append({
                "unit": parts[0],
                "load": parts[1] if len(parts) > 1 else "",
                "active": parts[2] if len(parts) > 2 else "",
                "sub": parts[3] if len(parts) > 3 else "",
            })

        return {
            "available": True,
            "count": len(services),
            "services": services,
        }

    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "available": False,
            "services": [],
            "error": str(exc),
        }
