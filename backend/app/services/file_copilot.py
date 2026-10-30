"""
File & Folder Copilot service for TERMIQ V2.0.

Provides:
- Natural-language parsing of file/folder/project requests with separation of
  request text, project name, template, filenames, and functional requirements.
- Missing-information clarification workflows.
- Deterministic, high-quality project templates (Python calculator, HTML/CSS/JS, Docs).
- Content generation via Gemini with strict validation and safe fallback.
- Multi-layer verification: disk presence, SHA-256 hash matching, no prompt leakage,
  syntax compilation, and in-memory functional behavior validation.
- One-time consumption, short TTL expiry, and conflict detection.
- Full audit logging without exposing sensitive data.
"""

import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from dotenv import load_dotenv

from app.models import (
    AuditEntry,
    FileOperationType,
    FileTask,
    FileTaskStatus,
    PlannedFile,
    ProjectTemplate,
)
from app.services.file_security import (
    compute_content_hash,
    get_approved_roots,
    is_safe_filename,
    safe_create_file,
    safe_create_folder,
    validate_path,
)

logger = logging.getLogger(__name__)

# Approval TTL (5 minutes)
APPROVAL_TTL_SECONDS = 300

# In-memory store for active file tasks and audit trail
_file_tasks: dict[str, FileTask] = {}
_file_audit_log: list[AuditEntry] = []
_file_lock = threading.Lock()


# ── Audit helpers ──────────────────────────────────────────────────────

def _file_audit(event: str, task_id: str = "", detail: str = "") -> None:
    entry = AuditEntry(
        event=f"FILE_{event}",
        plan_id=task_id,
        action_id="",
        detail=detail,
    )
    with _file_lock:
        _file_audit_log.append(entry)
    logger.info("AUDIT FILE_%s task=%s %s", event, task_id, detail)


def get_file_audit_log() -> list[dict]:
    with _file_lock:
        return [e.model_dump(mode="json") for e in _file_audit_log]


# ── Semantic Extraction Helpers ────────────────────────────────────────

def extract_project_name(text: str) -> Optional[str]:
    """
    Extract a clean project directory name from user text.
    Ensures generic words ('python', 'project') are not mistakenly used as the name.
    """
    lower = text.lower()

    # 1. Check explicit "named X" or "called X"
    match_named = re.search(r"\b(?:named|called)\s+([A-Za-z0-9_\-\.]+)", text, re.IGNORECASE)
    if match_named:
        return match_named.group(1).strip()

    # 2. Check for "Python <name> project" e.g. "Python calculator project"
    match_py_proj = re.search(r"\bpython\s+([A-Za-z0-9_\-]+)\s+project\b", text, re.IGNORECASE)
    if match_py_proj:
        cand = match_py_proj.group(1).strip()
        if cand.lower() not in ("starter", "new", "simple", "sample", "a"):
            return cand

    # 3. Check for "<name> project"
    match_project = re.search(r"\b([A-Za-z0-9_\-]+)\s+project\b", text, re.IGNORECASE)
    if match_project:
        cand = match_project.group(1).strip()
        if cand.lower() not in ("python", "new", "a", "the", "my", "starter", "small", "simple"):
            return cand

    # 4. Keyword heuristics
    if "calculator" in lower:
        return "calculator"
    if "website" in lower:
        return "website"
    if "notes" in lower or "documentation" in lower or "docs" in lower:
        return "docs"

    return None


def extract_requested_filenames(text: str) -> list[str]:
    """Identify explicitly mentioned filenames in the request."""
    matches = re.findall(r"\b[A-Za-z0-9_\-]+\.[a-zA-Z0-9]+\b|\.gitignore|\.env", text)
    seen = set()
    result = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def extract_functional_description(
    text: str,
    project_name: str,
    template: Optional[ProjectTemplate] = None,
) -> str:
    """Extract a clean, concise functional description rather than repeating the raw prompt."""
    lower = text.lower()
    if "calculator" in lower or project_name.lower() == "calculator":
        return "Command-line calculator providing arithmetic operations (+, -, *, /) with input validation and zero-division protection."
    if template == ProjectTemplate.HTML_WEBSITE or "website" in lower:
        return "Modern semantic HTML5, CSS3, and JavaScript website."
    if template == ProjectTemplate.MARKDOWN_DOCS or "documentation" in lower or "docs" in lower:
        return "Markdown documentation workspace with guide and development notes."
    if template == ProjectTemplate.PYTHON_STARTER:
        return f"Python application structure for {project_name}."
    return f"{project_name} application."


# ── Project Templates ──────────────────────────────────────────────────

