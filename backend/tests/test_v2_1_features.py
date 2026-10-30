"""
Comprehensive unit test suite for TERMIQ V2.1 features:
- Linux System Monitor & Hardware metrics
- Advanced File Operations (edit, diff, backup, trash, copy, move, duplicates, large files, organize)
- New Project Templates (Flask starter, FastAPI starter, Data Analysis)
- Developer Copilot (error explanation, venv creation, unit testing, git status, editor launch)
- Universal Task Management & Workflow history
- Automation Center workflows
- Notification Center & health alerts
- User Settings & Gemini status
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    FileOperationType,
    FileTaskStatus,
    ProjectTemplate,
    TaskCategory,
)
from app.services import (
    automation_service,
    developer_service,
    diagnostics,
    file_copilot,
    file_security,
    notification_service,
    task_manager,
)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def test_roots(tmp_path):
    projects_dir = tmp_path / "Projects"
    documents_dir = tmp_path / "Documents"
    downloads_dir = tmp_path / "Downloads"
    desktop_dir = tmp_path / "Desktop"

    for d in (projects_dir, documents_dir, downloads_dir, desktop_dir):
        d.mkdir(parents=True, exist_ok=True)

    return [projects_dir, documents_dir, downloads_dir, desktop_dir]


# ══════════════════════════════════════════════════════════════════════
# 1. System Monitor & Diagnostics Tests
# ══════════════════════════════════════════════════════════════════════

class TestSystemMonitorAndDiagnostics:
    def test_system_monitor_endpoint(self, client):
        resp = client.get("/api/v1/system/monitor")
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu" in data
        assert "memory" in data
        assert "swap" in data
        assert "disk" in data
        assert "network" in data
        assert "uptime_seconds" in data
        assert "uptime_human" in data
        assert "temperatures" in data
        assert isinstance(data["cpu"]["per_core_percent"], list)
        assert isinstance(data["memory"]["total_gb"], (int, float))

    def test_diagnose_slowdown(self, client):
        resp = client.get("/api/v1/system/diagnostics/slowdown")
        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "cpu_percent" in data
        assert "memory_percent" in data
        assert "top_cpu_processes" in data

    def test_diagnose_network(self, client):
        resp = client.get("/api/v1/system/diagnostics/network")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "summary" in data
        assert "active_interfaces" in data

    def test_diagnose_journal_errors(self, client):
        resp = client.get("/api/v1/system/diagnostics/journal-errors?line_count=10")
        assert resp.status_code == 200
        data = resp.json()
        assert "available" in data
        assert "recent_errors" in data


# ══════════════════════════════════════════════════════════════════════
# 2. Advanced File Operations Tests
# ══════════════════════════════════════════════════════════════════════

class TestAdvancedFileOperations:
    def test_safe_edit_file_with_diff_and_backup(self, test_roots):
        file_p = test_roots[0] / "editable.txt"
        file_p.write_text("Hello World\nLine 2\n", encoding="utf-8")

        res = file_security.safe_edit_file(
            file_p,
            new_content="Hello TERMIQ\nLine 2\nLine 3\n",
            create_backup=True,
            approved_roots=test_roots,
        )
        assert res["success"] is True
        assert "backup_path" in res
        assert res["backup_path"] is not None
        assert Path(res["backup_path"]).exists()
        assert "diff" in res
        assert "-Hello World" in res["diff"]
        assert "+Hello TERMIQ" in res["diff"]
        assert file_p.read_text(encoding="utf-8") == "Hello TERMIQ\nLine 2\nLine 3\n"

    def test_safe_copy_and_move_file(self, test_roots):
        src = test_roots[0] / "source.txt"
        src.write_text("Copy Me", encoding="utf-8")

        dest_copy = test_roots[1] / "copied.txt"
        res_copy = file_security.safe_copy_file(src, dest_copy, approved_roots=test_roots)
        assert res_copy["success"] is True
        assert dest_copy.exists()
        assert dest_copy.read_text(encoding="utf-8") == "Copy Me"

        dest_move = test_roots[1] / "moved.txt"
        res_move = file_security.safe_move_file(dest_copy, dest_move, approved_roots=test_roots)
        assert res_move["success"] is True
        assert dest_move.exists()
        assert not dest_copy.exists()

    def test_safe_trash_file(self, test_roots):
        target = test_roots[0] / "trash_me.txt"
        target.write_text("Temporary text", encoding="utf-8")

        res = file_security.safe_trash_file(target, approved_roots=test_roots)
        assert res["success"] is True
        assert not target.exists()
        assert "trashed_path" in res

    def test_safe_trash_root_prevented(self, test_roots):
        # Trashing an approved root directory itself must be blocked
        res = file_security.safe_trash_file(test_roots[0], approved_roots=test_roots)
        assert res["success"] is False
        assert "Cannot delete or trash an approved root" in res["error"]

    def test_safe_find_duplicates(self, test_roots):
        f1 = test_roots[0] / "file1.txt"
        f2 = test_roots[0] / "file2.txt"
        f3 = test_roots[0] / "file3.txt"

        content = "Exact duplicate content repeated in files for testing duplicate detection."
        f1.write_text(content, encoding="utf-8")
        f2.write_text(content, encoding="utf-8")
        f3.write_text("Different content altogether here.", encoding="utf-8")

        res = file_security.safe_find_duplicates(test_roots[0], min_bytes=10, approved_roots=test_roots)
        assert res["success"] is True
        assert res["total_groups"] >= 1
        group = res["duplicate_groups"][0]
        assert str(f1) in group["files"]
        assert str(f2) in group["files"]
        assert str(f3) not in group["files"]

    def test_safe_find_large_files(self, test_roots):
        small = test_roots[0] / "small.txt"
        small.write_text("small", encoding="utf-8")
        large = test_roots[0] / "large.dat"
        large.write_bytes(b"X" * 2000)

        res = file_security.safe_find_large_files(test_roots[0], min_bytes=1000, approved_roots=test_roots)
        assert res["success"] is True
        assert res["total_found"] == 1
        assert res["files"][0]["name"] == "large.dat"

    def test_safe_organize_folder(self, test_roots):
        downloads = test_roots[2]
        (downloads / "document.pdf").write_text("pdf dummy", encoding="utf-8")
        (downloads / "photo.png").write_text("png dummy", encoding="utf-8")
        (downloads / "script.py").write_text("py dummy", encoding="utf-8")

        # Dry run test
        res_dry = file_security.safe_organize_folder(downloads, dry_run=True, approved_roots=test_roots)
        assert res_dry["success"] is True
        assert res_dry["dry_run"] is True
        assert res_dry["total_files"] == 3

        # Actual execution test
        res_exec = file_security.safe_organize_folder(downloads, dry_run=False, approved_roots=test_roots)
        assert res_exec["success"] is True
        assert res_exec["moved_count"] == 3
        assert (downloads / "Documents" / "document.pdf").exists()
        assert (downloads / "Images" / "photo.png").exists()
        assert (downloads / "Code" / "script.py").exists()

    def test_safe_get_metadata(self, test_roots):
        target = test_roots[0] / "sample_meta.txt"
        target.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")

        res = file_security.safe_get_metadata(target, approved_roots=test_roots)
        assert res["success"] is True
        assert res["name"] == "sample_meta.txt"
        assert res["is_file"] is True
        assert res["is_dir"] is False
        assert res["lines_count"] == 3


# ══════════════════════════════════════════════════════════════════════
# 3. New Project Templates Tests (Flask, FastAPI, Data Analysis)
# ══════════════════════════════════════════════════════════════════════

class TestNewProjectTemplates:
    def test_flask_starter_template(self, test_roots):
        files = file_copilot.build_template_files(
            ProjectTemplate.FLASK_STARTER,
            project_name="my_flask_app",
            functional_description="Web app with Flask",
        )
        filenames = {f.relative_path for f in files}
        assert "app.py" in filenames
        assert "templates/index.html" in filenames
        assert "requirements.txt" in filenames
        assert "README.md" in filenames
        assert ".gitignore" in filenames

        # Verify app.py syntax
        app_file = next(f for f in files if f.relative_path == "app.py")
        code_obj = compile(app_file.content, "app.py", "exec")
        assert code_obj is not None
        assert "flask" in app_file.content.lower()

    def test_fastapi_starter_template(self, test_roots):
        files = file_copilot.build_template_files(
            ProjectTemplate.FASTAPI_STARTER,
            project_name="my_fastapi_app",
            functional_description="REST API with FastAPI",
        )
        filenames = {f.relative_path for f in files}
        assert "main.py" in filenames
        assert "requirements.txt" in filenames
        assert "README.md" in filenames
        assert ".gitignore" in filenames

        main_file = next(f for f in files if f.relative_path == "main.py")
        code_obj = compile(main_file.content, "main.py", "exec")
        assert code_obj is not None
        assert "fastapi" in main_file.content.lower()

    def test_data_analysis_template(self, test_roots):
        files = file_copilot.build_template_files(
            ProjectTemplate.DATA_ANALYSIS,
            project_name="sales_analysis",
            functional_description="Analyze sales CSV data",
        )
        filenames = {f.relative_path for f in files}
        assert "analysis.py" in filenames
        assert "data/README.md" in filenames
        assert "README.md" in filenames
        assert ".gitignore" in filenames

        analysis_file = next(f for f in files if f.relative_path == "analysis.py")
        code_obj = compile(analysis_file.content, "analysis.py", "exec")
        assert code_obj is not None


# ══════════════════════════════════════════════════════════════════════
# 4. Developer Copilot Tests
# ══════════════════════════════════════════════════════════════════════

class TestDeveloperCopilot:
    def test_explain_index_error(self):
        sample_error = """Traceback (most recent call last):
  File "main.py", line 14, in <module>
    item = items[10]
