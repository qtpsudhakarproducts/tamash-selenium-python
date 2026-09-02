from __future__ import annotations

from typing import Optional

from ... import env
from . import openai_compatible
from .types import HealProvider


def _env_or(key: str, fallback: str) -> str:
    value = env.get(key)
    return fallback if not value else value.rstrip("/")


def create_openai_provider() -> Optional[HealProvider]:
    api_key = env.get("OPENAI_API_KEY")
    model = env.get("OPENAI_MODEL")
    if not api_key or not model:
        return None
    base_url = _env_or("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return openai_compatible.create(
        name=f"openai:{model}",
        chat_url=f"{base_url}/chat/completions",
        auth_headers={"authorization": f"Bearer {api_key}"},
        model=model,
    )
