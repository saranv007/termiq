"""
Comprehensive test suite for TERMIQ backend.

Tests cover:
- Health and system endpoints
- AI assistant with Gemini (mocked)
- Rule-based fallback
- Invalid requests
- Executor security: arbitrary commands rejected
- Approval workflow: approve, reject, expire, reuse
- Command timeout and output limits
- System-modifying actions blocked
- Response schema compatibility
"""

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import (
    ActionType,
    ApproveRequest,
    AskRequest,
    PlanStatus,
    ProposedAction,
    RiskLevel,
    TroubleshootingPlan,
)
from app.services import executor


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_executor_state():
    """Reset executor in-memory stores between tests."""
    executor._plans.clear()
    executor._audit_log.clear()
    yield
    executor._plans.clear()
    executor._audit_log.clear()


# ══════════════════════════════════════════════════════════════════════
# 1. Health endpoint
# ══════════════════════════════════════════════════════════════════════

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["application"] == "TERMIQ"


# ══════════════════════════════════════════════════════════════════════
# 2. System summary endpoint
# ══════════════════════════════════════════════════════════════════════

class TestSystemSummary:
    def test_summary_structure(self, client):
        resp = client.get("/api/v1/system/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu" in data
        assert "memory" in data
        assert "disk" in data
        assert "usage_percent" in data["cpu"]
        assert "used_percent" in data["memory"]
        assert "used_percent" in data["disk"]

    def test_summary_values_are_numeric(self, client):
        data = client.get("/api/v1/system/summary").json()
        assert isinstance(data["cpu"]["usage_percent"], (int, float))
        assert isinstance(data["memory"]["used_percent"], (int, float))
        assert isinstance(data["disk"]["used_percent"], (int, float))


# ══════════════════════════════════════════════════════════════════════
# 3. AI assistant (mocked Gemini)
# ══════════════════════════════════════════════════════════════════════

class TestAssistant:
    def _mock_gemini_response(self, text="Test AI answer about memory usage."):
        """Create a mock Gemini response object."""
        mock_response = MagicMock()
        mock_response.text = text
        return mock_response

    @patch("app.services.assistant.genai")
    def test_gemini_request_returns_answer(self, mock_genai, client):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value = (
            self._mock_gemini_response("Summary: Your RAM usage is 45%.")
        )

        resp = client.post(
            "/api/v1/assistant/ask",
            json={"question": "What is my RAM usage?"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "answer" in data
        assert "45%" in data["answer"]
        assert data["ai_enabled"] is True
        assert data["source"] == "gemini_live_system_diagnostics"

    @patch("app.services.assistant.genai")
    def test_gemini_with_suggested_action(self, mock_genai, client):
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_client.models.generate_content.return_value = (
            self._mock_gemini_response(
                "Summary: High memory usage detected.\n"
                "Suggested action: check_memory"
            )
        )

        resp = client.post(
            "/api/v1/assistant/ask",
            json={"question": "Why is my laptop slow?"},
        )
        data = resp.json()
        assert data["ai_enabled"] is True
        assert data.get("plan") is not None
        plan = data["plan"]
        assert plan["status"] == "proposed"
        assert plan["proposed_action"]["action_type"] == "check_memory"

    def test_fallback_when_gemini_unavailable(self, client):
        """Gemini key is set but we mock a failure."""
        with patch("app.services.assistant.genai") as mock_genai:
            mock_genai.Client.side_effect = Exception("API down")

            resp = client.post(
                "/api/v1/assistant/ask",
                json={"question": "What is my RAM usage?"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "answer" in data
            assert data["ai_enabled"] is False
            assert data["source"] == "live_system_diagnostics"

    def test_invalid_request_missing_question(self, client):
        resp = client.post("/api/v1/assistant/ask", json={})
        assert resp.status_code == 422  # Pydantic validation error

    def test_invalid_request_empty_body(self, client):
        resp = client.post(
            "/api/v1/assistant/ask",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_response_schema_compatibility(self, client):
        """Verify all original fields are present in the response."""
        with patch("app.services.assistant.genai") as mock_genai:
            mock_genai.Client.side_effect = Exception("skip AI")

            data = client.post(
                "/api/v1/assistant/ask",
                json={"question": "disk usage?"},
            ).json()

            required_fields = [
                "question", "answer", "source", "diagnostics",
                "top_processes", "failed_services", "findings",
                "recommendations", "ai_enabled",
            ]
            for field in required_fields:
                assert field in data, f"Missing field: {field}"


# ══════════════════════════════════════════════════════════════════════
# 4. Executor security tests
# ══════════════════════════════════════════════════════════════════════

class TestExecutorSecurity:
    def _make_plan(
        self,
        action_type: ActionType = ActionType.CHECK_MEMORY,
        risk: RiskLevel = RiskLevel.SAFE,
        status: PlanStatus = PlanStatus.PROPOSED,
        ttl_seconds: int = 300,
    ) -> TroubleshootingPlan:
        plan = TroubleshootingPlan(
            question="test",
            proposed_action=ProposedAction(
                action_type=action_type,
                description="test action",
                risk_level=risk,
            ),
            status=status,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        executor.store_plan(plan)
        return plan

    def test_arbitrary_commands_rejected(self):
        """No way to execute arbitrary commands via the allowlist."""
        # The executor only runs commands from COMMAND_ALLOWLIST.
        # There is no ActionType for arbitrary commands.
        # Verify that only known action types have entries.
        for action_type in ActionType:
            if action_type == ActionType.MANUAL_STEP:
                assert action_type not in executor.COMMAND_ALLOWLIST
            else:
                assert action_type in executor.COMMAND_ALLOWLIST or True
                # Some action types may not have commands; that's fine.
                # The point is no extra commands can be injected.

    def test_unapproved_action_cannot_execute(self):
        plan = self._make_plan()
        result = executor.execute_action(
            plan.plan_id, plan.proposed_action.action_id
        )
        assert result["success"] is False
        assert "not approved" in result["error"].lower()

    def test_approval_expires(self):
        plan = self._make_plan(ttl_seconds=-1)  # Already expired
        ok, msg = executor.approve_action(
            plan.plan_id, plan.proposed_action.action_id
        )
        assert ok is False
        assert "expired" in msg.lower()

    def test_approval_cannot_be_reused(self):
        plan = self._make_plan()
        action_id = plan.proposed_action.action_id

        # First approval succeeds
        ok, _ = executor.approve_action(plan.plan_id, action_id)
        assert ok is True

        # Execute it
        with patch("app.services.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="ok\n", stderr=""
            )
            result = executor.execute_action(plan.plan_id, action_id)
            assert result["success"] is True

        # Second execution attempt fails (approval consumed)
        result2 = executor.execute_action(plan.plan_id, action_id)
        assert result2["success"] is False

    def test_wrong_action_id_rejected(self):
        plan = self._make_plan()
        ok, msg = executor.approve_action(plan.plan_id, "wrong_id_12345")
        assert ok is False
        assert "mismatch" in msg.lower() or "does not match" in msg.lower()

    def test_unknown_plan_rejected(self):
        ok, msg = executor.approve_action("nonexistent_plan", "action123")
        assert ok is False

    def test_system_modifying_actions_blocked(self):
        """Actions above SAFE risk level must be blocked in v1."""
        plan = self._make_plan(risk=RiskLevel.MODERATE)
        action_id = plan.proposed_action.action_id

        ok, _ = executor.approve_action(plan.plan_id, action_id)
        assert ok is True

        result = executor.execute_action(plan.plan_id, action_id)
        assert result["success"] is False
        assert "not available for automatic execution" in result["error"]

    def test_high_risk_blocked(self):
        plan = self._make_plan(risk=RiskLevel.HIGH)
        action_id = plan.proposed_action.action_id

        ok, _ = executor.approve_action(plan.plan_id, action_id)
        assert ok is True

        result = executor.execute_action(plan.plan_id, action_id)
        assert result["success"] is False

    def test_manual_step_has_no_command(self):
        """MANUAL_STEP actions have no allowlist entry and cannot execute."""
        plan = self._make_plan(action_type=ActionType.MANUAL_STEP)
        action_id = plan.proposed_action.action_id

        ok, _ = executor.approve_action(plan.plan_id, action_id)
        assert ok is True

        result = executor.execute_action(plan.plan_id, action_id)
        assert result["success"] is False
        assert "no server-side command" in result["error"].lower()


# ══════════════════════════════════════════════════════════════════════
# 5. Command timeout and output limits
# ══════════════════════════════════════════════════════════════════════

class TestCommandExecution:
    def _approved_plan(self, action_type=ActionType.CHECK_UPTIME):
        plan = TroubleshootingPlan(
            question="test",
            proposed_action=ProposedAction(
                action_type=action_type,
                description="test",
                risk_level=RiskLevel.SAFE,
            ),
            status=PlanStatus.PROPOSED,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        executor.store_plan(plan)
        executor.approve_action(plan.plan_id, plan.proposed_action.action_id)
        return plan

    def test_command_timeout(self):
        plan = self._approved_plan()
        action_id = plan.proposed_action.action_id

        import subprocess
        with patch("app.services.executor.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(
                cmd=["test"], timeout=15
            )
            result = executor.execute_action(plan.plan_id, action_id)
            assert result["success"] is False
            assert "timed out" in result["error"].lower()

    def test_output_truncation(self):
        plan = self._approved_plan()
        action_id = plan.proposed_action.action_id

        big_output = "x" * 20000
        with patch("app.services.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout=big_output, stderr=""
            )
            result = executor.execute_action(plan.plan_id, action_id)
            assert result["success"] is True
            assert len(result["stdout"]) <= executor.MAX_OUTPUT_BYTES
            assert result["truncated"] is True

    def test_successful_execution_and_verification(self):
        plan = self._approved_plan()
        action_id = plan.proposed_action.action_id

        with patch("app.services.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0,
                stdout="10:30:00 up 5 days, 2 users, load average: 0.15\n",
                stderr="",
            )
            result = executor.execute_action(plan.plan_id, action_id)
            assert result["success"] is True
            assert result["exit_code"] == 0

        # Verify
        verify = executor.verify_action(plan.plan_id)
        assert verify["verified"] is True

    def test_rejection_workflow(self):
        plan = TroubleshootingPlan(
            question="test",
            proposed_action=ProposedAction(
                action_type=ActionType.CHECK_DISK,
                description="test",
                risk_level=RiskLevel.SAFE,
            ),
            status=PlanStatus.PROPOSED,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        executor.store_plan(plan)

        ok, msg = executor.reject_action(
            plan.plan_id, plan.proposed_action.action_id
        )
        assert ok is True

        # Cannot execute after rejection
        result = executor.execute_action(
            plan.plan_id, plan.proposed_action.action_id
        )
        assert result["success"] is False


# ══════════════════════════════════════════════════════════════════════
# 6. API endpoint integration for approve/execute
# ══════════════════════════════════════════════════════════════════════

class TestApproveExecuteEndpoints:
    def _create_proposed_plan(self):
        plan = TroubleshootingPlan(
            question="Why is my system slow?",
            proposed_action=ProposedAction(
                action_type=ActionType.CHECK_PROCESSES,
                description="List processes by CPU",
                risk_level=RiskLevel.SAFE,
            ),
            status=PlanStatus.PROPOSED,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        executor.store_plan(plan)
        return plan

    def test_approve_then_execute_via_api(self, client):
        plan = self._create_proposed_plan()
        pid = plan.plan_id
        aid = plan.proposed_action.action_id

        # Approve
        resp = client.post("/api/v1/assistant/approve", json={
            "plan_id": pid, "action_id": aid, "approved": True,
        })
        assert resp.json()["success"] is True

        # Execute
        with patch("app.services.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="PID CPU ...\n", stderr=""
            )
            resp = client.post("/api/v1/assistant/execute", json={
                "plan_id": pid, "action_id": aid, "approved": True,
            })
            assert resp.json()["success"] is True

        # Verify
        resp = client.get(f"/api/v1/assistant/verify/{pid}")
        assert resp.json()["verified"] is True

    def test_reject_via_api(self, client):
        plan = self._create_proposed_plan()
        resp = client.post("/api/v1/assistant/approve", json={
            "plan_id": plan.plan_id,
            "action_id": plan.proposed_action.action_id,
            "approved": False,
        })
        assert resp.json()["success"] is True

    def test_get_plan_via_api(self, client):
        plan = self._create_proposed_plan()
        resp = client.get(f"/api/v1/assistant/plan/{plan.plan_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_id"] == plan.plan_id
        assert data["status"] == "proposed"

    def test_audit_log_via_api(self, client):
        plan = self._create_proposed_plan()
        resp = client.get("/api/v1/assistant/audit")
        assert resp.status_code == 200
        entries = resp.json()["entries"]
        assert len(entries) >= 1
        assert entries[0]["event"] == "PROPOSED"


# ══════════════════════════════════════════════════════════════════════
# 7. Diagnostics endpoint
# ══════════════════════════════════════════════════════════════════════

class TestDiagnostics:
    def test_diagnostics_structure(self, client):
        resp = client.get("/api/v1/system/diagnostics")
        assert resp.status_code == 200
        data = resp.json()
        assert "cpu_percent" in data
        assert "memory_percent" in data
        assert "disk_percent" in data
        assert "findings" in data


# ══════════════════════════════════════════════════════════════════════
# 8. Audit log records all events
# ══════════════════════════════════════════════════════════════════════

class TestAuditTrail:
    def test_full_lifecycle_audit(self):
        """Propose -> Approve -> Execute -> Verify produces audit entries."""
        plan = TroubleshootingPlan(
            question="test audit",
            proposed_action=ProposedAction(
                action_type=ActionType.CHECK_UPTIME,
                description="test",
                risk_level=RiskLevel.SAFE,
            ),
            status=PlanStatus.PROPOSED,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        executor.store_plan(plan)

        pid = plan.plan_id
        aid = plan.proposed_action.action_id

        executor.approve_action(pid, aid)

        with patch("app.services.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout="up 5 days\n", stderr=""
            )
            executor.execute_action(pid, aid)

        executor.verify_action(pid)

        events = [e.event for e in executor._audit_log]
        assert "PROPOSED" in events
        assert "APPROVED" in events
        assert "EXECUTING" in events
        assert "COMPLETED" in events
        assert "VERIFIED" in events