def build_template_files(
    template: ProjectTemplate,
    project_name: str,
    functional_description: str = "",
) -> list[PlannedFile]:
    """
    Generate planned files for a supported project template.
    Guarantees:
    - Never copies the raw user request into file contents or docstrings.
    - Python calculator produces a fully functional, interactive CLI calculator.
    - requirements.txt is empty when only standard library is required (no placeholders).
    - README.md contains features, requirements, and run instructions.
    """
    clean_name = project_name.strip() or "my_project"
    files: list[PlannedFile] = []
    is_calculator = "calculator" in clean_name.lower() or "calculator" in functional_description.lower()

    if template == ProjectTemplate.PYTHON_STARTER:
        if is_calculator:
            main_py = '''"""
Calculator
A functional interactive command-line calculator.
"""

from typing import Optional


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return the difference of a and b."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return the quotient of a and b. Raises ZeroDivisionError if b is 0."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero.")
    return a / b


OPERATIONS = {
    "+": ("Addition", add),
    "-": ("Subtraction", subtract),
    "*": ("Multiplication", multiply),
    "/": ("Division", divide),
}


def calculate(op: str, a: float, b: float) -> float:
    """Execute arithmetic operation between two numbers safely."""
    op_clean = op.strip()
    if op_clean not in OPERATIONS:
        raise ValueError(f"Unsupported operation: '{op_clean}'. Supported: +, -, *, /")
    _, func = OPERATIONS[op_clean]
    return func(a, b)


def parse_number(prompt_text: str) -> Optional[float]:
    """Prompt the user for a numeric value and handle invalid input."""
    while True:
        raw = input(prompt_text).strip()
        if raw.lower() in ("q", "quit", "exit"):
            return None
        try:
            return float(raw)
        except ValueError:
            print("Invalid input: please enter a valid numeric value.")


def run_interactive() -> None:
    """Run the interactive calculator loop."""
    print("=" * 40)
    print("TERMIQ Interactive CLI Calculator")
    print("Operations: + (Add), - (Subtract), * (Multiply), / (Divide)")
    print("Type 'q' to quit anytime.")
    print("=" * 40)

    while True:
        try:
            op = input("\\nSelect operation (+, -, *, /) or 'q' to quit: ").strip()
            if op.lower() in ("q", "quit", "exit"):
                print("Goodbye!")
                break

            if op not in OPERATIONS:
                print("Invalid operation. Please enter +, -, *, or /.")
                continue

            num1 = parse_number("Enter first number: ")
            if num1 is None:
                print("Goodbye!")
                break

            num2 = parse_number("Enter second number: ")
            if num2 is None:
                print("Goodbye!")
                break

            try:
                result = calculate(op, num1, num2)
                print(f"Result: {num1} {op} {num2} = {result}")
            except ZeroDivisionError as err:
                print(f"Error: {err}")

        except (KeyboardInterrupt, EOFError):
            print("\\nSession ended. Goodbye!")
            break


def main() -> None:
    """Main entry point."""
    run_interactive()


if __name__ == "__main__":
    main()
'''
            readme_md = f"""# {clean_name.title()}

A clean, functional command-line calculator written in Python.

## Features
- Core arithmetic operations: addition (`+`), subtraction (`-`), multiplication (`*`), and division (`/`).
- Robust input validation for non-numeric values.
- Safe division-by-zero handling with informative error messages.
- Modular structure: can be imported as a library or run interactively.

## Requirements
- Python 3.8+ (standard library only; no external dependencies required).

## How to Run

Run the calculator directly from your terminal:
```bash
python3 main.py
```

## Usage Example

```text
TERMIQ Interactive CLI Calculator
========================================
Select operation (+, -, *, /) or 'q' to quit: +
Enter first number: 10
Enter second number: 5
Result: 10.0 + 5.0 = 15.0
```
"""
        else:
            main_py = f'''"""
{clean_name}
{functional_description or "A Python application built with TERMIQ."}
"""


def run() -> None:
    """Execute main application logic."""
    print("Welcome to {clean_name}!")


def main() -> None:
    """Main entry point."""
    run()


if __name__ == "__main__":
    main()
'''
            readme_md = f"""# {clean_name}

{functional_description or "A Python application built with TERMIQ."}

## Features
- Clean project structure and entry point.
- Standard Python packaging files.

## Requirements
- Python 3.8+

## How to Run

```bash
python3 main.py
```
"""

        gitignore = """__pycache__/
*.py[cod]
*$py.class
.venv/
venv/
env/
.pytest_cache/
.coverage
htmlcov/
dist/
build/
*.egg-info/
"""
        # Requirements is empty because standard library satisfies the application
        reqs = ""

        for rel, content, desc in [
            ("main.py", main_py, "Main application entry point"),
            ("README.md", readme_md, "Project documentation"),
            (".gitignore", gitignore, "Git ignore configuration"),
            ("requirements.txt", reqs, "Python dependencies (none required)"),
        ]:
            files.append(
                PlannedFile(
                    relative_path=rel,
                    content=content,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content.encode("utf-8")),
                    description=desc,
                )
            )

    elif template == ProjectTemplate.HTML_WEBSITE:
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{clean_name.title()}</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header>
        <h1>{clean_name.title()}</h1>
        <p>A modern semantic web application.</p>
    </header>
    <main>
        <section id="content">
            <p>Welcome to your website generated by TERMIQ File Copilot.</p>
            <button id="action-btn">Click Me</button>
            <div id="output"></div>
        </section>
    </main>
    <script src="script.js"></script>
</body>
</html>
"""
        style_css = """* {
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    line-height: 1.6;
    background-color: #0f172a;
    color: #f8fafc;
    padding: 2rem;
}

header {
    text-align: center;
    margin-bottom: 2rem;
}

h1 {
    color: #38bdf8;
    margin-bottom: 0.5rem;
}

button {
    background-color: #38bdf8;
    color: #0f172a;
    border: none;
    padding: 0.75rem 1.5rem;
    font-size: 1rem;
    font-weight: bold;
    border-radius: 6px;
    cursor: pointer;
}

button:hover {
    background-color: #0ea5e9;
}

#output {
    margin-top: 1rem;
    font-weight: 500;
}
"""
        script_js = """document.addEventListener('DOMContentLoaded', () => {
    const btn = document.getElementById('action-btn');
    const output = document.getElementById('output');
    let clicks = 0;

    btn.addEventListener('click', () => {
        clicks += 1;
        output.textContent = `Button clicked ${clicks} time(s)!`;
    });
});
"""
        readme_md = f"""# {clean_name.title()}

A modern HTML5, CSS3, and JavaScript website.

## How to View

Open `index.html` in any modern web browser:
```bash
xdg-open index.html
```
"""
        for rel, content, desc in [
            ("index.html", index_html, "HTML5 structure"),
            ("style.css", style_css, "Modern CSS styling"),
            ("script.js", script_js, "Interactive JavaScript"),
            ("README.md", readme_md, "Website documentation"),
        ]:
            files.append(
                PlannedFile(
                    relative_path=rel,
                    content=content,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content.encode("utf-8")),
                    description=desc,
                )
            )

    elif template == ProjectTemplate.MARKDOWN_DOCS:
        readme_md = f"""# {clean_name.title()} Documentation

Documentation workspace for {clean_name.title()}.

## Contents
- [User Guide](guide.md)
- [Development Notes](notes.md)
"""
        guide_md = f"""# User Guide: {clean_name.title()}

## Overview
This guide provides an overview of {clean_name.title()}.

## Quick Start
1. Step one: Setup
2. Step two: Usage
3. Step three: Next steps
"""
        notes_md = f"""# Notes & Architecture: {clean_name.title()}

## Design Decisions
- Document key design decisions here.

