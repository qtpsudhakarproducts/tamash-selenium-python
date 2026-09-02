from __future__ import annotations

from typing import Optional

from ... import env
from . import openai_compatible
from .openai_provider import _env_or
from .types import HealProvider


def create_gemini_provider() -> Optional[HealProvider]:
    api_key = env.get("GEMINI_API_KEY")
    model = env.get("GEMINI_MODEL")
    if not api_key or not model:
        return None
    base_url = _env_or("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
    # GEMINI_THINKING=on keeps the model's default thinking budget; off (default) sends
    # reasoning_effort:low so a selector lookup returns in a few seconds instead of 15-30.
    disable_thinking = (env.get("GEMINI_THINKING") or "").strip().lower() != "on"
    return openai_compatible.create(
        name=f"gemini:{model}",
        chat_url=f"{base_url}/chat/completions",
        auth_headers={"authorization": f"Bearer {api_key}"},
        model=model,
        disable_thinking=disable_thinking,
    )
