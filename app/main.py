from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.v1.audit import router as audit_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Autonomous Repository Auditor powered by Google Gemini, LangGraph, and FastAPI.",
)

# Enable CORS for local development and dashboard communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Routers
app.include_router(audit_router, prefix="/api/v1")


@app.get("/", response_class=HTMLResponse, tags=["Dashboard"])
async def dashboard():
    """Serves the interactive CodeMate web dashboard."""
    template_path = Path(__file__).parent / "templates" / "index.html"
    if template_path.is_file():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>CodeMate Auditor</h1><p>Visit <a href='/docs'>/docs</a> for API documentation.</p>"
    )


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "gemini_model": settings.GEMINI_MODEL,
    }
