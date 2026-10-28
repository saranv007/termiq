"""
Comprehensive test suite for TERMIQ V2.0 File & Folder Copilot.

Tests cover:
- Natural-language request parsing & intent detection
- Missing-information clarification workflows
- Path validation, approved root enforcement, and path traversal rejection
- Symlink escape and sensitive path rejection (.ssh, .config, .env)
- Invalid filename rejection
- Existing target conflict handling & overwrite prevention
- Parent directory creation approval check
- Approval binding, TTL expiry, and anti-replay (single-use)
- Cancellation & rejection workflows
- Content size limits and binary file handling
- Directory listing and recursive file searching
- Project template generation (Python starter, HTML website, Markdown docs)
- Audit log verification
- Zero shell execution guarantees
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    FileOperationType,
    FileTaskStatus,
    ProjectTemplate,
)
from app.services import file_copilot, file_security


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_file_state():
    """Reset file copilot in-memory store and audit log between tests."""
    with file_copilot._file_lock:
        file_copilot._file_tasks.clear()
        file_copilot._file_audit_log.clear()
    yield
    with file_copilot._file_lock:
        file_copilot._file_tasks.clear()
        file_copilot._file_audit_log.clear()


@pytest.fixture
def test_roots(tmp_path):
    """Provide a controlled set of approved roots inside tmp_path."""
    projects_dir = tmp_path / "Projects"
    documents_dir = tmp_path / "Documents"
    downloads_dir = tmp_path / "Downloads"
    desktop_dir = tmp_path / "Desktop"

    for d in (projects_dir, documents_dir, downloads_dir, desktop_dir):
        d.mkdir(parents=True, exist_ok=True)

    return [projects_dir, documents_dir, downloads_dir, desktop_dir]


# ══════════════════════════════════════════════════════════════════════
# 1. Natural-Language Request Parsing
# ══════════════════════════════════════════════════════════════════════

class TestNLUParsing:
    def test_parse_python_calculator_request(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a Python file for a calculator in my Projects folder.",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.CREATE_FILE
        assert task.target_name == "calculator.py"
        assert task.target_directory == "Projects"
        assert task.status == FileTaskStatus.AWAITING_APPROVAL
        assert len(task.planned_files) == 1
        assert "def add" in task.planned_files[0].content or "calculator" in task.planned_files[0].content

    def test_parse_readme_request(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a README in Documents",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.CREATE_FILE
        assert task.target_name == "README.md"
        assert task.target_directory == "Documents"
        assert task.status == FileTaskStatus.AWAITING_APPROVAL

    def test_parse_create_folder_request(self, test_roots):
        task = file_copilot.parse_file_request(
            "Make a folder named College Notes in Documents",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.CREATE_FOLDER
        assert task.target_name == "College Notes"
        assert task.target_directory == "Documents"
        assert task.status == FileTaskStatus.AWAITING_APPROVAL

    def test_parse_search_request(self, test_roots):
        task = file_copilot.parse_file_request(
            "Find Python files in my Projects folder",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.SEARCH_FILES
        assert "*.py" in task.target_name or "python" in task.target_name.lower()
        assert task.target_directory == "Projects"

    def test_parse_list_request(self, test_roots):
        task = file_copilot.parse_file_request(
            "Show me the files in Downloads",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.LIST_DIR
        assert task.target_directory == "Downloads"

    def test_parse_website_project_request(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a small HTML, CSS, and JavaScript website in Projects",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.CREATE_PROJECT
        assert task.template == ProjectTemplate.HTML_WEBSITE
        assert task.target_directory == "Projects"
        assert len(task.planned_files) == 4  # index.html, style.css, script.js, README.md


# ══════════════════════════════════════════════════════════════════════
# 2. Clarification Workflow
# ══════════════════════════════════════════════════════════════════════

class TestClarification:
    def test_missing_filename_and_folder_requires_clarification(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a new file please",
            approved_roots=test_roots,
        )
        assert task.status == FileTaskStatus.NEEDS_CLARIFICATION
        assert len(task.clarification_questions) >= 1
        assert "filename" in task.clarification_fields_needed

    def test_clarify_task_with_answers_advances_to_awaiting_approval(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a Python script",
            approved_roots=test_roots,
        )
        # Missing destination directory
        assert task.status == FileTaskStatus.NEEDS_CLARIFICATION

        ok, msg, updated = file_copilot.clarify_task(
            task.task_id,
            answers={"directory": "Projects", "filename": "app.py"},
            approved_roots=test_roots,
        )
        assert ok is True
        assert updated.status == FileTaskStatus.AWAITING_APPROVAL
        assert updated.target_name == "app.py"
        assert updated.approval_token is not None


# ══════════════════════════════════════════════════════════════════════
# 3. Path Security & Approved Roots
# ══════════════════════════════════════════════════════════════════════

class TestPathSecurity:
    def test_valid_path_inside_approved_root(self, test_roots):
        valid, err = file_security.validate_path(
            test_roots[0] / "test.txt",
            approved_roots=test_roots,
        )
        assert err is None
        assert valid == test_roots[0] / "test.txt"

    def test_path_traversal_rejected(self, test_roots):
        valid, err = file_security.validate_path(
            test_roots[0] / ".." / ".." / "etc" / "passwd",
            approved_roots=test_roots,
        )
        assert valid is None
        assert "outside approved directories" in err.lower() or "sensitive" in err.lower()

    def test_sensitive_ssh_path_rejected(self, test_roots):
        valid, err = file_security.validate_path(
            Path.home() / ".ssh" / "id_rsa",
            approved_roots=test_roots,
        )
        assert valid is None
        assert "forbidden" in err.lower() or "sensitive" in err.lower()

    def test_sensitive_env_path_rejected(self, test_roots):
        valid, err = file_security.validate_path(
            test_roots[0] / ".env",
            approved_roots=test_roots,
        )
        assert valid is None
        assert "forbidden" in err.lower() or "sensitive" in err.lower()

    def test_symlink_escape_rejected(self, test_roots, tmp_path):
        outside_dir = tmp_path / "outside_jail"
        outside_dir.mkdir()
        symlink_in_root = test_roots[0] / "escape_link"
        os.symlink(outside_dir, symlink_in_root)

        valid, err = file_security.validate_path(
            symlink_in_root / "target.txt",
            approved_roots=test_roots,
        )
        assert valid is None
        assert "symlink" in err.lower() or "outside approved" in err.lower()

    def test_invalid_filename_characters(self):
        assert file_security.is_safe_filename("valid_name.py") is True
        assert file_security.is_safe_filename("invalid/name.py") is False
        assert file_security.is_safe_filename("invalid\\name.py") is False
        assert file_security.is_safe_filename("invalid\0name.py") is False
        assert file_security.is_safe_filename("..") is False
        assert file_security.is_safe_filename(".ssh") is False
        assert file_security.is_safe_filename(".env") is False


# ══════════════════════════════════════════════════════════════════════
# 4. Exclusive Creation & Conflict Handling
# ══════════════════════════════════════════════════════════════════════

class TestCreationAndConflicts:
    def test_create_file_success(self, test_roots):
        target = test_roots[0] / "notes.txt"
        res = file_security.safe_create_file(
            target,
            content="Hello TERMIQ",
            approved_roots=test_roots,
        )
        assert res["success"] is True
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "Hello TERMIQ"

    def test_overwrite_forbidden(self, test_roots):
        target = test_roots[0] / "existing.txt"
        target.write_text("Original content", encoding="utf-8")

        res = file_security.safe_create_file(
            target,
            content="Attempted overwrite",
            approved_roots=test_roots,
        )
        assert res["success"] is False
        assert res.get("conflict") is True
        assert target.read_text(encoding="utf-8") == "Original content"

    def test_conflict_detected_in_task_planning(self, test_roots):
        existing = test_roots[0] / "calc.py"
        existing.write_text("# existing", encoding="utf-8")

        task = file_copilot.parse_file_request(
            "Create a Python file for a calculator named calc.py in Projects",
            approved_roots=test_roots,
        )
        assert task.conflict_detected is True
        assert "already exists" in task.conflict_message.lower()

    def test_create_folder_success(self, test_roots):
        folder = test_roots[0] / "MyNewFolder"
        res = file_security.safe_create_folder(folder, approved_roots=test_roots)
        assert res["success"] is True
        assert folder.is_dir()

    def test_create_folder_conflict(self, test_roots):
        folder = test_roots[0] / "ExistingFolder"
        folder.mkdir()
        res = file_security.safe_create_folder(folder, approved_roots=test_roots)
        assert res["success"] is False
        assert res.get("conflict") is True


# ══════════════════════════════════════════════════════════════════════
# 5. Approval & Execution Lifecycle
# ══════════════════════════════════════════════════════════════════════

class TestApprovalLifecycle:
    def test_execute_without_approval_rejected(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a file named script.py in Projects",
            approved_roots=test_roots,
        )
        # Attempt to execute while status is AWAITING_APPROVAL without approval
        ok, msg, _ = file_copilot.execute_file_task(
            task.task_id,
            approval_token="wrong_token",
            approved_roots=test_roots,
        )
        assert ok is False
        assert "invalid" in msg.lower() or "not approved" in msg.lower()

    def test_approval_and_execution_success(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a file named sample.txt in Projects",
            approved_roots=test_roots,
        )
        token = task.approval_token
        assert token is not None

        # Approve
        ok_app, _, task_app = file_copilot.approve_file_task(task.task_id, approved=True, approval_token=token)
        assert ok_app is True

        # Execute
        ok_exec, msg_exec, task_exec = file_copilot.execute_file_task(
            task.task_id,
            approval_token=token,
            approved_roots=test_roots,
        )
        assert ok_exec is True
        assert task_exec.status == FileTaskStatus.COMPLETED
        assert (test_roots[0] / "sample.txt").exists()

    def test_approval_consumed_cannot_be_reused(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a file named reuse_test.txt in Projects",
            approved_roots=test_roots,
        )
        token = task.approval_token

        file_copilot.approve_file_task(task.task_id, approved=True, approval_token=token)
        ok1, _, _ = file_copilot.execute_file_task(task.task_id, approval_token=token, approved_roots=test_roots)
        assert ok1 is True

        # Second execution attempt with same token fails
        ok2, _, _ = file_copilot.execute_file_task(task.task_id, approval_token=token, approved_roots=test_roots)
        assert ok2 is False

    def test_expired_approval_rejected(self, test_roots):
        from datetime import datetime, timedelta, timezone

        task = file_copilot.parse_file_request(
            "Create a file named expired.txt in Projects",
            approved_roots=test_roots,
        )
        # Manually backdate expiration
        task.expires_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        ok, msg, _ = file_copilot.approve_file_task(task.task_id, approved=True, approval_token=task.approval_token)
        assert ok is False
        assert "expired" in msg.lower()

    def test_rejection_prevents_execution(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a file named reject_me.txt in Projects",
            approved_roots=test_roots,
        )
        token = task.approval_token

        # Reject
        ok_rej, _, task_rej = file_copilot.approve_file_task(task.task_id, approved=False)
        assert ok_rej is True
        assert task_rej.status == FileTaskStatus.REJECTED

        # Execution attempt must fail
        ok_exec, _, _ = file_copilot.execute_file_task(task.task_id, approval_token=token, approved_roots=test_roots)
        assert ok_exec is False
        assert not (test_roots[0] / "reject_me.txt").exists()


# ══════════════════════════════════════════════════════════════════════
# 6. Project Templates
# ══════════════════════════════════════════════════════════════════════

class TestProjectTemplates:
    def test_python_starter_project(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a Python calculator project named CalcApp in Projects",
            approved_roots=test_roots,
        )
        assert task.operation == FileOperationType.CREATE_PROJECT
        assert task.template == ProjectTemplate.PYTHON_STARTER
        assert len(task.planned_files) == 4

        # Approve & execute
        file_copilot.approve_file_task(task.task_id, approved=True, approval_token=task.approval_token)
        ok, msg, updated = file_copilot.execute_file_task(
            task.task_id,
            approval_token=task.approval_token,
            approved_roots=test_roots,
        )
        assert ok is True
        assert updated.status == FileTaskStatus.COMPLETED

        proj_dir = test_roots[0] / "CalcApp"
        assert proj_dir.is_dir()
        assert (proj_dir / "main.py").exists()
        assert (proj_dir / "README.md").exists()
        assert (proj_dir / ".gitignore").exists()
        assert (proj_dir / "requirements.txt").exists()

    def test_html_website_project(self, test_roots):
        task = file_copilot.parse_file_request(
            "Create a website project named MySite in Projects",
            approved_roots=test_roots,
        )
        assert task.template == ProjectTemplate.HTML_WEBSITE

        file_copilot.approve_file_task(task.task_id, approved=True, approval_token=task.approval_token)
        ok, _, _ = file_copilot.execute_file_task(
            task.task_id,
            approval_token=task.approval_token,
            approved_roots=test_roots,
        )
        assert ok is True

        proj_dir = test_roots[0] / "MySite"
        assert (proj_dir / "index.html").exists()
        assert (proj_dir / "style.css").exists()
        assert (proj_dir / "script.js").exists()


# ══════════════════════════════════════════════════════════════════════
# 7. Safe Reading, Listing, and Searching
# ══════════════════════════════════════════════════════════════════════

class TestReadListSearch:
    def test_safe_read_text_file(self, test_roots):
        target = test_roots[0] / "readable.txt"
        target.write_text("Content of readable text file.", encoding="utf-8")

        res = file_security.safe_read_text_file(target, approved_roots=test_roots)
        assert res["success"] is True
        assert res["content"] == "Content of readable text file."
        assert res["size_bytes"] == len("Content of readable text file.")

    def test_read_file_exceeding_size_limit(self, test_roots):
        target = test_roots[0] / "large.txt"
        target.write_text("X" * 100, encoding="utf-8")

        res = file_security.safe_read_text_file(target, max_bytes=50, approved_roots=test_roots)
        assert res["success"] is False
        assert "safety limit" in res["error"].lower()

    def test_read_binary_file_rejected(self, test_roots):
        target = test_roots[0] / "binary.dat"
        target.write_bytes(b"\x00\xff\xfe\x01\x02\x80")

        res = file_security.safe_read_text_file(target, approved_roots=test_roots)
        assert res["success"] is False
        assert "binary" in res["error"].lower()

    def test_safe_list_dir(self, test_roots):
        (test_roots[0] / "alpha.txt").write_text("a")
        (test_roots[0] / "beta.txt").write_text("b")
        (test_roots[0] / ".hidden.txt").write_text("hidden")

        res = file_security.safe_list_dir(test_roots[0], approved_roots=test_roots)
        assert res["success"] is True
        names = [item["name"] for item in res["items"]]
        assert "alpha.txt" in names
        assert "beta.txt" in names
        assert ".hidden.txt" not in names  # Hidden excluded

    def test_safe_search_files(self, test_roots):
        sub = test_roots[0] / "subfolder"
        sub.mkdir()
        (test_roots[0] / "calculator.py").write_text("# root calc")
        (sub / "calc_helper.py").write_text("# sub calc")
        (sub / "notes.txt").write_text("notes")

        res = file_security.safe_search_files(
            test_roots[0],
            pattern="calc*",
            approved_roots=test_roots,
        )
        assert res["success"] is True
        matched_names = [m["name"] for m in res["matches"]]
        assert "calculator.py" in matched_names
        assert "calc_helper.py" in matched_names
        assert "notes.txt" not in matched_names


# ══════════════════════════════════════════════════════════════════════
# 8. API Integration Endpoints
# ══════════════════════════════════════════════════════════════════════

class TestFileAPIEndpoints:
    def test_api_roots_endpoint(self, client):
        resp = client.get("/api/v1/files/roots")
        assert resp.status_code == 200
        data = resp.json()
        assert "roots" in data
        assert isinstance(data["roots"], list)

    def test_api_create_clarify_approve_execute(self, client, test_roots):
        with patch("app.services.file_copilot.get_approved_roots", return_value=test_roots):
            # 1. Create task
            resp = client.post("/api/v1/files/task/create", json={
                "request": "Create a file for my math homework in Documents"
            })
            assert resp.status_code == 200
            task = resp.json()
            tid = task["task_id"]

            # Needs clarification for filename
            assert task["status"] in ("needs_clarification", "ready_for_review", "awaiting_approval")

            # 2. Clarify if needed
            if task["status"] == "needs_clarification":
                resp_clarify = client.post(f"/api/v1/files/task/{tid}/clarify", json={
                    "answers": {"filename": "math.py"}
                })
                assert resp_clarify.status_code == 200
                task = resp_clarify.json()["task"]

            assert task["status"] == "awaiting_approval"
            token = task["approval_token"]

            # 3. Approve
            resp_app = client.post(f"/api/v1/files/task/{tid}/approve", json={
                "approved": True,
                "approval_token": token,
            })
            assert resp_app.status_code == 200

            # 4. Execute
            with patch("app.services.file_security.get_approved_roots", return_value=test_roots):
                resp_exec = client.post(f"/api/v1/files/task/{tid}/execute", json={
                    "approved": True,
                    "approval_token": token,
                })
                assert resp_exec.status_code == 200
                exec_data = resp_exec.json()
                assert exec_data["success"] is True
                assert (test_roots[1] / "math.py").exists()

    def test_api_audit_log(self, client):
        resp = client.get("/api/v1/files/audit")
        assert resp.status_code == 200
        assert "entries" in resp.json()


# ══════════════════════════════════════════════════════════════════════
# 9. Regression Test Suite: Python Calculator Project Fix
# ══════════════════════════════════════════════════════════════════════

class TestCalculatorProjectRegression:
    PROMPT = (
        "Create a Python calculator project in my Projects folder. "
        "Include main.py, README.md, .gitignore, and requirements.txt. "
        "Show me the destination and preview every file before creating anything."
    )

    def test_exact_prompt_parsing_and_separation(self, test_roots):
        task = file_copilot.parse_file_request(self.PROMPT, approved_roots=test_roots)

        # 1. Verification of structural concept separation
        assert task.operation == FileOperationType.CREATE_PROJECT
        assert task.target_name == "calculator"
        assert task.template == ProjectTemplate.PYTHON_STARTER
        assert task.target_directory == "Projects"
        assert task.requested_filenames == ["main.py", "README.md", ".gitignore", "requirements.txt"]
        assert task.functional_description is not None
        assert task.functional_description != self.PROMPT

        # 2. Destination preview is available
        assert task.target_path is not None
        assert task.target_path.endswith("calculator")
        assert "Projects/calculator" in task.target_path

        # 3. File preview contains exactly the requested files
        planned_map = {pf.relative_path: pf for pf in task.planned_files}
        assert set(planned_map.keys()) == {"main.py", "README.md", ".gitignore", "requirements.txt"}

        # 4. Zero prompt leakage into any planned file
        for rel_path, pf in planned_map.items():
            assert self.PROMPT not in pf.content, f"Prompt text leaked into planned file {rel_path}"

    def test_calculator_main_py_semantics(self, test_roots):
        task = file_copilot.parse_file_request(self.PROMPT, approved_roots=test_roots)
        planned_map = {pf.relative_path: pf for pf in task.planned_files}
        main_content = planned_map["main.py"].content

        # No prohibited execution
        assert "eval(" not in main_content
        assert "exec(" not in main_content
        assert "__name__ == '__main__'" in main_content or '__name__ == "__main__"' in main_content

        # Interactive functions and error handling present
        assert "def add" in main_content
        assert "def subtract" in main_content
        assert "def multiply" in main_content
        assert "def divide" in main_content
        assert "ZeroDivisionError" in main_content
        assert "def run_interactive" in main_content or "def main" in main_content

        # Syntax validity via compile
        code_obj = compile(main_content, "main.py", "exec")
        assert code_obj is not None

        # Functional correctness via in-memory execution
        ns = {}
        exec(code_obj, ns)
        assert ns["add"](10, 5) == 15
        assert ns["subtract"](10, 5) == 5
        assert ns["multiply"](10, 5) == 50
        assert ns["divide"](10, 5) == 2.0
        with pytest.raises(ZeroDivisionError):
            ns["divide"](10, 0)

    def test_calculator_ancillary_files(self, test_roots):
        task = file_copilot.parse_file_request(self.PROMPT, approved_roots=test_roots)
        planned_map = {pf.relative_path: pf for pf in task.planned_files}

        # README.md
        readme = planned_map["README.md"].content
        assert self.PROMPT not in readme
        assert "# Calculator" in readme
        assert "## Features" in readme
        assert "## Requirements" in readme
        assert "## How to Run" in readme
        assert "python3 main.py" in readme
        assert "## Usage Example" in readme

        # .gitignore
        gitignore = planned_map[".gitignore"].content
        assert "__pycache__/" in gitignore
        assert ".venv/" in gitignore

        # requirements.txt
        reqs = planned_map["requirements.txt"].content
        assert reqs == ""  # Zero dummy/placeholder comments
        assert "# Add project dependencies here" not in reqs

    def test_full_approval_execution_and_deep_verification(self, test_roots):
        task = file_copilot.parse_file_request(self.PROMPT, approved_roots=test_roots)
        assert task.status == FileTaskStatus.AWAITING_APPROVAL
        token = task.approval_token
        assert token is not None

        # Approve task
        ok_app, _, task_app = file_copilot.approve_file_task(task.task_id, approved=True, approval_token=token)
        assert ok_app is True

        # Execute task
        ok_exec, msg_exec, task_exec = file_copilot.execute_file_task(
            task.task_id,
            approval_token=token,
            approved_roots=test_roots,
        )
        assert ok_exec is True
        assert task_exec.status == FileTaskStatus.COMPLETED

        # Verify disk artifacts
        proj_dir = test_roots[0] / "calculator"
        assert proj_dir.is_dir()
        assert (proj_dir / "main.py").exists()
        assert (proj_dir / "README.md").exists()
        assert (proj_dir / ".gitignore").exists()
        assert (proj_dir / "requirements.txt").exists()

        # Check deep verification metadata
        assert task_exec.verification_details is not None
        assert task_exec.verification_details["hashes_matched"] is True
        assert task_exec.verification_details["no_prompt_leakage"] is True
        assert task_exec.verification_details["template_validated"] == "python_starter (calculator)"
        assert len(task_exec.verification_details["files_verified"]) == 4

        # Verify disk file content matches planned files
        for pf in task.planned_files:
            disk_content = (proj_dir / pf.relative_path).read_text(encoding="utf-8")
            assert disk_content == pf.content
            assert self.PROMPT not in disk_content

    def test_repeat_request_triggers_conflict_prevention(self, test_roots):
        # First execution succeeds
        task1 = file_copilot.parse_file_request(self.PROMPT, approved_roots=test_roots)
        file_copilot.approve_file_task(task1.task_id, approved=True, approval_token=task1.approval_token)
        ok1, _, _ = file_copilot.execute_file_task(task1.task_id, approval_token=task1.approval_token, approved_roots=test_roots)
        assert ok1 is True

        # Second request attempts to create existing directory
        task2 = file_copilot.parse_file_request(self.PROMPT, approved_roots=test_roots)
        assert task2.conflict_detected is True
        assert "Target already exists" in task2.conflict_message
        assert task2.status == FileTaskStatus.READY_FOR_REVIEW
        assert task2.approval_token is None  # Blocked from approval


