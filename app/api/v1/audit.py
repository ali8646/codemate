import logging
import time
import uuid
from typing import Dict, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.agent.graph import auditor_app, AuditorState
from app.schemas.audit import AuditRequest, AuditReport, AuditStatus

logger = logging.getLogger("codemate.audit")
logging.basicConfig(level=logging.INFO)

router = APIRouter(prefix="/audit", tags=["Audit"])

# In-memory store for audit runs
audit_store: Dict[str, Dict] = {}


def run_audit_background(audit_id: str, request: AuditRequest):
    """Executes the LangGraph audit pipeline in the background with granular progress tracking."""
    logger.info(f"[{audit_id}] Starting audit background task for {request.repo_url}")
    
    initial_state: AuditorState = {
        "audit_id": audit_id,
        "repo_target": request.repo_url,
        "auto_file_issues": request.auto_file_issues,
        "branch": request.branch,
        "repo_path": None,
        "start_time": time.time(),
        "stage": "SCOUTING",
        "status_messages": [
            "Audit initialized.",
            f"Ingesting repository target: {request.repo_url}",
        ],
        "error": None,
        "scout_result": None,
        "files_to_audit": [],
        "total_files_scanned": 0,
        "candidate_findings": [],
        "verified_findings": [],
        "rejected_findings": [],
        "report": None,
    }

    audit_store[audit_id] = {
        "status": AuditStatus.IN_PROGRESS,
        "stage": "SCOUTING",
        "progress": 15,
        "status_messages": [
            "Audit initialized.",
            f"Ingesting repository target: {request.repo_url}",
            "Scanning file tree and analyzing configuration files with Gemini...",
        ],
        "report": None,
        "error": None,
    }

    stage_progress_map = {
        "scout": (35, "AUDITING", "Scout complete. Starting performance and security code analysis..."),
        "audit": (70, "VERIFYING", "Code analysis complete. Entering verification loop to eliminate false positives..."),
        "verify": (90, "REMEDIATING", "Verification complete. Generating unified diffs and audit report..."),
        "remediate_and_dispatch": (100, "COMPLETED", "Audit finished successfully."),
    }

    try:
        for output in auditor_app.stream(initial_state):
            # Check for early cancellation
            if audit_store.get(audit_id, {}).get("status") == AuditStatus.CANCELLED:
                logger.info(f"[{audit_id}] Audit cancelled by user request.")
                audit_store[audit_id]["status_messages"].append("Audit stopped by user.")
                break

            for node_name, node_state in output.items():
                logger.info(f"[{audit_id}] Node completed: {node_name}")
                
                # Check cancellation again
                if audit_store.get(audit_id, {}).get("status") == AuditStatus.CANCELLED:
                    break
                
                # Update status and progress
                if node_name in stage_progress_map:
                    prog, next_stage, next_msg = stage_progress_map[node_name]
                    audit_store[audit_id]["progress"] = prog
                    audit_store[audit_id]["stage"] = next_stage
                    audit_store[audit_id]["status_messages"].append(next_msg)

                # Merge latest status messages from agent state
                if node_state.get("status_messages"):
                    for msg in node_state["status_messages"]:
                        if msg not in audit_store[audit_id]["status_messages"]:
                            audit_store[audit_id]["status_messages"].append(msg)

                if node_state.get("report"):
                    audit_store[audit_id]["report"] = node_state["report"]
                if node_state.get("error"):
                    audit_store[audit_id]["error"] = node_state["error"]

        if audit_store[audit_id].get("error"):
            audit_store[audit_id]["status"] = AuditStatus.FAILED
            audit_store[audit_id]["progress"] = 100
        else:
            audit_store[audit_id]["status"] = AuditStatus.COMPLETED
            audit_store[audit_id]["progress"] = 100
            audit_store[audit_id]["stage"] = "COMPLETED"

    except Exception as e:
        logger.error(f"[{audit_id}] Fatal audit execution error: {e}", exc_info=True)
        audit_store[audit_id]["status"] = AuditStatus.FAILED
        audit_store[audit_id]["progress"] = 100
        audit_store[audit_id]["error"] = str(e)
        audit_store[audit_id]["status_messages"].append(f"Execution error: {e}")


@router.post("", summary="Start a new repository audit")
async def start_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """
    Submits a repository URL for autonomous performance and security auditing.
    Runs asynchronously and returns an audit_id.
    """
    audit_id = str(uuid.uuid4())
    audit_store[audit_id] = {
        "status": AuditStatus.PENDING,
        "stage": "INITIALIZING",
        "progress": 5,
        "status_messages": ["Audit queued. Initializing agent pipeline..."],
        "report": None,
        "error": None,
    }
    background_tasks.add_task(run_audit_background, audit_id, request)
    return {
        "audit_id": audit_id,
        "repo_url": request.repo_url,
        "status": AuditStatus.PENDING,
        "progress": 5,
        "message": "Audit started successfully in background.",
    }


@router.post("/{audit_id}/cancel", summary="Cancel an in-progress audit")
async def cancel_audit(audit_id: str):
    """Signals an ongoing audit job to halt execution immediately."""
    if audit_id not in audit_store:
        raise HTTPException(status_code=404, detail="Audit ID not found.")
    
    current_status = audit_store[audit_id]["status"]
    if current_status in {AuditStatus.COMPLETED, AuditStatus.FAILED, AuditStatus.CANCELLED}:
        return {"audit_id": audit_id, "status": current_status, "message": "Audit is not active."}

    audit_store[audit_id]["status"] = AuditStatus.CANCELLED
    audit_store[audit_id]["stage"] = "CANCELLED"
    audit_store[audit_id]["status_messages"].append("Cancellation requested. Stopping agent...")
    return {"audit_id": audit_id, "status": AuditStatus.CANCELLED, "message": "Audit cancelled successfully."}


@router.get("/{audit_id}/status", summary="Check audit status and live stage progress")
async def get_audit_status(audit_id: str):
    """Retrieves live execution status, progress percentage, and agent logs."""
    if audit_id not in audit_store:
        raise HTTPException(status_code=404, detail="Audit ID not found.")
    data = audit_store[audit_id]
    return {
        "audit_id": audit_id,
        "status": data["status"],
        "stage": data["stage"],
        "progress": data.get("progress", 0),
        "status_messages": data["status_messages"],
        "error": data.get("error"),
    }


@router.get("/{audit_id}/report", summary="Retrieve final audit report and verified findings")
async def get_audit_report(audit_id: str):
    """Retrieves the completed AuditReport schema containing findings and diffs."""
    if audit_id not in audit_store:
        raise HTTPException(status_code=404, detail="Audit ID not found.")
    
    data = audit_store[audit_id]
    if data["status"] == AuditStatus.FAILED:
        raise HTTPException(status_code=500, detail=f"Audit failed: {data.get('error')}")
    if data["status"] != AuditStatus.COMPLETED or not data.get("report"):
        return {
            "audit_id": audit_id,
            "status": data["status"],
            "progress": data.get("progress", 0),
            "message": "Audit is still in progress.",
        }

    return data["report"]
