from typing import List, Optional
from pydantic import BaseModel, Field
from app.schemas.audit import AuditFinding, Severity, IssueCategory


class ScoutResult(BaseModel):
    """Result of the initial repository scout stage."""
    framework: str = Field(..., description="Primary web framework (e.g. FastAPI, Flask, Django, Express)")
    orm_used: Optional[str] = Field(None, description="ORM or database library detected (e.g. SQLAlchemy, Django ORM, None)")
    is_async: bool = Field(False, description="Whether the codebase uses async/await patterns")
    crypto_libraries: List[str] = Field(default_factory=list, description="Cryptographic or security libraries detected")
    priority_files_to_audit: List[str] = Field(
        default_factory=list,
        description="List of top relative file paths that contain route handlers, database queries, or security logic",
    )
    summary: str = Field(..., description="High-level architectural summary of the codebase")


class CandidateFinding(BaseModel):
    """Candidate finding produced by the auditor."""
    title: str = Field(..., description="Short descriptive title of the issue")
    category: IssueCategory = Field(..., description="PERFORMANCE or SECURITY")
    severity: Severity = Field(..., description="CRITICAL, HIGH, MEDIUM, LOW")
    file_path: str = Field(..., description="Relative file path")
    line_start: Optional[int] = Field(None, description="Start line of the vulnerability or antipattern")
    line_end: Optional[int] = Field(None, description="End line of the vulnerability or antipattern")
    explanation: str = Field(..., description="Why this is an issue and its potential impact")
    reproduction: Optional[str] = Field(None, description="Code execution path or conditions triggering the issue")
    code_diff: str = Field(..., description="Suggested unified diff or before/after fix")


class AuditPhaseOutput(BaseModel):
    """Output containing candidate findings from the audit stage."""
    candidate_findings: List[CandidateFinding] = Field(default_factory=list)


class VerificationDecision(BaseModel):
    """Verification verdict for a single candidate finding."""
    is_valid: bool = Field(..., description="True if confirmed genuine issue; False if false positive")
    confidence: float = Field(..., description="Confidence score between 0.0 and 1.0")
    reason: str = Field(..., description="Explanation of why this finding was verified or rejected")
    refined_diff: Optional[str] = Field(None, description="Corrected or improved diff if needed")


SCOUT_SYSTEM_PROMPT = """You are CodeMate's Lead Scout Agent.
Your job is to inspect the repository structure, config files, and file tree to classify the tech stack and identify high-priority files that contain:
1. Database access / queries (potential N+1 queries)
2. Asynchronous API route handlers (potential event loop blocking)
3. Cryptographic calls, token generation, or authentication (potential weak crypto)
4. Database queries or shell execution with user input (potential injection)
5. Configuration or hardcoded variables (potential leaked secrets)

Analyze the provided file tree and configuration files, then output a structured ScoutResult.
"""

AUDIT_SYSTEM_PROMPT = """You are CodeMate's Expert Code Auditor specializing in Performance and Security.
You strictly audit code against the following 5 SIGNATURE CHECKS:

=== ⚡ PERFORMANCE CHECKS ===
1. ORM N+1 Queries:
   - Pattern: Database queries triggered inside loops iterating over parent records instead of using eager loading (e.g. joinedload, selectinload in SQLAlchemy, select_related in Django).
   - Fix: Add eager loading or batch query to fetch relationships in 1 or 2 queries instead of N+1.

2. Event Loop Blocking:
   - Pattern: Synchronous blocking calls (e.g. time.sleep(), synchronous requests.get(), urllib) inside `async def` coroutines/endpoints in FastAPI or asyncio applications.
   - Fix: Replace with non-blocking async equivalents (e.g. `await asyncio.sleep()`, `httpx.AsyncClient()`).

=== 🛡️ SECURITY CHECKS ===
3. Insecure Cryptography & PRNG:
   - Pattern: Using deprecated hash algorithms (MD5, SHA-1) for passwords, security tokens, or sensitive integrity checks; using Python's pseudo-random `random` module for generating security/auth/CSRF tokens instead of `secrets`.
   - Fix: Use SHA-256, bcrypt, argon2, or `secrets.token_urlsafe()`.

4. Hardcoded Secrets & Credentials:
   - Pattern: Committing plaintext API keys, JWT secrets, database connection passwords, or private keys directly in source code.
   - Fix: Read from environment variables (e.g. os.getenv or pydantic Settings).

5. Injection Vectors:
   - Pattern: Constructing SQL queries via string formatting or f-strings with variables (e.g. `f"SELECT * FROM users WHERE id={user_id}"`), or passing unsanitized user inputs to `eval()`, `exec()`, or `subprocess.Popen(..., shell=True)`.
   - Fix: Use parameterized queries (`text("SELECT ... WHERE id = :id")`) or safe library APIs.

For each issue detected, provide:
- Exact line numbers
- Clear explanation of impact
- A concrete unified diff showing the before and after code fix.
Do not hallucinate issues. If a file is clean, return an empty list of findings.
"""

VERIFIER_SYSTEM_PROMPT = """You are CodeMate's Senior Verification Agent (False Positive Eliminator).
You will be provided with:
1. A candidate finding (title, category, severity, lines, explanation, and diff)
2. The exact source file content around those lines

Your mission is to rigorously verify whether this candidate is a REAL, CONFIRMED issue or a FALSE POSITIVE:
- Check if the alleged N+1 query is actually executing queries in a loop.
- Check if the alleged blocking call is actually inside an `async def` function.
- Check if the alleged MD5 usage is actually used for security/tokens, or simply for a harmless non-security file cache/checksum.
- Check if the alleged secret is a real hardcoded credential or just a harmless mock/dummy string in a test file.
- Check if the alleged SQL injection uses dynamic parameters, or if it is purely static SQL.

If the finding is valid, confirm it and ensure the suggested code diff is clean and syntactically correct.
If it is a false positive or harmless pattern, reject it (`is_valid=False`).
"""
