"""
Developer Copilot service for TERMIQ.

Capabilities:
- Explain Python errors and tracebacks (beginner & advanced modes)
- Create Python virtual environments
- Run project test suites safely with strict execution bounds
- Inspect project Git status and recent commits
- Open projects in VS Code or system editor
"""

import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from app.models import (
    ExplainErrorResponse,
    GitStatusResponse,
    OpenEditorResponse,
    RunTestsResponse,
)
from app.services.file_security import get_approved_roots, validate_path

logger = logging.getLogger(__name__)

# Predefined expert knowledge base for common Python errors
ERROR_PATTERNS = {
    "IndexError": {
        "summary": "The code tried to access a list item at an index position that does not exist.",
        "causes": [
            "The list is shorter than expected or completely empty.",
            "Using 1-based numbering instead of 0-based indexing.",
            "A loop counter exceeded the length of the collection.",
        ],
        "fix": "Check the length of the list with len(my_list) before accessing it, or use safe iteration (for item in my_list:).",
        "example": "if index < len(my_list):\n    item = my_list[index]\nelse:\n    print('Index out of range')",
    },
    "KeyError": {
        "summary": "The code tried to look up a key that does not exist in the dictionary.",
        "causes": [
            "The requested key is missing or misspelled.",
            "The dictionary was not initialized with default keys.",
            "Expected API response format changed.",
        ],
        "fix": "Use the dictionary's .get() method to supply a default fallback value, or verify key existence with 'if key in my_dict:'.",
        "example": "value = my_dict.get('expected_key', default_value)",
    },
    "TypeError": {
        "summary": "An operation or function was applied to an object of inappropriate type.",
        "causes": [
            "Trying to concatenate a string and a number without explicit conversion.",
            "Passing the wrong number or type of arguments to a function.",
            "Attempting to call an object that is not a function.",
        ],
        "fix": "Convert types explicitly (e.g., str(number) or int(string)), or check function signature parameters.",
        "example": "message = 'Count: ' + str(total_items)",
    },
    "AttributeError": {
        "summary": "The code attempted to access an attribute or method that does not exist on this object.",
        "causes": [
            "The variable is None because a preceding function returned nothing.",
            "A typographical error in the method or property name.",
            "The object is of a different class than assumed.",
        ],
        "fix": "Check whether the object is None before accessing its attributes (if obj is not None:).",
        "example": "if user is not None:\n    print(user.name)",
    },
    "ModuleNotFoundError": {
        "summary": "Python could not find the requested library or module.",
        "causes": [
            "The package is not installed in the currently active Python environment.",
            "A typo in the import statement.",
            "The virtual environment is not activated.",
        ],
        "fix": "Activate your project virtual environment and install the required package using pip install <package_name>.",
        "example": "source .venv/bin/activate\npip install <missing_package>",
    },
    "ZeroDivisionError": {
        "summary": "A mathematical division or modulo operation attempted to divide by zero.",
        "causes": [
            "The divisor variable evaluated to 0.",
            "An unhandled edge case in calculations with empty datasets or zero counts.",
        ],
        "fix": "Guard against zero divisors before dividing (if divisor != 0:).",
        "example": "result = total / count if count > 0 else 0.0",
    },
    "FileNotFoundError": {
        "summary": "The specified file path could not be located on the filesystem.",
        "causes": [
            "The path is relative and the current working directory differs from expectations.",
            "A typo in the filename or file extension.",
            "The file was moved or deleted.",
        ],
        "fix": "Use pathlib.Path(__file__).parent to build paths relative to the script, or verify path existence with path.exists().",
        "example": "from pathlib import Path\nfile_path = Path(__file__).parent / 'data.txt'\nif file_path.exists():\n    content = file_path.read_text()",
    },
}


