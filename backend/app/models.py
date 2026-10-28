"""Pydantic models for TERMIQ's diagnosis, planning, and execution pipeline."""

import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field


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
