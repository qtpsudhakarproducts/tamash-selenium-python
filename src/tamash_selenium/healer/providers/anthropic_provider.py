from __future__ import annotations

from typing import Optional

from ... import env
from . import _anthropic_sdk
from .types import HealProvider


def create_anthropic_provider() -> Optional[HealProvider]:
    api_key = env.get("ANTHROPIC_API_KEY")
    model = env.get("ANTHROPIC_MODEL")
    if not api_key or not model:
        return None
    return _anthropic_sdk.create(name=f"anthropic:{model}", model=model, api_key=api_key)