IndexError: list index out of range"""

        resp = developer_service.explain_python_error(sample_error)
        assert resp.error_type == "IndexError"
        assert "list" in resp.summary.lower()
        assert len(resp.possible_causes) > 0
        assert resp.recommended_fix != ""
        assert resp.code_example is not None

    def test_explain_zero_division_error(self):
        sample_error = "ZeroDivisionError: division by zero"
        resp = developer_service.explain_python_error(sample_error)
        assert resp.error_type == "ZeroDivisionError"
        assert "zero" in resp.summary.lower()

    def test_run_project_tests_success(self, test_roots):
        proj = test_roots[0] / "testable_proj"
        tests_dir = proj / "tests"
        tests_dir.mkdir(parents=True)

        # Write passing unittest
        (tests_dir / "test_sample.py").write_text("""import unittest
class SampleTest(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(1 + 1, 2)
""", encoding="utf-8")

        res = developer_service.run_project_tests(proj, approved_roots=test_roots)
        assert res.success is True
        assert res.passed >= 1
        assert res.failed == 0

    def test_get_git_status_non_repo(self, test_roots):
        res = developer_service.get_git_status(test_roots[0], approved_roots=test_roots)
        assert res.is_git_repo is False
        assert res.clean is False


# ══════════════════════════════════════════════════════════════════════
# 5. Task Manager & Notifications Tests
# ══════════════════════════════════════════════════════════════════════

class TestTaskManagerAndNotifications:
    def test_task_manager_lifecycle(self):
        task = task_manager.record_task(
            title="Diagnose RAM",
            category=TaskCategory.SYSTEM_DIAGNOSTIC,
            request_text="Why is RAM high?",
            status="ready_for_review",
            summary="Checked top memory consumers",
        )
        assert task.task_id is not None
        assert task.title == "Diagnose RAM"

        # Update task
        updated = task_manager.update_task_status(
            task.task_id,
            status="completed",
            verification_result="All checks completed",
        )
        assert updated.status == "completed"

        # List tasks
        all_tasks = task_manager.list_tasks()
        assert any(t.task_id == task.task_id for t in all_tasks)

        # Cancel task
        ok_cancel, _ = task_manager.cancel_task(task.task_id)
        assert ok_cancel is False  # Cannot cancel completed task

    def test_notification_center(self):
        notif = notification_service.add_notification(
            title="Backup Ready",
            message="File backup created successfully.",
            category="file",
        )
        assert notif.id is not None
        assert notif.is_read is False

        # Retrieve
        unread = notification_service.get_notifications(unread_only=True)
        assert any(n.id == notif.id for n in unread)

        # Mark read
        notification_service.mark_as_read(notif.id)
        unread_after = notification_service.get_notifications(unread_only=True)
        assert not any(n.id == notif.id for n in unread_after)

        # Dismiss
        ok_dismiss = notification_service.dismiss_notification(notif.id)
        assert ok_dismiss is True


# ══════════════════════════════════════════════════════════════════════
# 6. Automation Workflows & Settings Tests
# ══════════════════════════════════════════════════════════════════════

class TestAutomationAndSettings:
    def test_list_and_run_automation_workflow(self, test_roots):
        workflows = automation_service.list_workflows()
        assert len(workflows) >= 5
        wf_ids = [w.id for w in workflows]
        assert "organize_downloads" in wf_ids
        assert "check_disk_space" in wf_ids

        # Run check_disk_space (safe, no approval required)
        res = automation_service.execute_workflow(
            "check_disk_space",
            approved=True,
            approved_roots=test_roots,
        )
        assert res["success"] is True
        assert res["status"] == "completed"

    def test_settings_api(self, client):
        resp = client.get("/api/v1/settings")
        assert resp.status_code == 200
        settings = resp.json()
        assert "refresh_interval_seconds" in settings
        assert "mode" in settings
        assert "approved_roots" in settings

        resp_gemini = client.get("/api/v1/settings/gemini-status")
        assert resp_gemini.status_code == 200
        gdata = resp_gemini.json()
        assert "configured" in gdata
        assert "provider" in gdata
        assert "model" in gdata
        # Ensure raw secret is not leaked in hint
        assert not gdata["key_hint"].startswith("AIza")

