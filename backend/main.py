"""FastAPI application entrypoint for Job-Search Copilot."""

from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.api.export import router as export_router
from backend.api.jobs import router as jobs_router
from backend.api.logs import router as logs_router
from backend.api.profile import router as profile_router
from backend.config import get_settings
from backend.database import close_db, connect_db, ping_db
from backend.workflow.checkpointer import close_checkpointer, init_checkpointer_and_graph
from backend.workflow.runner import recover_interrupted_jobs


class HealthResponse(BaseModel):
    """Health response payload model."""

    status: str
    database: str
    llm_provider: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Lifespan context manager to handle application startup and shutdown."""
    await connect_db()
    # Initialize SQLite checkpointer and compiled workflow graph
    await init_checkpointer_and_graph()
    # Startup sweep: recover any jobs interrupted mid-run by a restart
    await recover_interrupted_jobs()
    yield
    await close_checkpointer()
    await close_db()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title="Job-Search Copilot API",
        description="Local multi-agent system to streamline internship applications.",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Enable CORS for local development and frontend access
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Mount routers
    app.include_router(profile_router)
    app.include_router(jobs_router)
    app.include_router(logs_router)
    app.include_router(export_router)

    @app.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health() -> HealthResponse:
        """Health check endpoint reporting API, database, and LLM provider status.

        Returns:
            HealthResponse: System operational status.
        """
        db_alive = await ping_db()
        settings = get_settings()
        return HealthResponse(
            status="ok",
            database="connected" if db_alive else "disconnected",
            llm_provider=settings.LLM_PROVIDER,
        )

    return app


app = create_app()
