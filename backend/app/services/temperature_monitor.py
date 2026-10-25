
from pathlib import Path


HWMON_ROOT = Path("/sys/class/hwmon")


def get_temperatures():
    readings = []

    if not HWMON_ROOT.exists():
        return {
            "available": False,
            "readings": [],
            "message": "Linux hardware-monitor sensors are unavailable.",
        }

    for hwmon in HWMON_ROOT.glob("hwmon*"):
        try:
            name_file = hwmon / "name"
            sensor_name = (
                name_file.read_text().strip()
                if name_file.exists()
                else hwmon.name
            )

            for temp_file in hwmon.glob("temp*_input"):
                try:
                    raw_value = int(temp_file.read_text().strip())
                    temperature_c = raw_value / 1000.0

                    label_file = temp_file.with_name(
                        temp_file.name.replace("_input", "_label")
                    )

                    label = (
                        label_file.read_text().strip()
                        if label_file.exists()
                        else temp_file.name.replace("_input", "")
                    )

                    readings.append({
                        "sensor": sensor_name,
                        "label": label,
                        "temperature_c": round(temperature_c, 1),
                    })
                except (ValueError, OSError):
                    continue
        except OSError:
            continue

    return {
        "available": bool(readings),
        "readings": readings,
        "message": (
            "Readings are from available Linux hardware-monitor sensors."
            if readings
            else "No readable hardware-monitor temperature sensors found."
        ),
    }
