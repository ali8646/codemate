from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class IssueCategory(str, Enum):
    PERFORMANCE = "PERFORMANCE"
    SECURITY = "SECURITY"
    CODE_QUALITY = "CODE_QUALITY"


class AuditFinding(BaseModel):
    """Structured audit finding."""
    title: str = Field(..., description="Short summary of the issue")
    category: IssueCategory = Field(..., description="Category of the finding")
    severity: Severity = Field(..., description="Severity level")
    file_path: str = Field(..., description="Relative path to the affected file")
    line_start: Optional[int] = Field(None, description="Starting line number")
    line_end: Optional[int] = Field(None, description="Ending line number")
    explanation: str = Field(..., description="Technical explanation of the vulnerability or performance issue")
    reproduction: Optional[str] = Field(None, description="Steps or context reproducing the issue")
    code_diff: Optional[str] = Field(None, description="Suggested unified diff or before/after code fix")
    github_issue_url: Optional[str] = Field(None, description="URL of created GitHub issue if filed")


class AuditRequest(BaseModel):
    """Request payload to initiate a repository audit."""
    repo_url: str = Field(..., description="URL of the GitHub repository (e.g. https://github.com/owner/repo)")
    auto_file_issues: bool = Field(False, description="Whether to automatically create GitHub issues for confirmed findings")
    branch: Optional[str] = Field("main", description="Git branch to audit")


class AuditStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AuditReport(BaseModel):
    """Final audit report."""
    audit_id: str
    repo_url: str
    status: AuditStatus
    findings: List[AuditFinding] = []
    total_scanned_files: int = 0
    duration_seconds: float = 0.0
    summary: str = ""
