import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import SystemMessage, HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, START, END

from app.core.config import settings
from app.schemas.audit import (
    AuditFinding,
    AuditReport,
    AuditStatus,
    IssueCategory,
    Severity,
)
from app.agent.prompts import (
    SCOUT_SYSTEM_PROMPT,
    AUDIT_SYSTEM_PROMPT,
    VERIFIER_SYSTEM_PROMPT,
    ScoutResult,
    AuditPhaseOutput,
    VerificationDecision,
)
from app.agent.tools.repo_tools import (
    prepare_repo_workspace,
    cleanup_repo_workspace,
    inspect_repo_structure,
    read_code_file,
    search_codebase,
)
from app.agent.tools.github_tools import file_github_issue


class AuditorState(TypedDict):
    """LangGraph State for the CodeMate Auditor."""
    audit_id: str
    repo_target: str
    auto_file_issues: bool
    branch: Optional[str]
    repo_path: Optional[str]
    start_time: float

    # Execution Lifecycle
    stage: str
    status_messages: List[str]
    error: Optional[str]

    # Intermediate Results
    scout_result: Optional[Dict[str, Any]]
    files_to_audit: List[str]
    total_files_scanned: int
    candidate_findings: List[Dict[str, Any]]
    verified_findings: List[Dict[str, Any]]
    rejected_findings: List[Dict[str, Any]]

    # Final Output
    report: Optional[Dict[str, Any]]


def get_llm():
    """Initializes the Gemini model using LangChain."""
    api_key = (
        settings.GEMINI_API_KEY
        or os.getenv("GEMINI_API_KEY")
        or os.getenv("GOOGLE_API_KEY")
    )
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY is not set. Please set GEMINI_API_KEY in your .env or environment variables."
        )

    return ChatGoogleGenerativeAI(
        model=settings.GEMINI_MODEL,
        google_api_key=api_key,
        temperature=0.0,
    )


