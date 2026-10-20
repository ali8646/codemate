import time
from unittest.mock import MagicMock, patch
from app.agent.graph import build_auditor_graph, AuditorState
from app.agent.prompts import ScoutResult, AuditPhaseOutput, CandidateFinding, VerificationDecision
from app.schemas.audit import IssueCategory, Severity


def test_langgraph_pipeline_end_to_end():
    """
    Simulates the full LangGraph workflow:
    Scout -> Audit -> Verify (Filtering False Positives) -> Remediation Report
    """
    # 1. Mock Gemini Scout Output
    mock_scout_output = ScoutResult(
        framework="FastAPI",
        orm_used="SQLAlchemy",
        is_async=True,
        crypto_libraries=[],
        priority_files_to_audit=["routes.py"],
        summary="FastAPI application with SQLAlchemy database models and async routes.",
    )

    # 2. Mock Gemini Audit Output (2 candidate findings: 1 true positive, 1 false positive candidate)
    mock_audit_output = AuditPhaseOutput(
        candidate_findings=[
            CandidateFinding(
                title="ORM N+1 Query in GET /users/profiles",
                category=IssueCategory.PERFORMANCE,
                severity=Severity.HIGH,
                file_path="routes.py",
                line_start=18,
                line_end=25,
                explanation="Executing db.query(Profile) inside for user in users triggers repeated queries.",
                code_diff="""--- routes.py
+++ routes.py
@@ -18,3 +18,3 @@
- users = db.query(User).all()
- for user in users:
-     profile = db.query(Profile).filter(Profile.user_id == user.id).first()
+ users = db.query(User).options(joinedload(User.profile)).all()
+ for user in users:
+     profile = user.profile""",
            ),
            CandidateFinding(
                title="Potential Blocking Call in routes.py",
                category=IssueCategory.PERFORMANCE,
                severity=Severity.MEDIUM,
                file_path="routes.py",
                line_start=30,
                line_end=35,
                explanation="Calling time.sleep(2) inside async def blocks the asyncio event loop.",
                code_diff="""--- routes.py
+++ routes.py
@@ -32,2 +32,2 @@
- time.sleep(2)
+ await asyncio.sleep(2)""",
            ),
        ]
    )

    # 3. Mock Gemini Verifier Output (confirms both findings)
    mock_verifier_decision = VerificationDecision(
        is_valid=True,
        confidence=0.95,
        reason="Verified: the query is executed inside a loop over parent models without eager loading.",
        refined_diff=None,
    )

    # Compile the LangGraph agent
    graph = build_auditor_graph()

    # Initial State targeting local benchmark
    initial_state: AuditorState = {
        "audit_id": "test-audit-123",
        "repo_target": "benchmarks/fastapi_nplusone",
        "auto_file_issues": False,
        "branch": "main",
        "repo_path": None,
        "start_time": time.time(),
        "stage": "INITIALIZING",
        "status_messages": ["Starting test audit..."],
        "error": None,
        "scout_result": None,
        "files_to_audit": [],
        "total_files_scanned": 0,
        "candidate_findings": [],
        "verified_findings": [],
        "rejected_findings": [],
        "report": None,
    }

    # Patch the Gemini LLM calls
    with patch("app.agent.graph.get_llm") as mock_get_llm:
        mock_llm_instance = MagicMock()
        mock_get_llm.return_value = mock_llm_instance

        # Mock structured output invoke responses
        def structured_output_side_effect(schema):
            mock_sub = MagicMock()
            if schema == ScoutResult:
                mock_sub.invoke.return_value = mock_scout_output
            elif schema == AuditPhaseOutput:
                mock_sub.invoke.return_value = mock_audit_output
            elif schema == VerificationDecision:
                mock_sub.invoke.return_value = mock_verifier_decision
            return mock_sub

        mock_llm_instance.with_structured_output.side_effect = structured_output_side_effect

        # Run the full LangGraph pipeline
        final_state = graph.invoke(initial_state)

    # Assertions on Pipeline Outputs
    assert final_state["stage"] == "COMPLETED"
    assert len(final_state["verified_findings"]) == 2
    
    report = final_state["report"]
    assert report is not None
    assert report["audit_id"] == "test-audit-123"
    assert len(report["findings"]) == 2
    assert report["findings"][0]["title"] == "ORM N+1 Query in GET /users/profiles"
    assert "joinedload" in report["findings"][0]["code_diff"]
    assert report["findings"][1]["title"] == "Potential Blocking Call in routes.py"
    assert report["duration_seconds"] >= 0.0
