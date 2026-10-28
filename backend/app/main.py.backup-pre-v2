import platform
import shutil
import psutil

from fastapi import FastAPI
from app.services.diagnostics import collect_diagnostics
from app.services.process_monitor import get_top_processes
from app.services.service_monitor import get_failed_services
from app.services.report_service import build_system_report
from pydantic import BaseModel
from app.services.assistant import answer_question
app = FastAPI(
    title="TERMIQ API",
    description="Meta AI-powered Linux copilot",
    version="0.2.0",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "application": "TERMIQ",
    }


@app.get("/api/v1/system/summary")
def system_summary():
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage("/")

    return {
        "os": platform.platform(),
        "python_version": platform.python_version(),
        "cpu": {
            "logical_cores": psutil.cpu_count(),
            "usage_percent": psutil.cpu_percent(interval=0.5),
        },
        "memory": {
            "total_gb": round(memory.total / (1024 ** 3), 2),
            "used_percent": memory.percent,
            "available_gb": round(
                memory.available / (1024 ** 3), 2
            ),
        },
        "disk": {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_percent": round(
                disk.used / disk.total * 100, 2
            ),
            "free_gb": round(disk.free / (1024 ** 3), 2),
        },
    }
@app.get("/api/v1/system/diagnostics")
def system_diagnostics():
    return collect_diagnostics()
@app.get("/api/v1/system/processes")
def system_processes():
    return {
        "processes": get_top_processes()
    }

@app.get("/api/v1/system/failed-services")
def failed_services():
    return get_failed_services()
@app.get("/api/v1/system/report")
def system_report():
    return build_system_report()

class AskRequest(BaseModel):
    question: str


@app.post("/api/v1/assistant/ask")
def assistant_ask(request: AskRequest):
    return answer_question(request.question)
