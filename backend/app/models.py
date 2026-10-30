"""Pydantic models for TERMIQ's diagnosis, planning, execution, and file copilot pipeline."""

import enum
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Existing Diagnostic & System Models ───────────────────────────────

class ActionType(str, enum.Enum):
    """Supported action categories."""
    CHECK_UPTIME = "check_uptime"
    CHECK_MEMORY = "check_memory"
    CHECK_DISK = "check_disk"
    CHECK_PROCESSES = "check_processes"
    CHECK_FAILED_SERVICES = "check_failed_services"
    CHECK_JOURNAL_ERRORS = "check_journal_errors"
    CHECK_NETWORK = "check_network"
    CHECK_TEMPERATURE = "check_temperature"
    MANUAL_STEP = "manual_step"  # Explain-only, never executed
    # New action types
    CHECK_NETWORK_CONNECTIVITY = "check_network_connectivity"
    CHECK_DISK_IO = "check_disk_io"
    CHECK_BATTERY = "check_battery"
    RUN_UNIT_TESTS = "run_unit_tests"
    CREATE_VIRTUALENV = "create_virtualenv"
    INSPECT_GIT_STATUS = "inspect_git_status"
    OPEN_IN_EDITOR = "open_in_editor"


class RiskLevel(str, enum.Enum):
    SAFE = "safe"          # Read-only diagnostic or inspection
    CAUTION = "caution"    # User-approved file creation/edit/move
    MODERATE = "moderate"  # Backward compatibility alias
    RESTRICTED = "restricted" # System changes requiring strict approval
    HIGH = "high"          # Blocked / destructive


class PlanStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    VERIFIED = "verified"


class ProposedAction(BaseModel):
    """A single action the backend can execute after approval."""
    action_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    action_type: ActionType
    description: str
    risk_level: RiskLevel = RiskLevel.SAFE
    requires_approval: bool = True
    verification_method: str = "Compare output against expected values"


class TroubleshootingPlan(BaseModel):
    """Complete diagnosis-plan-execute-verify record."""
    plan_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    question: str
    diagnosis_summary: str = ""
    evidence: list[dict] = Field(default_factory=list)
    possible_causes: list[str] = Field(default_factory=list)
    proposed_action: Optional[ProposedAction] = None
    status: PlanStatus = PlanStatus.PROPOSED
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None
    execution_result: Optional[dict] = None
    verification_result: Optional[str] = None
    verification_details: Optional[dict] = None


class ApproveRequest(BaseModel):
    """Frontend request to approve/reject a proposed action."""
    plan_id: str
    action_id: str
    approved: bool


class AskRequest(BaseModel):
    """User question to the assistant."""
    question: str
    mode: str = "beginner"  # "beginner" or "advanced"


class AskResponse(BaseModel):
    """Structured response from the assistant."""
    question: str
    answer: str
    source: str = "live_system_diagnostics"
    diagnostics: dict = Field(default_factory=dict)
    top_processes: dict = Field(default_factory=dict)
    failed_services: dict = Field(default_factory=dict)
    findings: list[dict] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    ai_enabled: bool = False
    plan: Optional[TroubleshootingPlan] = None
    structured_sections: Optional[dict] = None


