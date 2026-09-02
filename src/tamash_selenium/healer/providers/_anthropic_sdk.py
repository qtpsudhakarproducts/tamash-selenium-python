"""Anthropic Messages API via the official ``anthropic`` SDK — shared by the API-key ``anthropic``
provider and by ``claude-subscription`` (same endpoint, different auth).

Follows the Java port: ``claude-subscription`` authenticates a plain Messages call with a Claude
Code OAuth token (``CLAUDE_CODE_OAUTH_TOKEN`` from ``claude setup-token``) plus the
``anthropic-beta: oauth-2025-04-20`` header and a leading Claude Code identity system block —
the wire contract the token is authorised for. One dependency (``anthropic``) covers both.
"""

from __future__ import annotations

from typing import Optional

from . import prompt
from .http import classify_thrown_error
from .types import (
    ActionTacticResult,
    HealProvider,
    ProviderDiagnosis,
    ProviderResult,
    SuggestActionTacticInput,
    SuggestSelectorInput,
)

DEFAULT_TIMEOUT_MS = 15000.0
_CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
_OAUTH_BETA = "oauth-2025-04-20"


def create(name: str, model: str, api_key: Optional[str] = None, auth_token: Optional[str] = None) -> HealProvider:
    import anthropic  # raises ModuleNotFoundError -> handled by providers/__init__.py

    oauth = bool(auth_token)
    kwargs = {"auth_token": auth_token} if oauth else {"api_key": api_key}
    if oauth:
        kwargs["default_headers"] = {"anthropic-beta": _OAUTH_BETA}
    client = anthropic.Anthropic(**kwargs)

    def _system(system_prompt: str):
        if oauth:
            return [{"type": "text", "text": _CLAUDE_CODE_IDENTITY}, {"type": "text", "text": system_prompt}]
        return system_prompt

    def _call(system_prompt: str, user_text: str, timeout_ms: Optional[float], label: str):
        try:
            timeout_s = (timeout_ms or DEFAULT_TIMEOUT_MS) / 1000
            return client.messages.create(
                model=model, max_tokens=1024, system=_system(system_prompt),
                messages=[{"role": "user", "content": user_text}], timeout=timeout_s,
            )
        except Exception as error:  # noqa: BLE001
            print(f"[self-healer] {name}{label} provider error: {error}")
            return None

    def _first_text(response) -> Optional[str]:
        block = next((b for b in response.content if getattr(b, "type", None) == "text"), None)
        return block.text if block is not None else None

    def _usage(response):
        try:
            return {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens}
        except Exception:  # noqa: BLE001
            return None

    def suggest_selector(input: SuggestSelectorInput) -> Optional[ProviderResult]:
        response = _call(prompt.SYSTEM_PROMPT, prompt.build_user_prompt(input), input.get("timeout_ms"), "")
        if response is None:
            return None
        text = _first_text(response)
        suggestion = prompt.parse_suggestion(text) if text else None
        return {"suggestion": suggestion, "usage": _usage(response)} if suggestion is not None else None

    def suggest_action_tactic(input: SuggestActionTacticInput) -> Optional[ActionTacticResult]:
        response = _call(prompt.ACTION_RECOVERY_SYSTEM_PROMPT, prompt.build_action_recovery_user_prompt(input),
                         input.get("timeout_ms"), " action-recovery")
        if response is None:
            return None
        text = _first_text(response)
        tactic = prompt.parse_action_tactic_suggestion(text) if text else None
        return {"tactic": tactic, "usage": _usage(response)} if tactic is not None else None

    def diagnose(timeout_ms: float) -> ProviderDiagnosis:
        try:
            response = client.messages.create(
                model=model, max_tokens=16, system=_system("Reply with the single word OK."),
                messages=[{"role": "user", "content": "Reply with the single word OK."}], timeout=timeout_ms / 1000,
            )
            text = _first_text(response)
            if not text or not text.strip():
                return {"category": "bad-response", "detail": "Anthropic replied but with no text content"}
            return {"category": "ok", "detail": f"{model} responded within the timeout"}
        except Exception as error:  # noqa: BLE001
            return classify_thrown_error(error)

    return HealProvider(name=name, suggest_selector=suggest_selector,
                        suggest_action_tactic=suggest_action_tactic, diagnose=diagnose)