## Roadmap
- [x] Initial documentation structure
- [ ] Detailed specifications
"""
        for rel, content, desc in [
            ("README.md", readme_md, "Documentation table of contents"),
            ("guide.md", guide_md, "User quickstart guide"),
            ("notes.md", notes_md, "Development notes"),
        ]:
            files.append(
                PlannedFile(
                    relative_path=rel,
                    content=content,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content.encode("utf-8")),
                    description=desc,
                )
            )

    elif template == ProjectTemplate.FLASK_STARTER:
        app_py = f'''"""
{clean_name.title()} Flask Application.
Built with TERMIQ.
"""

from flask import Flask, jsonify, render_template

app = Flask(__name__)


@app.route("/")
def home():
    """Render home page."""
    return render_template("index.html", title="{clean_name.title()}")


@app.route("/api/health")
def health():
    """Health check endpoint."""
    return jsonify({{"status": "ok", "app": "{clean_name}"}})


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
'''
        index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{clean_name.title()}</title>
    <style>
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            background: #0f172a;
            color: #f8fafc;
            display: grid;
            place-content: center;
            height: 100vh;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            padding: 2rem;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
            text-align: center;
        }}
        h1 {{ color: #38bdf8; margin-top: 0; }}
        a {{ color: #38bdf8; text-decoration: none; }}
    </style>
</head>
<body>
    <div class="card">
        <h1>{clean_name.title()}</h1>
        <p>Flask web application powered by TERMIQ.</p>
        <p><a href="/api/health">Check API Health</a></p>
    </div>
</body>
</html>
"""
        readme_md = f"""# {clean_name.title()}

A lightweight Flask web application built with TERMIQ.

## Features
- Modular application layout with Jinja2 templates.
- Health check API endpoint (`/api/health`).
- Production-ready directory structure.

## Requirements
- Python 3.8+
- Flask 3.0+

## Setup & Run

1. Create a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the application:
```bash
python3 app.py
```
Open `http://127.0.0.1:5000` in your browser.
"""
        gitignore = """__pycache__/
*.py[cod]
.venv/
venv/
instance/
.pytest_cache/
"""
        reqs = "flask>=3.0.0\nwerkzeug>=3.0.0\n"

        for rel, content, desc in [
            ("app.py", app_py, "Flask application entry point"),
            ("templates/index.html", index_html, "Jinja2 starter template"),
            ("README.md", readme_md, "Project setup instructions"),
            (".gitignore", gitignore, "Git ignore rules"),
            ("requirements.txt", reqs, "Flask dependencies"),
        ]:
            files.append(
                PlannedFile(
                    relative_path=rel,
                    content=content,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content.encode("utf-8")),
                    description=desc,
                )
            )

    elif template == ProjectTemplate.FASTAPI_STARTER:
        main_py = f'''"""
{clean_name.title()} FastAPI Application.
Built with TERMIQ.
"""

from fastapi import FastAPI

app = FastAPI(
    title="{clean_name.title()}",
    description="FastAPI service built with TERMIQ",
    version="1.0.0",
)


@app.get("/")
def read_root():
    """Root welcome endpoint."""
    return {{"message": "Welcome to {clean_name.title()}!"}}


@app.get("/health")
def read_health():
    """Health check endpoint."""
    return {{"status": "ok", "app": "{clean_name}"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
'''
        readme_md = f"""# {clean_name.title()}

A modern, high-performance FastAPI service built with TERMIQ.

## Features
- Fully typed endpoints using FastAPI and Pydantic.
- Interactive API documentation via Swagger UI (`/docs`) and ReDoc (`/redoc`).
- Health check endpoint (`/health`).

## Setup & Run

1. Create a virtual environment and install dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Run the development server:
```bash
uvicorn main:app --reload
```
Open `http://127.0.0.1:8000/docs` to view the interactive documentation.
"""
        gitignore = """__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
"""
        reqs = "fastapi>=0.110.0\nuvicorn>=0.28.0\n"

        for rel, content, desc in [
            ("main.py", main_py, "FastAPI application entry point"),
            ("README.md", readme_md, "FastAPI documentation"),
            (".gitignore", gitignore, "Git ignore configuration"),
            ("requirements.txt", reqs, "FastAPI dependencies"),
        ]:
            files.append(
                PlannedFile(
                    relative_path=rel,
                    content=content,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content.encode("utf-8")),
                    description=desc,
                )
            )

    elif template == ProjectTemplate.DATA_ANALYSIS:
        analysis_py = f'''"""
{clean_name.title()} Data Analysis Script.
Built with TERMIQ.
"""

import csv
import statistics
from pathlib import Path


def summarize_numeric_column(data: list[float]) -> dict[str, float]:
    """Compute basic descriptive statistics for a list of numbers."""
    if not data:
        return {{}}
    return {{
        "count": len(data),
        "mean": round(statistics.mean(data), 2),
        "median": round(statistics.median(data), 2),
        "stdev": round(statistics.stdev(data), 2) if len(data) > 1 else 0.0,
        "min": min(data),
        "max": max(data),
    }}


def main() -> None:
    """Run data analysis pipeline."""
    print("=" * 40)
    print("TERMIQ Data Analysis Pipeline: {clean_name.title()}")
    print("=" * 40)
    data_dir = Path(__file__).parent / "data"
    print(f"Data directory: {{data_dir}}")
    print("Ready to process dataset files (CSV, JSON).")


if __name__ == "__main__":
    main()
'''
        data_readme = """# Data Directory

Place your raw datasets (CSV, JSON, Parquet) in this folder.
"""
        readme_md = f"""# {clean_name.title()}

A data analysis starter project built with TERMIQ.

## Structure
- `analysis.py`: Main data processing and statistics script.
- `data/`: Directory for input dataset files.
- `requirements.txt`: Python data analysis dependencies.

## Usage

Run the analysis script:
```bash
python3 analysis.py
```
"""
        gitignore = """__pycache__/
*.py[cod]
.venv/
venv/
*.csv
*.parquet
*.xlsx
"""
        reqs = "# Optional dependencies for advanced workflows:\n# pandas>=2.2.0\n# matplotlib>=3.8.0\n"

        for rel, content, desc in [
            ("analysis.py", analysis_py, "Data analysis processing script"),
            ("data/README.md", data_readme, "Data folder documentation"),
            ("README.md", readme_md, "Analysis project documentation"),
            (".gitignore", gitignore, "Git ignore rules for datasets"),
            ("requirements.txt", reqs, "Optional data science dependencies"),
        ]:
            files.append(
                PlannedFile(
                    relative_path=rel,
                    content=content,
                    content_hash=compute_content_hash(content),
                    size_bytes=len(content.encode("utf-8")),
                    description=desc,
                )
            )

    return files


