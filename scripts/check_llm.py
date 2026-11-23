"""LLM Connectivity Probe Script.

Executes one tiny generate_text call and one generate_json call through backend/llm/client.py.
Prints success, provider, model name, and latency. NEVER prints or logs secrets (API keys).
Provides clear diagnoses for API_KEY_INVALID, model not found, and 429 rate limits.
"""

import asyncio
from pathlib import Path
import sys
import time
from typing import Optional
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_settings
from backend.llm.client import get_llm_client


class PingResponse(BaseModel):
    status: str
    message: str


def diagnose_error(exc: Exception) -> str:
    """Classify common LLM failure modes into clear human-actionable messages."""
    err_str = str(exc)
    err_lower = err_str.lower()

    if "api_key_invalid" in err_lower or "api key not valid" in err_lower or "invalid_argument" in err_lower and "api key" in err_lower:
        return (
            "DIAGNOSIS: API_KEY_INVALID\n"
            "The configured GEMINI_API_KEY was rejected by Google GenAI service.\n"
            "Action: Please update GEMINI_API_KEY in your .env file with a valid key from Google AI Studio."
        )
    if "not_found" in err_lower or "404" in err_lower or "model" in err_lower and "not found" in err_lower:
        return (
            "DIAGNOSIS: MODEL_NOT_FOUND\n"
            "The requested model name is not available or deprecated.\n"
            "Action: Check LLM_MODEL in .env (recommended: 'gemini-2.5-flash')."
        )
    if "429" in err_lower or "resource_exhausted" in err_lower or "quota" in err_lower or "rate limit" in err_lower:
        return (
            "DIAGNOSIS: RATE_LIMIT_OR_QUOTA_EXHAUSTED (429)\n"
            "The API key quota has been exhausted or is rate limited.\n"
            "Action: Wait for quota reset or switch to a different API key / project."
        )
    return f"DIAGNOSIS: UNEXPECTED_ERROR ({type(exc).__name__}): {err_str}"


async def probe_llm():
    print("=" * 70)
    print("LLM CONNECTIVITY AND HEALTH PROBE")
    print("=" * 70)

    settings = get_settings()
    provider = settings.LLM_PROVIDER
    model = settings.LLM_MODEL

    print(f"Provider:   {provider}")
    print(f"Model:      {model}")
    print(f"Key Set:    {bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY != 'placeholder_for_local_testing')}")
    print("-" * 70)

    try:
        client = get_llm_client()
    except Exception as e:
        print(f"FAILED to initialize LLM client: {e}")
        return False

    # 1. Test generate_text
    print("\n[1/2] Probing generate_text with minimal prompt ('Respond with PONG')...")
    start_t = time.perf_counter()
    try:
        text_resp = await client.generate_text(prompt="Respond with the single word PONG.")
        latency_text = (time.perf_counter() - start_t) * 1000
        print(f"  SUCCESS! Latency: {latency_text:.1f}ms")
        print(f"  Response: {text_resp.strip()[:100]}")
    except Exception as exc:
        latency_text = (time.perf_counter() - start_t) * 1000
        print(f"  FAILED after {latency_text:.1f}ms")
        print(f"\n{diagnose_error(exc)}")
        return False

    # 2. Test generate_json
    print("\n[2/2] Probing generate_json with schema validation...")
    start_j = time.perf_counter()
    try:
        json_resp = await client.generate_json(
            prompt="Return JSON with status='ok' and message='hello'.",
            schema=PingResponse,
        )
        latency_json = (time.perf_counter() - start_j) * 1000
        print(f"  SUCCESS! Latency: {latency_json:.1f}ms")
        print(f"  Parsed JSON: status='{json_resp.status}', message='{json_resp.message}'")
    except Exception as exc:
        latency_json = (time.perf_counter() - start_j) * 1000
        print(f"  FAILED after {latency_json:.1f}ms")
        print(f"\n{diagnose_error(exc)}")
        return False

    print("\n" + "=" * 70)
    print("ALL LLM PROBES PASSED SUCCESSFULLY")
    print("=" * 70)
    return True


if __name__ == "__main__":
    success = asyncio.run(probe_llm())
    sys.exit(0 if success else 1)

