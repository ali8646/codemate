import time
import uuid
from typing import Dict, Optional
from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.agent.graph import auditor_app, AuditorState
from app.schemas.audit import AuditRequest, AuditReport, AuditStatus


router = APIRouter(prefix="/audit", tags=["Audit"])

# In-memory store for audit runs (can be upgraded to Redis/PostgreSQL)
audit_store: Dict[str, Dict] = {}


def run_audit_background(audit_id: str, request: AuditRequest):
    """Executes the LangGraph audit pipeline in the background."""
    initial_state: AuditorState = {
        "audit_id": audit_id,
        "repo_target": request.repo_url,
        "auto_file_issues": request.auto_file_issues,
        "branch": request.branch,
        "repo_path": None,
        "start_time": time.time(),
        "stage": "INITIALIZING",
        "status_messages": ["Audit job queued and started."],
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
        "stage": "INITIALIZING",
        "status_messages": ["Audit job queued and started."],
        "report": None,
        "error": None,
    }

    try:
        # Stream or invoke the LangGraph pipeline
        for output in auditor_app.stream(initial_state):
            for node_name, node_state in output.items():
                audit_store[audit_id]["stage"] = node_state.get("stage", node_name)
                if node_state.get("status_messages"):
                    audit_store[audit_id]["status_messages"] = node_state["status_messages"]
                if node_state.get("report"):
                    audit_store[audit_id]["report"] = node_state["report"]
                if node_state.get("error"):
                    audit_store[audit_id]["error"] = node_state["error"]

        if audit_store[audit_id].get("error"):
            audit_store[audit_id]["status"] = AuditStatus.FAILED
        else:
            audit_store[audit_id]["status"] = AuditStatus.COMPLETED

    except Exception as e:
        audit_store[audit_id]["status"] = AuditStatus.FAILED
        audit_store[audit_id]["error"] = str(e)
        audit_store[audit_id]["status_messages"].append(f"Fatal error during audit: {e}")


@router.post("", summary="Start a new repository audit")
async def start_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """
    Submits a repository URL for autonomous performance and security auditing.
    Runs asynchronously and returns an audit_id.
    """
    audit_id = str(uuid.uuid4())
    audit_store[audit_id] = {
        "status": AuditStatus.PENDING,
        "stage": "PENDING",
        "status_messages": ["Audit registered. Initializing..."],
        "report": None,
        "error": None,
    }
    background_tasks.add_task(run_audit_background, audit_id, request)
    return {
        "audit_id": audit_id,
        "repo_url": request.repo_url,
        "status": AuditStatus.PENDING,
        "message": "Audit started successfully in background.",
    }


@router.get("/{audit_id}/status", summary="Check audit status and live stage progress")
async def get_audit_status(audit_id: str):
    """Retrieves live execution status and agent logs for an audit job."""
    if audit_id not in audit_store:
        raise HTTPException(status_code=404, detail="Audit ID not found.")
    return {
        "audit_id": audit_id,
        "status": audit_store[audit_id]["status"],
        "stage": audit_store[audit_id]["stage"],
        "status_messages": audit_store[audit_id]["status_messages"],
        "error": audit_store[audit_id].get("error"),
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
            "message": "Audit is still in progress.",
        }

    return data["report"]