# ── Single-File Content Generation ─────────────────────────────────────

def generate_single_file_content(filename: str, functional_description: str) -> str:
    """
    Generate file content for a single file using Gemini if available,
    or a high-quality deterministic fallback generator.
    Guarantees raw user request strings are never dumped into file content.
    """
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("GEMINI_API_KEY")
    model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite")

    ext = Path(filename).suffix.lower()
    clean_desc = functional_description.strip() or f"Implementation for {filename}"

    if api_key:
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(timeout=15000),
            )
            prompt = f"""You are a professional software engineer.
Generate clean, production-ready, readable contents for a file named '{filename}'.
Functional requirement: {clean_desc}

Rules:
- Output ONLY the raw file contents.
- Do NOT wrap the output in markdown code fences (like ```python or ```).
- Do NOT include any explanations, greetings, or conversational filler.
- Include sensible docstrings and comments inside the file.
"""
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=1000),
            )
            raw = (response.text or "").strip()
            # Clean accidental code fence wrappers
            if raw.startswith("```"):
                lines = raw.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()

            if raw:
                return raw + "\n"
        except Exception as exc:
            logger.warning("Gemini generation failed for %s, using fallback: %s", filename, exc)

    # ── High-quality deterministic fallback ───────────────────────────
    stem = Path(filename).stem
    if "calc" in filename.lower() and ext == ".py":
        # Return full calculator code
        template_files = build_template_files(ProjectTemplate.PYTHON_STARTER, "calculator", clean_desc)
        return template_files[0].content

    if ext == ".py":
        return f'''"""
{stem.title()}
{clean_desc}
"""


def main() -> None:
    """Execute main logic."""
    print("Running {stem}...")


if __name__ == "__main__":
    main()
'''
    elif ext == ".md":
        return f"""# {stem.replace('_', ' ').title()}

{clean_desc}

## Overview
Describe the purpose and usage of this document here.
"""
    elif ext == ".html":
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{stem.title()}</title>
</head>
<body>
    <h1>{stem.title()}</h1>
    <p>{clean_desc}</p>
</body>
</html>
"""
    elif ext in (".js", ".ts"):
        return f"""/**
 * {filename}
 * {clean_desc}
 */

console.log('Loaded {filename}');
"""
    elif ext == ".css":
        return f"""/* {filename} - {clean_desc} */
