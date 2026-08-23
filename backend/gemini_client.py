"""Shared Gemini client singleton (one HTTP pool per process)."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

from backend.config import Settings, get_settings

logger = logging.getLogger(__name__)


@lru_cache
def get_gemini_client(api_key: str) -> Any:
    from google import genai

    return genai.Client(api_key=api_key)


def resolve_gemini_client(settings: Optional[Settings] = None) -> Optional[Any]:
    settings = settings or get_settings()
    if not settings.has_gemini:
        return None
    try:
        return get_gemini_client(settings.google_api_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to init Gemini client: %s", exc)
        return None