class AuditEntry(BaseModel):
    """Immutable record of a security-relevant event."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: str
    plan_id: str = ""
    action_id: str = ""
    detail: str = ""


# ── File & Folder Copilot Models (V2.0 & V2.1) ────────────────────────

class FileOperationType(str, enum.Enum):
    """Supported file operations."""
    CREATE_FILE = "create_file"
    CREATE_FOLDER = "create_folder"
    CREATE_PROJECT = "create_project"
    LIST_DIR = "list_dir"
    SEARCH_FILES = "search_files"
    READ_FILE = "read_file"
    # Advanced operations
    EDIT_FILE = "edit_file"
    COPY_FILE = "copy_file"
    MOVE_FILE = "move_file"
    RENAME_FILE = "rename_file"
    TRASH_FILE = "trash_file"
    FIND_DUPLICATES = "find_duplicates"
    FIND_LARGE_FILES = "find_large_files"
    ORGANIZE_FOLDER = "organize_folder"


class FileTaskStatus(str, enum.Enum):
    """Lifecycle states for a file task."""
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY_FOR_REVIEW = "ready_for_review"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ProjectTemplate(str, enum.Enum):
    """Predefined project templates."""
    PYTHON_STARTER = "python_starter"
    HTML_WEBSITE = "html_website"
    MARKDOWN_DOCS = "markdown_docs"
    FLASK_STARTER = "flask_starter"
    FASTAPI_STARTER = "fastapi_starter"
    DATA_ANALYSIS = "data_analysis"


class PlannedFile(BaseModel):
    """A file planned for creation as part of a task."""
    relative_path: str
    content: str
    content_hash: str
    size_bytes: int
    description: str = ""


class FileTask(BaseModel):
    """Structured file operation task with clarification and approval state."""
    task_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    request_text: str
    operation: FileOperationType
    status: FileTaskStatus = FileTaskStatus.NEEDS_CLARIFICATION

    # Target path specifications (user-facing and resolved canonical)
    target_directory: Optional[str] = None
    resolved_target_directory: Optional[str] = None
    target_name: Optional[str] = None
    target_path: Optional[str] = None
    resolved_target_path: Optional[str] = None

    # Destination for copy/move/rename
    destination_path: Optional[str] = None
    resolved_destination_path: Optional[str] = None

    # Optional template
    template: Optional[ProjectTemplate] = None
    requested_filenames: list[str] = Field(default_factory=list)
    functional_description: Optional[str] = None

    # Clarification questions when important details are missing
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_fields_needed: list[str] = Field(default_factory=list)
    user_provided_answers: dict[str, str] = Field(default_factory=dict)

    # Planned files and content hashes
    planned_files: list[PlannedFile] = Field(default_factory=list)
    diff_preview: Optional[str] = None
    summary: str = ""

    # Hierarchy and conflict detection
    needs_parent_creation: bool = False
    parent_dirs_to_create: list[str] = Field(default_factory=list)
    conflict_detected: bool = False
    conflict_message: Optional[str] = None

    # Approval security binding
    approval_token: Optional[str] = None
    approved_hash: Optional[str] = None
    requires_approval: bool = True

    # Timestamps & expiry
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    # Results
    execution_result: Optional[dict] = None
    verification_result: Optional[str] = None
    verification_details: Optional[dict] = None


class CreateFileTaskRequest(BaseModel):
    """Initial user request to the File Copilot."""
    request: str
    context_directory: Optional[str] = None


class ClarifyFileTaskRequest(BaseModel):
    """User response providing clarification answers."""
    answers: dict[str, str] = Field(default_factory=dict)
    text: Optional[str] = None


class ApproveFileTaskRequest(BaseModel):
    """Approval or rejection decision for a file task."""
    approved: bool
    approval_token: Optional[str] = None


class EditFileRequest(BaseModel):
    """Request to safely edit a file."""
    path: str
    new_content: str
    create_backup: bool = True


class CopyMoveFileRequest(BaseModel):
    """Request to copy or move a file."""
    source_path: str
    destination_path: str
    operation: str = "copy"  # "copy", "move", or "rename"
    approved: bool = False
    approval_token: Optional[str] = None


class TrashFileRequest(BaseModel):
    """Request to move a file to Trash."""
    path: str
    approved: bool = False
    approval_token: Optional[str] = None


class OrganizeFolderRequest(BaseModel):
    """Request to organize a folder by file categories."""
    path: str
    dry_run: bool = True
    approved: bool = False
    approval_token: Optional[str] = None


# ── Developer Copilot Models ──────────────────────────────────────────

class ExplainErrorRequest(BaseModel):
    """Request to explain a Python error or stack trace."""
    error_text: str
    context_code: Optional[str] = None
    mode: str = "beginner"


class ExplainErrorResponse(BaseModel):
    """Structured response explaining a Python error."""
    error_type: str
    summary: str
    current_evidence: str
    possible_causes: list[str]
    recommended_fix: str
    code_example: Optional[str] = None
    source: str = "ai_or_rules"


class CreateVenvRequest(BaseModel):
    """Request to create a virtual environment."""
    directory: str
    venv_name: str = ".venv"
    approved: bool = False
    approval_token: Optional[str] = None


class CreateVenvResponse(BaseModel):
    """Result of creating a virtual environment."""
    success: bool
    venv_path: str
    python_path: str
    message: str


class RunTestsRequest(BaseModel):
    """Request to run tests in a project directory."""
    project_directory: str
    approved: bool = True
    approval_token: Optional[str] = None


class RunTestsResponse(BaseModel):
    """Result of running unit tests."""
    success: bool
    passed: int
    failed: int
    errors: int
    duration_seconds: float
    output: str
    summary: str


class GitStatusRequest(BaseModel):
    """Request to inspect Git status in a project directory."""
    project_directory: str


class GitStatusResponse(BaseModel):
    """Git status and recent commits."""
    is_git_repo: bool
    branch: str
    modified_files: list[str]
    untracked_files: list[str]
    recent_commits: list[str]
    clean: bool


class OpenEditorRequest(BaseModel):
    """Request to open a project or file in VS Code or editor."""
    target_path: str
    editor: str = "code"


class OpenEditorResponse(BaseModel):
    """Result of opening editor."""
    success: bool
    editor_used: str
    message: str


# ── Notification Models ───────────────────────────────────────────────

class NotificationSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


class NotificationItem(BaseModel):
    """A notification in the TERMIQ notification center."""
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str
    message: str
    severity: NotificationSeverity = NotificationSeverity.INFO
    category: str = "system"  # "system", "task", "file", "security"
    task_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    is_read: bool = False


# ── Automation Models ─────────────────────────────────────────────────

class AutomationWorkflow(BaseModel):
    """A user-triggerable or scheduled workflow."""
    id: str
    name: str
    description: str
    category: str
    requires_approval: bool = True
    is_enabled: bool = True
    last_run: Optional[datetime] = None
    last_status: Optional[str] = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunRequest(BaseModel):
    """Request to execute an automation workflow."""
    workflow_id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    approved: bool = False
    approval_token: Optional[str] = None


class AutomationExecutionRecord(BaseModel):
    """Record of an automation run."""
    run_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    workflow_id: str
    workflow_name: str
    status: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    output: Optional[dict] = None
    error: Optional[str] = None


# ── Unified Task & History Models ─────────────────────────────────────

class TaskCategory(str, enum.Enum):
    SYSTEM_DIAGNOSTIC = "system_diagnostic"
    FILE_OPERATION = "file_operation"
    DEVELOPER_TOOL = "developer_tool"
    AUTOMATION = "automation"


class UnifiedTask(BaseModel):
    """Unified representation of any TERMIQ task for history and management."""
    task_id: str
    category: TaskCategory
    title: str
    request_text: str
    status: str
    risk_level: RiskLevel = RiskLevel.SAFE
    requires_approval: bool = True
    approval_token: Optional[str] = None
    summary: str = ""
    details: dict[str, Any] = Field(default_factory=dict)
    verification_result: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ── System Monitor Comprehensive Models ────────────────────────────────

class SystemMonitorData(BaseModel):
    """Complete live system stats for the System Monitor section."""
    os: str
    uptime_seconds: float
    uptime_human: str
    boot_time: str
    cpu: dict
    memory: dict
    swap: dict
    disk: dict
    network: dict
    battery: dict
    temperatures: dict
    processes: list[dict]
    failed_services: list[dict]


# ── User Settings Models ──────────────────────────────────────────────

class UserSettings(BaseModel):
    """TERMIQ user preferences and configuration."""
    approved_roots: list[str] = Field(default_factory=list)
    refresh_interval_seconds: int = 5
    mode: str = "beginner"  # "beginner" or "advanced"
    notifications_enabled: bool = True
    retention_days: int = 30
    theme: str = "dark"