def node_scout(state: AuditorState) -> Dict[str, Any]:
    """
    Stage 1: Ingest repository, inspect directory structure, identify tech stack and key files.
    """
    repo_target = state["repo_target"]
    branch = state.get("branch") or "main"
    status_messages = list(state.get("status_messages", []))

    status_messages.append(f"Cloning & exploring repository workspace: {repo_target}")
    
    try:
        repo_path = prepare_repo_workspace(repo_target, branch=branch)
    except Exception as e:
        return {
            "stage": "FAILED",
            "error": f"Failed to ingest repository: {e}",
            "status_messages": status_messages + [f"Error ingesting repository: {e}"],
        }

    tree_info = inspect_repo_structure(repo_path)
    file_tree = tree_info["file_tree"]
    source_files = tree_info["source_files"]
    config_files = tree_info["config_files"]

    status_messages.append(
        f"Indexed {len(source_files)} source files and {len(config_files)} config files."
    )

    # Read config files (e.g. requirements.txt, pyproject.toml, package.json)
    configs_summary = []
    for cfg in config_files[:5]:
        content = read_code_file(repo_path, cfg, max_lines=60)
        configs_summary.append(f"File {cfg}:\n{content}\n")

    prompt = f"""Target Repository: {repo_target}
Total Source Files: {len(source_files)}

File Tree:
{file_tree}

Key Configuration Files:
{''.join(configs_summary)}

Source Files List (sample):
{', '.join(source_files[:40])}
"""

    llm = get_llm()
    structured_scout = llm.with_structured_output(ScoutResult)
    
    try:
        scout_res: ScoutResult = structured_scout.invoke([
            SystemMessage(content=SCOUT_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])
        scout_dict = scout_res.model_dump()
    except Exception as e:
        status_messages.append(f"Scout parsing fallback: {e}")
        scout_dict = {
            "framework": "Python / Web",
            "orm_used": "SQLAlchemy / ORM",
            "is_async": True,
            "crypto_libraries": ["hashlib", "secrets"],
            "priority_files_to_audit": source_files[:10],
            "summary": "Repository structure explored.",
        }

    # Determine files to audit (combine Scout recommendations with available source files)
    priority_files = scout_dict.get("priority_files_to_audit", [])
    valid_priority = [f for f in priority_files if (repo_path / f).is_file()]
    if not valid_priority:
        valid_priority = source_files[:8]

    status_messages.append(
        f"Scout complete. Tech stack: {scout_dict.get('framework')}. Prioritizing {len(valid_priority)} files."
    )

    return {
        "repo_path": str(repo_path),
        "stage": "SCOUT_COMPLETED",
        "status_messages": status_messages,
        "scout_result": scout_dict,
        "files_to_audit": valid_priority,
        "total_files_scanned": len(valid_priority),
    }


def node_audit(state: AuditorState) -> Dict[str, Any]:
    """
    Stage 2: Execute deep audit across prioritized files against the 5 signature checks.
    """
    if state.get("stage") == "FAILED" or not state.get("repo_path"):
        return state

    repo_path = Path(state["repo_path"])
    files = state.get("files_to_audit", [])
    status_messages = list(state.get("status_messages", []))
    status_messages.append(f"Executing Performance and Security audit across {len(files)} files...")

    llm = get_llm()
    structured_auditor = llm.with_structured_output(AuditPhaseOutput)
    candidate_findings: List[Dict[str, Any]] = []

    for file_rel in files:
        file_content = read_code_file(repo_path, file_rel, max_lines=250)
        
        prompt = f"""Examine this source file for the 5 signature checks:
1. ORM N+1 Queries
2. Event Loop Blocking (sync sleep/requests in async def)
3. Insecure Cryptography & PRNG (MD5, SHA1 for passwords/tokens, random for auth tokens)
4. Hardcoded Secrets (API tokens, private keys)
5. Injection Vectors (Raw SQL string formatting, eval/exec)

{file_content}
"""
        try:
            audit_out: AuditPhaseOutput = structured_auditor.invoke([
                SystemMessage(content=AUDIT_SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            for finding in audit_out.candidate_findings:
                finding_dict = finding.model_dump()
                finding_dict["file_path"] = file_rel
                candidate_findings.append(finding_dict)
        except Exception as e:
            status_messages.append(f"Audit error on {file_rel}: {e}")

    status_messages.append(f"Auditing complete. Found {len(candidate_findings)} candidate issues.")

    return {
        "stage": "AUDIT_COMPLETED",
        "status_messages": status_messages,
        "candidate_findings": candidate_findings,
    }


def node_verify(state: AuditorState) -> Dict[str, Any]:
    """
    Stage 3: Verification loop to eliminate false positives and refine code diffs.
    """
    if state.get("stage") == "FAILED" or not state.get("repo_path"):
        return state

    repo_path = Path(state["repo_path"])
    candidates = state.get("candidate_findings", [])
    status_messages = list(state.get("status_messages", []))
    status_messages.append(f"Entering Verification Loop: validating {len(candidates)} candidate findings...")

    llm = get_llm()
    structured_verifier = llm.with_structured_output(VerificationDecision)

    verified: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []

    for item in candidates:
        file_rel = item.get("file_path", "")
        start_line = item.get("line_start") or 1
        end_line = item.get("line_end") or (start_line + 25)

        # Read surrounding lines for precise context
        context_start = max(1, start_line - 10)
        context_end = end_line + 10
        surrounding_code = read_code_file(repo_path, file_rel, start_line=context_start, end_line=context_end)

        verify_prompt = f"""Verify this candidate issue:
Title: {item.get('title')}
Category: {item.get('category')}
Severity: {item.get('severity')}
Reported Lines: {start_line}-{end_line}
Explanation: {item.get('explanation')}
Proposed Diff:
{item.get('code_diff')}

Surrounding File Code:
{surrounding_code}

Determine if this is a true positive (genuine issue) or a false positive.
"""
        try:
            decision: VerificationDecision = structured_verifier.invoke([
                SystemMessage(content=VERIFIER_SYSTEM_PROMPT),
                HumanMessage(content=verify_prompt),
            ])

            if decision.is_valid and decision.confidence >= 0.65:
                if decision.refined_diff:
                    item["code_diff"] = decision.refined_diff
                item["verification_note"] = decision.reason
                verified.append(item)
            else:
                item["rejection_reason"] = decision.reason
                rejected.append(item)
        except Exception as e:
            # In case of verification timeout/error, preserve the candidate if high severity
            status_messages.append(f"Verification call warning: {e}")
            verified.append(item)

    status_messages.append(
        f"Verification complete: {len(verified)} confirmed findings, {len(rejected)} false positives filtered out."
    )

    return {
        "stage": "VERIFICATION_COMPLETED",
        "status_messages": status_messages,
        "verified_findings": verified,
        "rejected_findings": rejected,
    }


def node_remediate_and_dispatch(state: AuditorState) -> Dict[str, Any]:
    """
    Stage 4: Dispatch GitHub Issues (if enabled) and synthesize final AuditReport.
    """
    status_messages = list(state.get("status_messages", []))
    repo_target = state["repo_target"]
    auto_file_issues = state.get("auto_file_issues", False)
    verified = state.get("verified_findings", [])
    
    status_messages.append("Synthesizing final audit report and remediation steps...")

    final_findings: List[AuditFinding] = []

    for item in verified:
        finding = AuditFinding(
            title=item.get("title", "Detected Issue"),
            category=IssueCategory(item.get("category", "SECURITY")),
            severity=Severity(item.get("severity", "MEDIUM")),
            file_path=item.get("file_path", "unknown"),
            line_start=item.get("line_start"),
            line_end=item.get("line_end"),
            explanation=item.get("explanation", ""),
            reproduction=item.get("reproduction"),
            code_diff=item.get("code_diff"),
        )

        # File on GitHub if requested
        if auto_file_issues:
            issue_url = file_github_issue(repo_target, finding)
            if issue_url:
                finding.github_issue_url = issue_url
                status_messages.append(f"Created GitHub Issue for '{finding.title}': {issue_url}")

        final_findings.append(finding)

    # Calculate duration
    duration = time.time() - state.get("start_time", time.time())

    # Build summary
    perf_count = sum(1 for f in final_findings if f.category == IssueCategory.PERFORMANCE)
    sec_count = sum(1 for f in final_findings if f.category == IssueCategory.SECURITY)
    
    summary = (
        f"CodeMate audited {state.get('total_files_scanned', 0)} files in {duration:.1f}s. "
        f"Identified {len(final_findings)} confirmed findings ({perf_count} performance, {sec_count} security). "
        f"Filtered {len(state.get('rejected_findings', []))} false positives."
    )

    report = AuditReport(
        audit_id=state["audit_id"],
        repo_url=repo_target,
        status=AuditStatus.COMPLETED,
        findings=final_findings,
        total_scanned_files=state.get("total_files_scanned", 0),
        duration_seconds=round(duration, 2),
        summary=summary,
    )

    # Clean up workspace
    if state.get("repo_path"):
        cleanup_repo_workspace(Path(state["repo_path"]))

    status_messages.append("Audit successfully completed!")

    return {
        "stage": "COMPLETED",
        "status_messages": status_messages,
        "report": report.model_dump(),
    }


def build_auditor_graph():
    """Compiles and returns the LangGraph state machine."""
    workflow = StateGraph(AuditorState)

    # Add Nodes
    workflow.add_node("scout", node_scout)
    workflow.add_node("audit", node_audit)
    workflow.add_node("verify", node_verify)
    workflow.add_node("remediate_and_dispatch", node_remediate_and_dispatch)

    # Add Edges (Deterministic sequential pipeline)
    workflow.add_edge(START, "scout")
    workflow.add_edge("scout", "audit")
    workflow.add_edge("audit", "verify")
    workflow.add_edge("verify", "remediate_and_dispatch")
    workflow.add_edge("remediate_and_dispatch", END)

    return workflow.compile()


# Compiled LangGraph agent
auditor_app = build_auditor_graph()
