"""Provider-agnostic LLM client wrapper supporting Google Gemini, OpenAI, and Ollama."""

from abc import ABC, abstractmethod
import asyncio
import logging
import random
from typing import Any, Optional, Type, TypeVar
from pydantic import BaseModel
from backend.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def is_retryable_error(exc: Exception) -> bool:
    """Detect whether exception indicates HTTP 429 (rate limit) or 5xx (transient server error)."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if code is not None:
        try:
            code_int = int(code)
            if code_int == 429 or 500 <= code_int < 600:
                return True
        except (ValueError, TypeError):
            pass

    msg = str(exc).lower()
    if any(k in msg for k in ("429", "resource_exhausted", "rate limit", "quota")):
        return True
    if any(k in msg for k in ("500", "502", "503", "504", "internal server error", "unavailable", "bad gateway")):
        return True
    return False


async def retry_with_backoff(
    coro_func,
    max_tries: int = 4,
    base_delay: float = 0.5,
):
    """Execute coroutine with exponential backoff and randomized jitter for 429 and 5xx errors."""
    for attempt in range(1, max_tries + 1):
        try:
            return await coro_func()
        except Exception as exc:
            if attempt >= max_tries or not is_retryable_error(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1)) + random.uniform(0.01, 0.1 * base_delay)
            logger.warning(
                "LLM call encountered retryable error (%s, attempt %d/%d). Retrying in %.2fs...",
                exc,
                attempt,
                max_tries,
                delay,
            )
            await asyncio.sleep(delay)


def _clean_schema_for_gemini(schema_dict: dict) -> dict:
    """Recursively strip unsupported keys (e.g. additionalProperties) from schema for Gemini Developer API."""
    import copy
    cleaned = copy.deepcopy(schema_dict)

    def _clean(node):
        if isinstance(node, dict):
            node.pop("additionalProperties", None)
            for v in node.values():
                _clean(v)
        elif isinstance(node, list):
            for item in node:
                _clean(item)

    _clean(cleaned)
    return cleaned


class LLMClient(ABC):
    """Abstract base class for all LLM client implementations."""

    @abstractmethod
    async def generate_text(
        self, prompt: str, system_instruction: Optional[str] = None
    ) -> str:
        """Generate a raw text string from the given prompt.

        Args:
            prompt: User-provided input text.
            system_instruction: Optional system instruction for the LLM.

        Returns:
            str: Generated text response.
        """
        pass

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: Type[T],
        system_instruction: Optional[str] = None,
    ) -> T:
        """Generate structured JSON adhering to the provided Pydantic schema.

        Args:
            prompt: User-provided input text.
            schema: Pydantic model class defining the expected response format.
            system_instruction: Optional system instruction for the LLM.

        Returns:
            T: Parsed and validated instance of the schema model.
        """
        pass


class GeminiClient(LLMClient):
    """Google Gemini LLM client implementation using the official google-genai SDK."""

    def __init__(self, api_key: str, model_name: str, max_retries: int = 4) -> None:
        """Initialize the Gemini client with API key and model name.

        Args:
            api_key: Gemini API key.
            model_name: Configurable model name (e.g. gemini-2.5-flash).
            max_retries: Maximum attempts for transient 429/5xx errors (default 4).
        """
        if not model_name:
            raise ValueError("model_name must be specified and cannot be empty.")
        self.api_key = api_key
        self.model_name = model_name
        self.max_retries = max_retries
        self._client = None

    def _get_client(self):
        """Lazy initialization of the Google GenAI client."""
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key or None)
        return self._client

    async def generate_text(
        self, prompt: str, system_instruction: Optional[str] = None
    ) -> str:
        """Generate plain text using Gemini async API with backoff retry on 429/5xx."""
        client = self._get_client()
        from google.genai import types

        config = types.GenerateContentConfig()
        if system_instruction:
            config.system_instruction = system_instruction

        async def _call():
            return await client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )

        response = await retry_with_backoff(_call, max_tries=self.max_retries)
        return response.text or ""

    async def generate_json(
        self,
        prompt: str,
        schema: Type[T],
        system_instruction: Optional[str] = None,
    ) -> T:
        """Generate structured JSON using Gemini and validate into schema with backoff retry."""
        client = self._get_client()
        from google.genai import types

        raw_schema = schema.model_json_schema() if hasattr(schema, "model_json_schema") else schema
        cleaned_schema = _clean_schema_for_gemini(raw_schema) if isinstance(raw_schema, dict) else schema

        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=cleaned_schema,
        )
        if system_instruction:
            config.system_instruction = system_instruction

        async def _call():
            return await client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )

        response = await retry_with_backoff(_call, max_tries=self.max_retries)
        raw_text = response.text or "{}"
        return schema.model_validate_json(raw_text)


class OpenAIClient(LLMClient):
    """Stub for OpenAI provider."""

    def __init__(self, api_key: str, model_name: str) -> None:
        """Initialize OpenAI client stub."""
        self.api_key = api_key
        self.model_name = model_name

    async def generate_text(
        self, prompt: str, system_instruction: Optional[str] = None
    ) -> str:
        """Raise NotImplementedError for OpenAI text generation."""
        raise NotImplementedError("OpenAI provider is not implemented in v1.")

    async def generate_json(
        self,
        prompt: str,
        schema: Type[T],
        system_instruction: Optional[str] = None,
    ) -> T:
        """Raise NotImplementedError for OpenAI JSON generation."""
        raise NotImplementedError("OpenAI provider is not implemented in v1.")


class OllamaClient(LLMClient):
    """Stub for local Ollama provider."""

    def __init__(self, base_url: str, model_name: str) -> None:
        """Initialize Ollama client stub."""
        self.base_url = base_url
        self.model_name = model_name

    async def generate_text(
        self, prompt: str, system_instruction: Optional[str] = None
    ) -> str:
        """Raise NotImplementedError for Ollama text generation."""
        raise NotImplementedError("Ollama provider is not implemented in v1.")

    async def generate_json(
        self,
        prompt: str,
        schema: Type[T],
        system_instruction: Optional[str] = None,
    ) -> T:
        """Raise NotImplementedError for Ollama JSON generation."""
        raise NotImplementedError("Ollama provider is not implemented in v1.")


def get_llm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
) -> LLMClient:
    """Factory function returning the configured LLMClient based on application settings or overrides.

    Args:
        provider: Optional provider name ('gemini', 'openai', 'ollama').
        model: Optional model name.
        api_key: Optional API key.

    Returns:
        LLMClient: Configured provider instance.

    Raises:
        ValueError: If provider is unrecognized.
    """
    settings = get_settings()
    prov = (provider or settings.LLM_PROVIDER).lower().strip()
    mdl = model or settings.LLM_MODEL
    key = api_key or settings.GEMINI_API_KEY

    if prov == "gemini":
        return GeminiClient(
            api_key=key,
            model_name=mdl,
        )
    elif prov == "openai":
        return OpenAIClient(
            api_key=key,
            model_name=mdl,
        )
    elif prov == "ollama":
        return OllamaClient(
            base_url="http://localhost:11434",
            model_name=mdl,
        )
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER '{prov}'. Allowed values: gemini, openai, ollama."
        )
