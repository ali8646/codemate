import pytest
from app.agent.tools.github_tools import parse_repo_owner_and_name, format_github_issue_body
from app.schemas.audit import AuditFinding, Severity, IssueCategory


def test_parse_github_url():
    owner, repo = parse_repo_owner_and_name("https://github.com/ali8646/codemate")
    assert owner == "ali8646"
    assert repo == "codemate"

    owner, repo = parse_repo_owner_and_name("ali8646/codemate.git")
    assert owner == "ali8646"
    assert repo == "codemate"


def test_format_github_issue_body():
    finding = AuditFinding(
        title="ORM N+1 Query in GET /users",
        category=IssueCategory.PERFORMANCE,
        severity=Severity.HIGH,
        file_path="app/routes.py",
        line_start=15,
        line_end=22,
        explanation="Looping over records triggers repeated SELECT queries.",
        code_diff="- users = db.query(User).all()\n+ users = db.query(User).options(joinedload(User.profile)).all()",
    )
    body = format_github_issue_body(finding, "ali8646/codemate")
    assert "[HIGH] ORM N+1 Query in GET /users" in body
    assert "`app/routes.py` (L15-L22)" in body
    assert "Proposed Remediation Diff" in body
    assert "joinedload" in body
