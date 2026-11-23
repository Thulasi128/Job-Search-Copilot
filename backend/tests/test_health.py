"""Unit and integration tests for the /health endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(async_client: AsyncClient):
    """Verify that GET /health returns HTTP 200 with expected status fields."""
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] in ("connected", "disconnected")
    assert data["llm_provider"] == "gemini"

