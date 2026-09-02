"""Self-healing backed by a personal Claude subscription rather than a pay-per-token API key.

Uses the ``anthropic`` SDK's Messages endpoint authenticated with a Claude Code OAuth token
(``CLAUDE_CODE_OAUTH_TOKEN``, from ``claude setup-token``) plus the
``anthropic-beta: oauth-2025-04-20`` header and the Claude Code identity system block — the wire
contract that token is authorised for. Always constructs; auth is only verifiable per call.
"""

from __future__ import annotations

from typing import Optional

from ... import env
from . import _anthropic_sdk
from .types import (
    ActionTacticResult,
    HealProvider,
    ProviderDiagnosis,
    ProviderResult,
    SuggestActionTacticInput,
    SuggestSelectorInput,
)


def create_claude_subscription_provider() -> HealProvider:
    model = env.get("CLAUDE_SUBSCRIPTION_MODEL") or "claude-haiku-4-5"
    token = env.get("CLAUDE_CODE_OAUTH_TOKEN")
    name = f"claude-subscription:{model}"

    if not token:
        return _unavailable(name)
    try:
        return _anthropic_sdk.create(name=name, model=model, auth_token=token)
    except ModuleNotFoundError:
        raise  # providers/__init__.py prints the "install the extra" hint


def _unavailable(name: str) -> HealProvider:
    def _warn(*_a, **_k):
        print("[self-healer] claude-subscription: CLAUDE_CODE_OAUTH_TOKEN is not set — "
              "run `claude setup-token`, or use HEALER_PROVIDER=anthropic + ANTHROPIC_API_KEY instead.")
        return None

    def diagnose(_timeout_ms: float) -> ProviderDiagnosis:
        return {"category": "not-authenticated", "detail": "CLAUDE_CODE_OAUTH_TOKEN is not set"}

    return HealProvider(
        name=name,
        suggest_selector=lambda _i: _warn(),  # type: ignore[arg-type]
        suggest_action_tactic=lambda _i: _warn(),
        diagnose=diagnose,
    )
