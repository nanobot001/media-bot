import asyncio
import json
import logging
import os
import traceback
from typing import Any, Dict, Optional

import httpx

from moviebot.config import settings
from moviebot.db.repositories import ErrorLogRepository

logger = logging.getLogger(__name__)


def _normalize_model(model: str) -> str:
    m = model or "gemini-2.5-flash"
    if m.startswith("models/"):
        return m[len("models/"):]
    return m


async def generate_gemini_content(
    prompt: str,
    system_instruction: Optional[str] = None,
    json_schema: Optional[Dict[str, Any]] = None,
    temperature: float = 0.2,
    model: Optional[str] = None
) -> str:
    """
    Generate text or JSON using the Google Gemini API with retries and DB logging on failure.
    """
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not configured in settings or environment variables.")

    model_name = _normalize_model(model or settings.gemini_enrichment_model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"

    # Assemble request payload
    payload: Dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
        }
    }

    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    if json_schema:
        payload["generationConfig"]["response_mime_type"] = "application/json"
        payload["generationConfig"]["response_schema"] = json_schema

    max_attempts = 4
    base_backoff = 1.0

    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                res = await client.post(
                    url,
                    headers={"x-goog-api-key": api_key},
                    json=payload
                )

                if res.status_code in (429, 500, 502, 503, 504):
                    # Retryable codes
                    res.raise_for_status()

                res.raise_for_status()
                data = res.json()

                # Extract content
                candidates = data.get("candidates")
                if not candidates:
                    raise ValueError(f"Gemini API returned no candidates: {data}")

                parts = candidates[0].get("content", {}).get("parts")
                if not parts:
                    raise ValueError(f"Gemini API candidate content had no parts: {data}")

                return parts[0].get("text", "")

        except Exception as e:
            logger.warning(
                f"Attempt {attempt}/{max_attempts} to query Gemini failed: {e}"
            )
            if attempt < max_attempts:
                sleep_time = base_backoff * (2 ** (attempt - 1))
                await asyncio.sleep(sleep_time)
            else:
                # Log failure to ErrorLogRepository
                error_msg = f"Gemini API content generation failed after {max_attempts} attempts: {str(e)}"
                stack_trace = traceback.format_exc()
                try:
                    ErrorLogRepository.insert(
                        command_name="gemini_client",
                        user_id=None,
                        user_name=None,
                        error_message=error_msg,
                        stack_trace=stack_trace
                    )
                except Exception as db_err:
                    logger.error(f"Failed to insert Gemini error into ErrorLogRepository: {db_err}")

                raise RuntimeError(error_msg) from e

    raise RuntimeError("Gemini content generation reached unreachable state.")
