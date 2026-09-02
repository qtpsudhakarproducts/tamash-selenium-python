"""``HEALER_PROVIDER`` picks which provider backs self-healing. Each API-key provider gracefully
returns ``None`` (disabling healing for that action) if its own env vars aren't set. When
``HEALER_PROVIDER`` is unset the rule-based ``tamash`` provider is used — plug-and-play healing
with no key, no network, no tokens.
"""

from __future__ import annotations

import threading
from typing import Optional

from ... import env
from .tamash_rule_based_provider import create_tamash_rule_based_provider
from .types import (
    ActionTacticResult,
    HealProvider,
    ProviderDiagnosis,
    ProviderResult,
    SelectorSuggestion,
    SuggestActionTacticInput,
    SuggestSelectorInput,
    TokenUsage,
    exclude_ref_strategy,
    format_token_usage,
    sum_token_usage,
)

__all__ = [
    "get_heal_provider",
    "reset_provider_cache",
    "HealProvider",
    "ProviderResult",
    "ProviderDiagnosis",
    "SelectorSuggestion",
    "SuggestSelectorInput",
    "SuggestActionTacticInput",
    "ActionTacticResult",
    "TokenUsage",
    "exclude_ref_strategy",
    "format_token_usage",
    "sum_token_usage",
]

_lock = threading.Lock()
_cached_provider: Optional[HealProvider] = None
_cache_populated = False


def _build_provider(name: Optional[str]) -> Optional[HealProvider]:
    if not name or name == "tamash":
        return create_tamash_rule_based_provider()

    # AI providers land in Phase 2 — imported lazily so a slim install without their optional
    # dependencies still works for the rule-based default.
    if name == "openai":
        from .openai_provider import create_openai_provider
        return create_openai_provider()
    if name == "gemini":
        from .gemini_provider import create_gemini_provider
        return create_gemini_provider()
    if name == "ollama":
        from .ollama_provider import create_ollama_provider
        return create_ollama_provider()
    if name == "ollama-local":
        from .ollama_provider import create_ollama_local_provider
        return create_ollama_local_provider()
    if name == "anthropic":
        from .anthropic_provider import create_anthropic_provider
        return create_anthropic_provider()
    if name == "claude-subscription":
        from .claude_subscription_provider import create_claude_subscription_provider
        return create_claude_subscription_provider()
    if name == "copilot-subscription":
        from .copilot_subscription_provider import create_copilot_subscription_provider
        return create_copilot_subscription_provider()
    return None


def get_heal_provider() -> Optional[HealProvider]:
    global _cached_provider, _cache_populated
    with _lock:
        if _cache_populated:
            return _cached_provider
        try:
            _cached_provider = _build_provider((env.get("HEALER_PROVIDER") or "").strip() or None)
        except ModuleNotFoundError as exc:
            print(f"[self-healer] provider unavailable: {exc}. Install the matching extra "
                  f"(e.g. `pip install 'tamash-selenium[anthropic]'`).")
            _cached_provider = None
        _cache_populated = True
        return _cached_provider


def reset_provider_cache() -> None:
    global _cached_provider, _cache_populated
    with _lock:
        _cached_provider = None
        _cache_populated = False
