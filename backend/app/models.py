"""Pydantic models for TERMIQ's diagnosis, planning, execution, and file copilot pipeline."""

import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Existing Diagnostic & System Models ───────────────────────────────

class ActionType(str, enum.Enum):
    """Supported action categories. Only read-only diagnostics in v1."""
    CHECK_UPTIME = "check_uptime"
    CHECK_MEMORY = "check_memory"
    CHECK_DISK = "check_disk"
    CHECK_PROCESSES = "check_processes"
    CHECK_FAILED_SERVICES = "check_failed_services"
    CHECK_JOURNAL_ERRORS = "check_journal_errors"
    CHECK_NETWORK = "check_network"
    CHECK_TEMPERATURE = "check_temperature"
    MANUAL_STEP = "manual_step"  # Explain-only, never executed


class RiskLevel(str, enum.Enum):
    SAFE = "safe"          # Read-only diagnostic
    MODERATE = "moderate"  # System-modifying (blocked in v1)
    HIGH = "high"          # Destructive (blocked in v1)


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


class ApproveRequest(BaseModel):
    """Frontend request to approve/reject a proposed action."""
    plan_id: str
    action_id: str
    approved: bool


class AskRequest(BaseModel):
    """User question to the assistant."""
    question: str


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


class AuditEntry(BaseModel):
    """Immutable record of a security-relevant event."""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event: str
    plan_id: str = ""
    action_id: str = ""
    detail: str = ""


# ── File & Folder Copilot Models (V2.0) ────────────────────────────────

class FileOperationType(str, enum.Enum):
    """Supported file operations in V2.0."""
    CREATE_FILE = "create_file"
    CREATE_FOLDER = "create_folder"
    CREATE_PROJECT = "create_project"
    LIST_DIR = "list_dir"
    SEARCH_FILES = "search_files"
    READ_FILE = "read_file"


class FileTaskStatus(str, enum.Enum):
    """Lifecycle states for a file task."""
    NEEDS_CLARIFICATION = "needs_clarification"
    READY_FOR_REVIEW = "ready_for_review"
    AWAITING_APPROVAL = "awaiting_approval"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class ProjectTemplate(str, enum.Enum):
    """Predefined project templates."""
    PYTHON_STARTER = "python_starter"
    HTML_WEBSITE = "html_website"
    MARKDOWN_DOCS = "markdown_docs"


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

    # Optional template
    template: Optional[ProjectTemplate] = None

    # Clarification questions when important details are missing
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_fields_needed: list[str] = Field(default_factory=list)
    user_provided_answers: dict[str, str] = Field(default_factory=dict)

    # Planned files and content hashes
    planned_files: list[PlannedFile] = Field(default_factory=list)
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
