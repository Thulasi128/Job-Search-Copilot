"""Tests for provider-agnostic LLM wrapper, retry with backoff, and factory."""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from pydantic import BaseModel

from backend.llm.client import (
    GeminiClient,
    OllamaClient,
    OpenAIClient,
    get_llm_client,
    is_retryable_error,
)


class SampleSchema(BaseModel):
    """Sample Pydantic model for structured output testing."""

    summary: str
    score: int


class CustomAPIError(Exception):
    """Mock exception representing an API error with code."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


def test_is_retryable_error_classification():
    """Verify is_retryable_error correctly distinguishes 429/5xx from 4xx."""
    assert is_retryable_error(CustomAPIError("Rate limit exceeded", 429)) is True
    assert is_retryable_error(CustomAPIError("Internal server error", 500)) is True
    assert is_retryable_error(CustomAPIError("Bad gateway", 502)) is True
    assert is_retryable_error(CustomAPIError("Service unavailable", 503)) is True
    assert is_retryable_error(Exception("429 Resource Exhausted")) is True

    # Non-retryable errors
    assert is_retryable_error(CustomAPIError("Invalid API key", 400)) is False
    assert is_retryable_error(CustomAPIError("Unauthorized", 401)) is False
    assert is_retryable_error(CustomAPIError("Not found", 404)) is False


@pytest.mark.asyncio
async def test_gemini_client_retries_on_429_with_backoff():
    """Verify GeminiClient retries transient 429 errors up to max_retries and succeeds."""
    client = GeminiClient(api_key="test_key", model_name="gemini-test-model", max_retries=4)

    mock_response = MagicMock()
    mock_response.text = "Recovered after retry!"

    mock_genai_client = MagicMock()
    # Fails twice with 429, then succeeds on 3rd attempt
    mock_genai_client.aio.models.generate_content = AsyncMock(
        side_effect=[
            CustomAPIError("Resource exhausted: 429", 429),
            CustomAPIError("Temporary rate limit: 429", 429),
            mock_response,
        ]
    )

    with patch.object(client, "_get_client", return_value=mock_genai_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        result = await client.generate_text(prompt="Test prompt")
        assert result == "Recovered after retry!"
        assert mock_genai_client.aio.models.generate_content.await_count == 3
        assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_gemini_client_fails_immediately_on_non_retryable_error():
    """Verify GeminiClient does NOT retry permanent errors (e.g. 400 API_KEY_INVALID)."""
    client = GeminiClient(api_key="bad_key", model_name="gemini-test-model", max_retries=4)

    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock(
        side_effect=CustomAPIError("API key not valid", 400)
    )

    with patch.object(client, "_get_client", return_value=mock_genai_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(CustomAPIError, match="API key not valid"):
            await client.generate_text(prompt="Test prompt")
        assert mock_genai_client.aio.models.generate_content.await_count == 1
        mock_sleep.assert_not_called()


@pytest.mark.asyncio
async def test_gemini_client_exhausts_retries_on_persistent_503():
    """Verify GeminiClient raises after max_retries attempts if error persists."""
    client = GeminiClient(api_key="test_key", model_name="gemini-test-model", max_retries=3)

    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock(
        side_effect=CustomAPIError("Service Unavailable", 503)
    )

    with patch.object(client, "_get_client", return_value=mock_genai_client), patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        with pytest.raises(CustomAPIError, match="Service Unavailable"):
            await client.generate_text(prompt="Test prompt")
        assert mock_genai_client.aio.models.generate_content.await_count == 3
        assert mock_sleep.await_count == 2


@pytest.mark.asyncio
async def test_gemini_client_generate_text_mocked():
    """Verify GeminiClient.generate_text invokes client and returns text."""
    client = GeminiClient(api_key="test_key", model_name="gemini-test-model")

    mock_response = MagicMock()
    mock_response.text = "Hello, world!"

    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch.object(client, "_get_client", return_value=mock_genai_client):
        result = await client.generate_text(
            prompt="Test prompt",
            system_instruction="Be concise",
        )
        assert result == "Hello, world!"
        mock_genai_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_client_generate_json_mocked():
    """Verify GeminiClient.generate_json parses structured output into Pydantic schema."""
    client = GeminiClient(api_key="test_key", model_name="gemini-test-model")

    mock_response = MagicMock()
    mock_response.text = '{"summary": "Qualified candidate", "score": 85}'

    mock_genai_client = MagicMock()
    mock_genai_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

    with patch.object(client, "_get_client", return_value=mock_genai_client):
        result = await client.generate_json(
            prompt="Analyze candidate",
            schema=SampleSchema,
            system_instruction="Return JSON matching schema",
        )
        assert isinstance(result, SampleSchema)
        assert result.summary == "Qualified candidate"
        assert result.score == 85


@pytest.mark.asyncio
async def test_openai_and_ollama_stubs_raise_not_implemented():
    """Verify OpenAI and Ollama client stubs raise informative NotImplementedError."""
    openai_client = OpenAIClient(api_key="sk-test", model_name="gpt-4o")
    with pytest.raises(NotImplementedError, match="OpenAI provider is not implemented in v1"):
        await openai_client.generate_text("test")

    with pytest.raises(NotImplementedError, match="OpenAI provider is not implemented in v1"):
        await openai_client.generate_json("test", SampleSchema)

    ollama_client = OllamaClient(base_url="http://localhost:11434", model_name="llama3")
    with pytest.raises(NotImplementedError, match="Ollama provider is not implemented in v1"):
        await ollama_client.generate_text("test")

    with pytest.raises(NotImplementedError, match="Ollama provider is not implemented in v1"):
        await ollama_client.generate_json("test", SampleSchema)


def test_get_llm_client_factory():
    """Verify get_llm_client instantiates correct client types and handles errors."""
    gemini = get_llm_client(provider="gemini", model="gemini-custom")
    assert isinstance(gemini, GeminiClient)
    assert gemini.model_name == "gemini-custom"

    openai = get_llm_client(provider="openai", model="gpt-4o")
    assert isinstance(openai, OpenAIClient)

    ollama = get_llm_client(provider="ollama", model="llama3")
    assert isinstance(ollama, OllamaClient)

    with pytest.raises(ValueError, match="Unsupported LLM_PROVIDER"):
        get_llm_client(provider="unsupported_provider")
