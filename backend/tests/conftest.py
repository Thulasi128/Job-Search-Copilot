"""Pytest configuration and shared test fixtures."""

import os
from unittest.mock import AsyncMock
import mongomock_motor
import pytest
from httpx import ASGITransport, AsyncClient

# Ensure test environment settings are configured before importing app
os.environ["LLM_PROVIDER"] = "gemini"
os.environ["LLM_MODEL"] = "gemini-2.5-flash"
os.environ["GEMINI_API_KEY"] = "mock_key_for_testing"
os.environ["MONGO_URI"] = "mongodb://localhost:27017"
os.environ["MONGO_DB_NAME"] = "job_search_copilot_test"

import backend.database as db_module
from backend.main import app


@pytest.fixture(autouse=True)
def mock_mongo_db(monkeypatch):
    """Fixture providing isolated in-memory MongoDB mock client for fast, deterministic testing."""
    mock_client = mongomock_motor.AsyncMongoMockClient()
    mock_db = mock_client["job_search_copilot_test"]

    monkeypatch.setattr(db_module, "_mongo_client", mock_client)
    monkeypatch.setattr(db_module, "get_db", lambda: mock_db)
    monkeypatch.setattr(db_module, "ping_db", AsyncMock(return_value=True))
    return mock_db


@pytest.fixture
async def async_client():
    """Fixture providing an async HTTP client bound to the FastAPI ASGI application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
