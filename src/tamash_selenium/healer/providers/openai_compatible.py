"""Shared :class:`HealProvider` for any endpoint that speaks OpenAI's Chat Completions shape —
OpenAI itself and Gemini's OpenAI-compatible surface. Thin per-vendor wrappers
(``openai_provider.py`` / ``gemini_provider.py``) just supply the URL, auth headers, and model.
"""

from __future__ import annotations

from typing import Optional

from . import http, prompt
from .types import (
    ActionTacticResult,
    HealProvider,
    ProviderDiagnosis,
    ProviderResult,
    SuggestActionTacticInput,
    SuggestSelectorInput,
)

DEFAULT_TIMEOUT_MS = 20000.0


def _content(payload: Optional[dict]) -> Optional[str]:
    if not payload:
        return None
    choices = payload.get("choices") or []
    if not choices:
        return None
    return (choices[0].get("message") or {}).get("content")


def create(name: str, chat_url: str, auth_headers: dict, model: str, disable_thinking: bool = False) -> HealProvider:
    def _body(system: str, user_text: str) -> dict:
        body = {
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
        }
        if disable_thinking:
            body["reasoning_effort"] = "low"
        return body

    def suggest_selector(input: SuggestSelectorInput) -> Optional[ProviderResult]:
        timeout_ms = input.get("timeout_ms") or DEFAULT_TIMEOUT_MS
        payload = http.post_json(name, chat_url, auth_headers,
                                 _body(prompt.SYSTEM_PROMPT, prompt.build_user_prompt(input)), timeout_ms)
        content = _content(payload)
        if not content:
            return None
        suggestion = prompt.parse_suggestion(content)
        if suggestion is None:
            return None
        return {"suggestion": suggestion, "usage": prompt.extract_openai_compatible_usage(payload)}

    def suggest_action_tactic(input: SuggestActionTacticInput) -> Optional[ActionTacticResult]:
        timeout_ms = input.get("timeout_ms") or DEFAULT_TIMEOUT_MS
        payload = http.post_json(f"{name} action-recovery", chat_url, auth_headers,
                                 _body(prompt.ACTION_RECOVERY_SYSTEM_PROMPT,
                                       prompt.build_action_recovery_user_prompt(input)), timeout_ms)
        content = _content(payload)
        if not content:
            return None
        tactic = prompt.parse_action_tactic_suggestion(content)
        if tactic is None:
            return None
        return {"tactic": tactic, "usage": prompt.extract_openai_compatible_usage(payload)}

    def diagnose(timeout_ms: float) -> ProviderDiagnosis:
        return http.probe_http_endpoint(
            chat_url, auth_headers,
            {"model": model, "messages": [{"role": "user", "content": "Reply with the single word OK."}]},
            timeout_ms / 1000, _content,
        )

    return HealProvider(name=name, suggest_selector=suggest_selector,
                        suggest_action_tactic=suggest_action_tactic, diagnose=diagnose)