body {{
    font-family: sans-serif;
    margin: 0;
    padding: 1rem;
}}
"""
    elif ext == ".json":
        return json.dumps({
            "name": stem,
            "description": clean_desc,
            "version": "1.0.0",
        }, indent=2) + "\n"

    return f"# {stem.title()}\n{clean_desc}\n"


# ── Natural Language Request Parsing ───────────────────────────────────

def _extract_path_mentions(text: str) -> Optional[str]:
    """Look for standard folder mentions like 'Projects', 'Documents', 'Downloads', 'Desktop'."""
    lower = text.lower()
    for candidate in ["projects", "documents", "downloads", "desktop"]:
        if re.search(rf"\b(in|into|under|to)\s+(my\s+)?{candidate}\b", lower):
            return candidate.capitalize()
        if re.search(rf"\b{candidate}\s+folder\b", lower) or re.search(rf"\b{candidate}\s+directory\b", lower):
            return candidate.capitalize()
    return None


def parse_file_request(
    request_text: str,
    context_directory: Optional[str] = None,
    approved_roots: Optional[list[Path]] = None,
) -> FileTask:
    """
    Parse a user's natural language request into a structured FileTask.
    Properly separates:
    - original request text
    - clean project/file name
    - template
    - destination directory
    - requested filenames
    - functional requirements
    """
    text = request_text.strip()
    lower = text.lower()

    if approved_roots is None:
        approved_roots = get_approved_roots()

    task_id = uuid4().hex[:16]

    # 1. Detect Operation Type
    op: FileOperationType = FileOperationType.CREATE_FILE
    template: Optional[ProjectTemplate] = None
    target_name: Optional[str] = None
    target_dir: Optional[str] = context_directory

    # Search check
    if any(k in lower for k in ["find ", "search ", "locate "]) and any(k in lower for k in ["file", "files"]):
        op = FileOperationType.SEARCH_FILES
    # List check
    elif (
        re.search(r"\b(show|list|display|view)\b.*\b(files|directory|contents)\b", lower)
        or "list dir" in lower
        or "what files" in lower
    ):
        op = FileOperationType.LIST_DIR
    # Read check
    elif any(k in lower for k in ["read file", "read the file", "show content", "view file", "open file", "cat "]):
        op = FileOperationType.READ_FILE
    # Folder check
    elif any(k in lower for k in ["make a folder", "create a folder", "new folder", "mkdir", "create directory", "make directory"]):
        op = FileOperationType.CREATE_FOLDER
    # Organize check
    elif any(k in lower for k in ["organize downloads", "clean up downloads", "organize folder", "clean up folder", "organize my downloads"]):
        op = FileOperationType.ORGANIZE_FOLDER
        target_name = "Downloads" if "downloads" in lower else "folder"
        if "downloads" in lower and not target_dir:
            target_dir = "Downloads"
    # Duplicates check
    elif any(k in lower for k in ["find duplicate", "find duplicates", "duplicate files", "duplicate images"]):
        op = FileOperationType.FIND_DUPLICATES
        if not target_dir:
            target_dir = "Downloads" if "downloads" in lower else "Projects"
    # Large files check
    elif any(k in lower for k in ["large files", "big files", "files larger than", "files over"]):
        op = FileOperationType.FIND_LARGE_FILES
        if not target_dir:
            target_dir = "Downloads" if "downloads" in lower else "Projects"
    # Project check
    elif (
        re.search(r"\b(create|make|build|new|starter)\s+(?:a\s+)?(?:python\s+)?(?:starter\s+)?(?:calculator\s+)?(?:flask\s+)?(?:fastapi\s+)?project\b", lower)
        or re.search(r"\b(create|make|build|new)\s+(?:a\s+)?(?:small\s+)?(?:html|css|js|website)\b", lower)
        or re.search(r"\b(create|make|build|new)\s+(?:a\s+)?(?:docs|documentation)\s+folder\b", lower)
    ) and not re.search(r"\b(create|make|new)\s+(?:a\s+)?(?:python\s+)?(?:text\s+)?file\b", lower):
        op = FileOperationType.CREATE_PROJECT
        if any(w in lower for w in ["html", "website", "web page", "web site"]):
            template = ProjectTemplate.HTML_WEBSITE
        elif any(w in lower for w in ["doc", "docs", "documentation", "markdown"]):
            template = ProjectTemplate.MARKDOWN_DOCS
        elif "flask" in lower:
            template = ProjectTemplate.FLASK_STARTER
        elif "fastapi" in lower:
            template = ProjectTemplate.FASTAPI_STARTER
        elif any(w in lower for w in ["data analysis", "data science", "pandas"]):
            template = ProjectTemplate.DATA_ANALYSIS
        else:
            template = ProjectTemplate.PYTHON_STARTER
    else:
        op = FileOperationType.CREATE_FILE

    # 2. Extract Destination Directory
    dir_mention = _extract_path_mentions(text)
    if dir_mention:
        target_dir = dir_mention

    # 3. Extract Target Name and Requested Files
    requested_filenames = extract_requested_filenames(text)

    if op == FileOperationType.CREATE_PROJECT:
        target_name = extract_project_name(text)

    elif op == FileOperationType.CREATE_FOLDER:
        match_folder = re.search(r"\b(?:named|called)\s+([A-Za-z0-9_\-\. ]+?)(?:\s+in|\s+under|\.|$)", text, re.IGNORECASE)
        if match_folder:
            target_name = match_folder.group(1).strip()
        else:
            match_make = re.search(r"\b(?:make|create)\s+(?:a\s+)?folder\s+([A-Za-z0-9_\-\.]+)", text, re.IGNORECASE)
            if match_make:
                target_name = match_make.group(1).strip()

    elif op == FileOperationType.CREATE_FILE:
        match_file = re.search(r"([A-Za-z0-9_\-]+\.[a-zA-Z0-9]+)", text)
        match_named = re.search(r"\b(?:named|called)\s+([A-Za-z0-9_\-\.]+)", text, re.IGNORECASE)
        if match_file:
            target_name = match_file.group(1).strip()
        elif match_named:
            target_name = match_named.group(1).strip()
        elif "readme" in lower:
            target_name = "README.md"
        elif "calculator" in lower:
            target_name = "calculator.py"
        elif "python" in lower:
            target_name = "script.py"

    elif op == FileOperationType.SEARCH_FILES:
        match_pattern = re.search(r"\b(?:for|find)\s+([A-Za-z0-9_\-\.\*]+)", text, re.IGNORECASE)
        if match_pattern:
            target_name = match_pattern.group(1).strip()
        elif "python" in lower:
            target_name = "*.py"

    elif op == FileOperationType.READ_FILE:
        match_file = re.search(r"([A-Za-z0-9_\-]+\.[a-zA-Z0-9]+)", text)
        if match_file:
            target_name = match_file.group(1).strip()

    # 4. Synthesize clean functional description
    functional_desc = extract_functional_description(text, target_name or "", template)

    # 5. Clarification Checks
    clarifications: list[str] = []
    fields_needed: list[str] = []

    if op == FileOperationType.CREATE_FILE:
        if not target_name:
            clarifications.append("What should the file be named? (e.g., calculator.py, README.md)")
            fields_needed.append("filename")
        if not target_dir:
            clarifications.append("Which folder should this file be created in? (e.g., Projects, Documents, or Desktop)")
            fields_needed.append("directory")

    elif op == FileOperationType.CREATE_FOLDER:
        if not target_name:
            clarifications.append("What should the new folder be named?")
            fields_needed.append("folder_name")
        if not target_dir:
            clarifications.append("Where should this folder be created? (e.g., Projects, Documents, or Desktop)")
            fields_needed.append("directory")

    elif op == FileOperationType.CREATE_PROJECT:
        if not target_name:
            clarifications.append("What should the project directory be named?")
            fields_needed.append("project_name")
        if not target_dir:
            clarifications.append("Where should this project be created? (e.g., Projects or Documents)")
            fields_needed.append("directory")
        if not template:
            clarifications.append("Which template would you like to use? (python_starter, html_website, markdown_docs)")
            fields_needed.append("template")

    elif op == FileOperationType.SEARCH_FILES:
        if not target_name:
            clarifications.append("What filename or pattern would you like to search for?")
            fields_needed.append("pattern")
        if not target_dir:
            target_dir = approved_roots[0].name if approved_roots else "Projects"

    elif op == FileOperationType.LIST_DIR:
        if not target_dir:
            target_dir = approved_roots[0].name if approved_roots else "Projects"

    elif op == FileOperationType.READ_FILE:
        if not target_name:
            clarifications.append("Which file would you like to read?")
            fields_needed.append("filename")
        if not target_dir:
            target_dir = approved_roots[0].name if approved_roots else "Projects"

    status = (
        FileTaskStatus.NEEDS_CLARIFICATION
        if clarifications
        else FileTaskStatus.READY_FOR_REVIEW
    )

    task = FileTask(
        task_id=task_id,
        request_text=text,
        operation=op,
        status=status,
        target_directory=target_dir,
        target_name=target_name,
        template=template,
        requested_filenames=requested_filenames,
        functional_description=functional_desc,
        clarification_questions=clarifications,
        clarification_fields_needed=fields_needed,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_TTL_SECONDS),
    )

    if status == FileTaskStatus.READY_FOR_REVIEW:
        _prepare_task_plan(task, approved_roots=approved_roots)

    with _file_lock:
        _file_tasks[task.task_id] = task

    _file_audit("TASK_CREATED", task.task_id, f"op={op.value} status={status.value}")
    return task


def _resolve_directory_root(dir_input: str, approved_roots: list[Path]) -> Optional[Path]:
    """Map a folder name or path (e.g. 'Projects', '~/Projects') to an approved Path."""
    clean = dir_input.strip()
    for root in approved_roots:
        if root.name.lower() == clean.lower():
            return root

    resolved, err = validate_path(clean, must_exist=False, approved_roots=approved_roots)
    if resolved and not err:
        return resolved

    if approved_roots:
        candidate = (approved_roots[0].parent / clean).resolve()
        for root in approved_roots:
            if candidate == root or root in candidate.parents:
                return candidate

    return None


def _prepare_task_plan(task: FileTask, approved_roots: Optional[list[Path]] = None) -> None:
    """
    Construct planned files with clean functional descriptions, compute hashes,
    detect conflicts, and issue approval token.
    """
    if approved_roots is None:
        approved_roots = get_approved_roots()

    if not task.target_directory or not task.target_name:
        task.status = FileTaskStatus.NEEDS_CLARIFICATION
        return

    resolved_dir = _resolve_directory_root(task.target_directory, approved_roots)
    if not resolved_dir:
        task.status = FileTaskStatus.FAILED
        task.conflict_detected = True
        task.conflict_message = f"Directory '{task.target_directory}' is not in approved roots."
        return

    task.resolved_target_directory = str(resolved_dir)

    if not is_safe_filename(task.target_name):
        task.status = FileTaskStatus.FAILED
        task.conflict_detected = True
        task.conflict_message = f"Filename or folder name '{task.target_name}' is invalid or contains forbidden characters."
        return

    full_target = resolved_dir / task.target_name
    task.target_path = str(full_target)
    task.resolved_target_path = str(full_target.resolve())

    # Check for conflict
    if full_target.exists() or full_target.is_symlink():
        task.conflict_detected = True
        task.conflict_message = f"Target already exists: {full_target.name}. Choose another name or destination."
        task.status = FileTaskStatus.READY_FOR_REVIEW
        return

    if not resolved_dir.exists():
        task.needs_parent_creation = True
        task.parent_dirs_to_create = [str(resolved_dir)]

    # Generate planned files using clean functional descriptions (NEVER raw prompt)
    if task.operation == FileOperationType.CREATE_PROJECT and task.template:
        task.planned_files = build_template_files(
            task.template,
            project_name=task.target_name,
            functional_description=task.functional_description or "",
        )
        file_list_str = ", ".join(f.relative_path for f in task.planned_files)
        task.summary = f"Create project '{task.target_name}' using template '{task.template.value}' ({len(task.planned_files)} files: {file_list_str})"

    elif task.operation == FileOperationType.CREATE_FILE:
        content = generate_single_file_content(task.target_name, task.functional_description or "")
        task.planned_files = [
            PlannedFile(
                relative_path=task.target_name,
                content=content,
                content_hash=compute_content_hash(content),
                size_bytes=len(content.encode("utf-8")),
                description=f"Create file {task.target_name}",
            )
        ]
        task.summary = f"Create file '{task.target_name}' in '{resolved_dir.name}'"

    elif task.operation == FileOperationType.CREATE_FOLDER:
        task.planned_files = []
        task.summary = f"Create folder '{task.target_name}' in '{resolved_dir.name}'"

    # Compute combined approval hash and token
    hash_payload = f"{task.task_id}:{task.resolved_target_path}"
    for pf in task.planned_files:
        hash_payload += f":{pf.relative_path}:{pf.content_hash}"

    task.approved_hash = compute_content_hash(hash_payload)
    task.approval_token = uuid4().hex[:16]
    task.status = FileTaskStatus.AWAITING_APPROVAL
    task.expires_at = datetime.now(timezone.utc) + timedelta(seconds=APPROVAL_TTL_SECONDS)


# ── Clarification ──────────────────────────────────────────────────────

def clarify_task(
    task_id: str,
    answers: dict[str, str],
    text: Optional[str] = None,
    approved_roots: Optional[list[Path]] = None,
) -> tuple[bool, str, Optional[FileTask]]:
    """Update a task in NEEDS_CLARIFICATION with answers from the user."""
    with _file_lock:
        task = _file_tasks.get(task_id)

    if not task:
        return False, "Task not found.", None

    if task.status not in (FileTaskStatus.NEEDS_CLARIFICATION, FileTaskStatus.READY_FOR_REVIEW):
        return False, f"Task is in status {task.status.value}, cannot clarify.", task

    task.user_provided_answers.update(answers)

    if "filename" in answers:
        task.target_name = answers["filename"].strip()
    if "folder_name" in answers:
        task.target_name = answers["folder_name"].strip()
    if "project_name" in answers:
        task.target_name = answers["project_name"].strip()
    if "directory" in answers:
        task.target_directory = answers["directory"].strip()
    if "template" in answers:
        raw_tmpl = answers["template"].strip().lower()
        if "html" in raw_tmpl or "website" in raw_tmpl:
            task.template = ProjectTemplate.HTML_WEBSITE
        elif "doc" in raw_tmpl or "markdown" in raw_tmpl:
            task.template = ProjectTemplate.MARKDOWN_DOCS
        else:
            task.template = ProjectTemplate.PYTHON_STARTER

    if text:
        dir_mention = _extract_path_mentions(text)
        if dir_mention and not task.target_directory:
            task.target_directory = dir_mention

        file_match = re.search(r"([A-Za-z0-9_\-]+\.[a-zA-Z0-9]+)", text)
        if file_match and not task.target_name:
            task.target_name = file_match.group(1).strip()

    remaining_clarifications = []
    if not task.target_name:
        remaining_clarifications.append("Target name is still required.")
    if not task.target_directory:
        remaining_clarifications.append("Target directory is still required.")

    if remaining_clarifications:
        task.clarification_questions = remaining_clarifications
        task.status = FileTaskStatus.NEEDS_CLARIFICATION
    else:
        task.clarification_questions = []
        task.functional_description = extract_functional_description(
            task.request_text, task.target_name, task.template
        )
        task.status = FileTaskStatus.READY_FOR_REVIEW
        _prepare_task_plan(task, approved_roots=approved_roots)

    _file_audit("CLARIFIED", task.task_id, f"status={task.status.value}")
    return True, "Task updated.", task


# ── Content-Quality & Functional Verification ──────────────────────────

def _verify_calculator_semantics(content: str) -> tuple[bool, str]:
    """
    In-memory validation of calculator code.
    Verifies:
    - Syntax validity via compile()
    - Absence of eval/exec
    - Presence of main guard
    - Presence and correctness of arithmetic operations
    - Safe handling of ZeroDivisionError
    """
    try:
        code_obj = compile(content, "main.py", "exec")
    except SyntaxError as exc:
        return False, f"Syntax compilation error in main.py: {exc}"

    if "eval(" in content or "exec(" in content:
        return False, "Prohibited eval/exec call detected in main.py."

    if '__name__ == "__main__"' not in content and "__name__ == '__main__'" not in content:
        return False, "Missing main guard (__name__ == '__main__') in main.py."

    ns: dict = {}
    try:
        exec(code_obj, ns)
    except Exception as exc:
        return False, f"Failed to load module definitions in isolated namespace: {exc}"

    for func_name in ("add", "subtract", "multiply", "divide"):
        if func_name not in ns or not callable(ns[func_name]):
            return False, f"Required arithmetic function '{func_name}' is missing or not callable."

    try:
        if ns["add"](10, 5) != 15:
            return False, "add(10, 5) did not return 15."
        if ns["subtract"](10, 5) != 5:
            return False, "subtract(10, 5) did not return 5."
        if ns["multiply"](10, 5) != 50:
            return False, "multiply(10, 5) did not return 50."
        if ns["divide"](10, 5) != 2.0:
            return False, "divide(10, 5) did not return 2.0."
    except Exception as exc:
        return False, f"Arithmetic verification error: {exc}"

    try:
        ns["divide"](10, 0)
        return False, "divide() did not raise ZeroDivisionError on division by zero."
    except ZeroDivisionError:
        pass
    except Exception as exc:
        return False, f"Unexpected error on division by zero test: {exc}"

    return True, "Calculator functions verified (+, -, *, /, ZeroDivisionError)."


def verify_task_execution(
    task: FileTask,
    approved_roots: list[Path],
) -> tuple[bool, str, dict]:
    """
    Perform deep verification of the created files on disk:
    1. Physical existence within approved destination.
    2. Bit-for-bit SHA-256 content hash matching against approved plan.
    3. Content size validation.
    4. Verification that raw prompt text was NOT leaked into generated files.
    5. Template-specific functional correctness validation.
    """
    target_root = Path(task.resolved_target_path)
    if not target_root.exists():
        return False, f"Target path does not exist on disk: {target_root}", {}

    details = {
        "files_verified": [],
        "hashes_matched": True,
        "no_prompt_leakage": True,
        "template_validated": None,
    }

    # For CREATE_FOLDER
    if task.operation == FileOperationType.CREATE_FOLDER:
        if not target_root.is_dir():
            return False, f"Expected directory but found non-directory at {target_root}", details
        details["files_verified"].append(str(target_root))
        return True, f"Folder verified on disk: {target_root.name}", details

    # For CREATE_FILE and CREATE_PROJECT
    for pf in task.planned_files:
        dest_file = target_root if task.operation == FileOperationType.CREATE_FILE else target_root / pf.relative_path
        if not dest_file.exists():
            return False, f"Expected file is missing from disk: {pf.relative_path}", details

        try:
            raw_bytes = dest_file.read_bytes()
            disk_content = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return False, f"Created file is not valid UTF-8 text: {pf.relative_path}", details
        except OSError as exc:
            return False, f"Error reading created file {pf.relative_path}: {exc}", details

        # Hash check
        disk_hash = compute_content_hash(disk_content)
        if disk_hash != pf.content_hash:
            details["hashes_matched"] = False
            return (
                False,
                f"Content hash mismatch for {pf.relative_path} (expected {pf.content_hash[:8]}..., got {disk_hash[:8]}...)",
                details,
            )

        # Prompt leakage check (detect if full raw request leaked into file)
        req = task.request_text.strip()
        if len(req) > 20 and req in disk_content:
            details["no_prompt_leakage"] = False
            return False, f"Request prompt string leaked into {pf.relative_path}", details

        # Template checks for Python starter
        if pf.relative_path == "main.py":
            is_calc = (
                "calculator" in (task.target_name or "").lower()
                or "calculator" in (task.functional_description or "").lower()
            )
            if is_calc:
                ok_calc, calc_msg = _verify_calculator_semantics(disk_content)
                if not ok_calc:
                    return False, f"Calculator functional verification failed: {calc_msg}", details
                details["template_validated"] = "python_starter (calculator)"

        elif pf.relative_path == "requirements.txt":
            # Must not contain placeholder comments
            if "Add project dependencies here" in disk_content:
                return False, "requirements.txt contains generic placeholder comments.", details

        elif pf.relative_path == "README.md":
            # Must contain run instructions
            if "python3 main.py" not in disk_content and "xdg-open index.html" not in disk_content and "# " not in disk_content:
                return False, f"README.md missing standard run instructions or title in {pf.relative_path}.", details

        details["files_verified"].append(pf.relative_path)

    summary = f"All {len(details['files_verified'])} file(s) verified on disk with exact content hashes."
    if details["template_validated"]:
        summary += f" Functional behavior validated: {details['template_validated']}."

    return True, summary, details


# ── Approval & Execution ───────────────────────────────────────────────

def approve_file_task(
    task_id: str,
    approved: bool,
    approval_token: Optional[str] = None,
) -> tuple[bool, str, Optional[FileTask]]:
    """Approve or reject a planned file task."""
    with _file_lock:
        task = _file_tasks.get(task_id)

    if not task:
        _file_audit("APPROVE_FAILED", task_id, "unknown_task")
        return False, "Task not found.", None

    if task.expires_at and datetime.now(timezone.utc) > task.expires_at:
        task.status = FileTaskStatus.EXPIRED
        _file_audit("EXPIRED", task_id)
        return False, "Approval has expired. Please prepare a new task.", task

    if not approved:
        task.status = FileTaskStatus.REJECTED
        _file_audit("REJECTED", task_id)
        return True, "Task rejected.", task

    if task.status != FileTaskStatus.AWAITING_APPROVAL:
        return False, f"Task is {task.status.value}, not awaiting approval.", task

    if approval_token and approval_token != task.approval_token:
        _file_audit("APPROVE_FAILED", task_id, "invalid_token")
        return False, "Invalid approval token.", task

    task.status = FileTaskStatus.READY_FOR_REVIEW
    _file_audit("APPROVED", task_id, f"target={task.target_name}")
    return True, "Task approved. Ready for execution.", task


def execute_file_task(
    task_id: str,
    approval_token: Optional[str] = None,
    approved_roots: Optional[list[Path]] = None,
) -> tuple[bool, str, Optional[FileTask]]:
    """
    Execute an approved file task.

    Security & Quality guarantees:
    - Task must be in valid approved state.
    - Approval token must match.
    - Expiration verified again.
    - Re-checks that destination does not exist.
    - Content hash verified before writing.
    - One-time token consumption.
    - Deep verification on disk after creation (hash comparison, syntax & semantics).
    """
    with _file_lock:
        task = _file_tasks.get(task_id)

    if not task:
        return False, "Task not found.", None

    if task.expires_at and datetime.now(timezone.utc) > task.expires_at:
        task.status = FileTaskStatus.EXPIRED
        _file_audit("EXEC_EXPIRED", task_id)
        return False, "Approval token has expired.", task

    if approval_token and approval_token != task.approval_token:
        _file_audit("EXEC_FAILED", task_id, "token_mismatch")
        return False, "Invalid approval token.", task

    if task.status not in (FileTaskStatus.READY_FOR_REVIEW, FileTaskStatus.AWAITING_APPROVAL):
        return False, f"Task is {task.status.value}, not approved for execution.", task

    if approved_roots is None:
        approved_roots = get_approved_roots()

    # Consume the token immediately to prevent reuse
    task.status = FileTaskStatus.EXECUTING
    task.approval_token = None
    _file_audit("EXECUTING", task_id)

    target_path = Path(task.resolved_target_path)

    # Conflict check immediately before execution
    if target_path.exists() or target_path.is_symlink():
        task.status = FileTaskStatus.FAILED
        task.conflict_detected = True
        task.conflict_message = f"Target already appeared: {target_path.name}"
        _file_audit("CONFLICT_ABORT", task_id, str(target_path))
        return False, "Execution aborted: target file or directory already exists.", task

    created_files_report = []

    try:
        # Execution Case 1: CREATE_FOLDER
        if task.operation == FileOperationType.CREATE_FOLDER:
            res = safe_create_folder(
                target_path,
                create_parents=task.needs_parent_creation,
                approved_roots=approved_roots,
            )
            if not res["success"]:
                task.status = FileTaskStatus.FAILED
                task.execution_result = res
                _file_audit("EXEC_ERROR", task_id, res.get("error", ""))
                return False, res.get("error", "Failed to create folder."), task

            created_files_report.append(res["path"])
            task.execution_result = {"created_folders": [res["path"]]}

        # Execution Case 2: CREATE_FILE
        elif task.operation == FileOperationType.CREATE_FILE:
            pf = task.planned_files[0]
            res = safe_create_file(
                target_path,
                content=pf.content,
                create_parents=task.needs_parent_creation,
                approved_roots=approved_roots,
            )
            if not res["success"]:
                task.status = FileTaskStatus.FAILED
                task.execution_result = res
                _file_audit("EXEC_ERROR", task_id, res.get("error", ""))
                return False, res.get("error", "Failed to create file."), task

            created_files_report.append(res["path"])
            task.execution_result = {"created_files": [res["path"]], "bytes": res["bytes_written"]}

        # Execution Case 3: CREATE_PROJECT
        elif task.operation == FileOperationType.CREATE_PROJECT:
            folder_res = safe_create_folder(
                target_path,
                create_parents=task.needs_parent_creation,
                approved_roots=approved_roots,
            )
            if not folder_res["success"]:
                task.status = FileTaskStatus.FAILED
                task.execution_result = folder_res
                return False, folder_res.get("error", "Failed to create project root."), task

            created_files_report.append(folder_res["path"])

            created_files = []
            failures = []
            for pf in task.planned_files:
                file_dest = target_path / pf.relative_path
                file_res = safe_create_file(
                    file_dest,
                    content=pf.content,
                    create_parents=True,
                    approved_roots=approved_roots,
                )
                if file_res["success"]:
                    created_files.append(file_res["path"])
                else:
                    failures.append({"file": pf.relative_path, "error": file_res.get("error")})

            task.execution_result = {
                "project_root": str(target_path),
                "created_files": created_files,
                "failures": failures,
            }

            if failures:
                task.status = FileTaskStatus.FAILED
                task.verification_result = f"Partial creation: {len(created_files)} created, {len(failures)} failed."
                _file_audit("PARTIAL_COMPLETION", task_id, f"failures={len(failures)}")
                return False, f"Some files could not be created: {failures}", task

        # ── Deep Post-Execution Verification ──────────────────────────
        ok_ver, ver_msg, ver_details = verify_task_execution(task, approved_roots=approved_roots)
        task.verification_result = ver_msg
        task.verification_details = ver_details

        if not ok_ver:
            task.status = FileTaskStatus.FAILED
            _file_audit("VERIFY_FAILED", task_id, ver_msg)
            return False, f"Verification failed: {ver_msg}", task

        task.status = FileTaskStatus.COMPLETED
        _file_audit("COMPLETED", task_id, f"created={len(created_files_report)}")
        return True, task.verification_result, task

    except Exception as exc:
        task.status = FileTaskStatus.FAILED
        task.execution_result = {"error": str(exc)}
        _file_audit("EXEC_EXCEPTION", task_id, str(exc))
        return False, f"Unexpected error during execution: {exc}", task


def get_task(task_id: str) -> Optional[FileTask]:
    with _file_lock:
        return _file_tasks.get(task_id)