def explain_python_error(
    error_text: str,
    context_code: Optional[str] = None,
    mode: str = "beginner",
) -> ExplainErrorResponse:
    """
    Analyze a Python error or traceback and produce a structured, beginner-friendly explanation.
    """
    raw_error = error_text.strip()
    if not raw_error:
        return ExplainErrorResponse(
            error_type="Unknown",
            summary="No error text provided to analyze.",
            current_evidence="Empty input.",
            possible_causes=["Please provide a Python error message or traceback."],
            recommended_fix="Copy and paste the traceback from your terminal or IDE.",
            source="rules",
        )

    # Detect exception type
    matched_type = "Python Error"
    for err_name in ERROR_PATTERNS:
        if err_name in raw_error:
            matched_type = err_name
            break

    # Check for general exception pattern: E.g., ValueError: ...
    if matched_type == "Python Error":
        exc_match = re.search(r"([A-Za-z]+Error|[A-Za-z]+Exception):\s*(.*)", raw_error)
        if exc_match:
            matched_type = exc_match.group(1)

    # Try Gemini if API key is present
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    if api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=10000),
            )
            prompt = f"""You are an expert Python programming mentor.
Explain this Python error to a user ({mode} mode):
Error / Traceback:
{raw_error}

Context Code (if any):
{context_code or 'None'}

Return a concise JSON object with these exact keys:
- "error_type": string (e.g. {matched_type})
- "summary": string (1 clear sentence explaining what happened in plain English)
- "current_evidence": string (the specific line or expression that failed)
- "possible_causes": list of 2-3 short strings
- "recommended_fix": string (practical, concrete fix instructions)
- "code_example": string (clean corrected code snippet)
"""
            resp = client.models.generate_content(
                model=gemini_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2,
                    max_output_tokens=800,
                ),
            )
            if resp.text:
                import json
                data = json.loads(resp.text)
                return ExplainErrorResponse(
                    error_type=data.get("error_type", matched_type),
                    summary=data.get("summary", ""),
                    current_evidence=data.get("current_evidence", raw_error[:200]),
                    possible_causes=data.get("possible_causes", []),
                    recommended_fix=data.get("recommended_fix", ""),
                    code_example=data.get("code_example", None),
                    source="gemini_ai",
                )
        except Exception as exc:
            logger.warning("Gemini error explanation failed, using expert rules: %s", exc)

    # Fallback to expert knowledge base
    rule_data = ERROR_PATTERNS.get(matched_type, {
        "summary": f"Python encountered a runtime exception: {matched_type}.",
        "causes": [
            "A syntax mistake or unexpected variable state occurred.",
            "An unhandled edge case in program input.",
        ],
        "fix": "Inspect the line identified in the traceback, check variable values, and add defensive error handling.",
        "example": "try:\n    # code here\n    pass\nexcept Exception as err:\n    print(f'Caught error: {err}')",
    })

    # Extract failing line evidence from traceback
    evidence = raw_error
    line_match = re.search(r"File \".*?\", line (\d+)(?:, in .*)?\n\s*(.*)", raw_error)
    if line_match:
        evidence = f"Line {line_match.group(1)}: {line_match.group(2).strip()}"

    return ExplainErrorResponse(
        error_type=matched_type,
        summary=rule_data["summary"],
        current_evidence=evidence,
        possible_causes=rule_data["causes"],
        recommended_fix=rule_data["fix"],
        code_example=rule_data.get("example"),
        source="expert_rules",
    )


def create_virtualenv(
    directory: str | Path,
    venv_name: str = ".venv",
    approved_roots: Optional[list[Path]] = None,
) -> dict:
    """
    Create a Python virtual environment in an approved project directory.
    """
    valid_dir, err = validate_path(directory, must_exist=True, approved_roots=approved_roots)
    if err or valid_dir is None:
        return {"success": False, "error": err}

    if not valid_dir.is_dir():
        return {"success": False, "error": f"Path is not a directory: {valid_dir.name}"}

    target_venv = valid_dir / venv_name
    if target_venv.exists():
        return {
            "success": False,
            "error": f"Virtual environment already exists at '{target_venv.name}'.",
        }

    try:
        res = subprocess.run(
            [sys.executable, "-m", "venv", str(target_venv)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if res.returncode != 0:
            return {
                "success": False,
                "error": f"venv creation failed: {res.stderr.strip()}",
            }

        python_bin = target_venv / "bin" / "python3"
        return {
            "success": True,
            "venv_path": str(target_venv),
            "python_path": str(python_bin),
            "message": f"Created Python virtual environment at '{target_venv.name}'.",
        }
    except Exception as exc:
        return {"success": False, "error": f"Exception creating venv: {exc}"}


def run_project_tests(
    project_directory: str | Path,
    approved_roots: Optional[list[Path]] = None,
) -> RunTestsResponse:
    """
    Run pytest or unittest for a project directory within strict bounds.
    No shell=True, fixed timeout, output capped at 8KB.
    """
    valid_dir, err = validate_path(project_directory, must_exist=True, approved_roots=approved_roots)
    if err or valid_dir is None:
        return RunTestsResponse(
            success=False,
            passed=0,
            failed=0,
            errors=1,
            duration_seconds=0.0,
            output="",
            summary=f"Path validation error: {err}",
        )

    # Determine runner
    venv_pytest = valid_dir / ".venv" / "bin" / "pytest"
    venv_python = valid_dir / ".venv" / "bin" / "python"

    if venv_pytest.exists():
        cmd = [str(venv_pytest), "-v"]
    elif venv_python.exists():
        cmd = [str(venv_python), "-m", "unittest", "discover", "-s", "tests"]
    else:
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]

    start_time = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(valid_dir),
            capture_output=True,
            text=True,
            timeout=15,
        )
        duration = (datetime.now(timezone.utc) - start_time).total_seconds()
        output = (proc.stdout + "\n" + proc.stderr).strip()[:8192]

        passed = 0
        failed = 0
        errors = 0

        # Parse pytest output
        pytest_match = re.search(r"(\d+)\s+passed", output)
        if pytest_match:
            passed = int(pytest_match.group(1))
        fail_match = re.search(r"(\d+)\s+failed", output)
        if fail_match:
            failed = int(fail_match.group(1))

        # Parse unittest output
        if "Ran " in output:
            ran_match = re.search(r"Ran (\d+) test", output)
            total = int(ran_match.group(1)) if ran_match else 0
            if "OK" in output:
                passed = total
            elif "FAILED" in output:
                failures_match = re.search(r"failures=(\d+)", output)
                errors_match = re.search(r"errors=(\d+)", output)
                if failures_match:
                    failed = int(failures_match.group(1))
                if errors_match:
                    errors = int(errors_match.group(1))
                passed = max(0, total - failed - errors)

        success = proc.returncode == 0
        summary = f"Tests completed: {passed} passed, {failed} failed in {duration:.2f}s."
        if not success and passed == 0 and failed == 0:
            summary = "No tests ran or test runner returned non-zero code."

        return RunTestsResponse(
            success=success,
            passed=passed,
            failed=failed,
            errors=errors,
            duration_seconds=round(duration, 2),
            output=output,
            summary=summary,
        )
    except subprocess.TimeoutExpired:
        return RunTestsResponse(
            success=False,
            passed=0,
            failed=0,
            errors=1,
            duration_seconds=15.0,
            output="Execution timed out after 15 seconds.",
            summary="Test run timed out.",
        )
    except Exception as exc:
        return RunTestsResponse(
            success=False,
            passed=0,
            failed=0,
            errors=1,
            duration_seconds=0.0,
            output=str(exc),
            summary=f"Test runner error: {exc}",
        )


def get_git_status(
    project_directory: str | Path,
    approved_roots: Optional[list[Path]] = None,
) -> GitStatusResponse:
    """
    Inspect Git repository status and recent commit log safely.
    """
    valid_dir, err = validate_path(project_directory, must_exist=True, approved_roots=approved_roots)
    if err or valid_dir is None:
        return GitStatusResponse(
            is_git_repo=False,
            branch="",
            modified_files=[],
            untracked_files=[],
            recent_commits=[],
            clean=False,
        )

    git_dir = valid_dir / ".git"
    if not git_dir.exists():
        return GitStatusResponse(
            is_git_repo=False,
            branch="",
            modified_files=[],
            untracked_files=[],
            recent_commits=[],
            clean=False,
        )

    git_bin = shutil.which("git") or "/usr/bin/git"

    # Branch
    branch = ""
    try:
        branch_res = subprocess.run(
            [git_bin, "-C", str(valid_dir), "branch", "--show-current"],
            capture_output=True, text=True, timeout=5,
        )
        branch = branch_res.stdout.strip()
    except Exception:
        pass

    # Status
    modified = []
    untracked = []
    try:
        status_res = subprocess.run(
            [git_bin, "-C", str(valid_dir), "status", "--porcelain=v1"],
            capture_output=True, text=True, timeout=5,
        )
        for line in status_res.stdout.splitlines():
            code = line[:2]
            filename = line[3:].strip()
            if code.strip() == "??":
                untracked.append(filename)
            else:
                modified.append(filename)
    except Exception:
        pass

    # Recent commits
    recent_commits = []
    try:
        log_res = subprocess.run(
            [git_bin, "-C", str(valid_dir), "log", "-n", "5", "--oneline"],
            capture_output=True, text=True, timeout=5,
        )
        recent_commits = [c.strip() for c in log_res.stdout.splitlines() if c.strip()]
    except Exception:
        pass

    clean = len(modified) == 0 and len(untracked) == 0

    return GitStatusResponse(
        is_git_repo=True,
        branch=branch or "HEAD",
        modified_files=modified,
        untracked_files=untracked,
        recent_commits=recent_commits,
        clean=clean,
    )


def open_in_editor(
    target_path: str | Path,
    editor_preference: str = "code",
    approved_roots: Optional[list[Path]] = None,
) -> OpenEditorResponse:
    """
    Open a file or project folder in VS Code or an available system editor safely.
    """
    valid_path, err = validate_path(target_path, must_exist=True, approved_roots=approved_roots)
    if err or valid_path is None:
        return OpenEditorResponse(
            success=False,
            editor_used="",
            message=f"Path error: {err}",
        )

    candidates = [editor_preference, "code", "gnome-text-editor", "gedit", "xdg-open"]
    found_bin = None
    for cand in candidates:
        bin_path = shutil.which(cand)
        if bin_path:
            found_bin = bin_path
            break

    if not found_bin:
        return OpenEditorResponse(
            success=False,
            editor_used="",
            message="No supported editor (code, gnome-text-editor, gedit, xdg-open) was found on the system.",
        )

    try:
        subprocess.Popen([found_bin, str(valid_path)])
        return OpenEditorResponse(
            success=True,
            editor_used=Path(found_bin).name,
            message=f"Opened '{valid_path.name}' in {Path(found_bin).name}.",
        )
    except Exception as exc:
        return OpenEditorResponse(
            success=False,
            editor_used=Path(found_bin).name,
            message=f"Failed to launch editor: {exc}",
        )

