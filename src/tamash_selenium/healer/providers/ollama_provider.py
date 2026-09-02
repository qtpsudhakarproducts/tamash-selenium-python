"""Ollama's native ``/api/chat`` endpoint (the OpenAI-compatible path 410s on Ollama Cloud).

Backs both ``HEALER_PROVIDER=ollama`` (Ollama Cloud, ``OLLAMA_API_KEY`` required) and
``ollama-local`` (a self-hosted ``ollama serve``, key optional).
"""

from __future__ import annotations

from typing import Optional

from ... import env
from . import http, prompt
from .openai_provider import _env_or
from .types import (
    ActionTacticResult,
    HealProvider,
    ProviderDiagnosis,
    ProviderResult,
    SuggestActionTacticInput,
    SuggestSelectorInput,
    TokenUsage,
)

DEFAULT_TIMEOUT_MS = 15000.0


def _usage(payload: dict) -> TokenUsage:
    input_tokens = payload.get("prompt_eval_count")
    output_tokens = payload.get("eval_count")
    total = (input_tokens + output_tokens) if input_tokens is not None and output_tokens is not None else None
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total}


def _content(payload: Optional[dict]) -> Optional[str]:
    return (payload.get("message") or {}).get("content") if payload else None


def _build(name: str, url: str, headers: dict, model: str) -> HealProvider:
    def _body(system: str, user_text: str) -> dict:
        return {
            "model": model, "stream": False, "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
            ],
        }

    def suggest_selector(input: SuggestSelectorInput) -> Optional[ProviderResult]:
        payload = http.post_json(name, url, headers, _body(prompt.SYSTEM_PROMPT, prompt.build_user_prompt(input)),
                                 input.get("timeout_ms") or DEFAULT_TIMEOUT_MS)
        content = _content(payload)
        if not content:
            return None
        suggestion = prompt.parse_suggestion(content)
        return {"suggestion": suggestion, "usage": _usage(payload)} if suggestion is not None else None

    def suggest_action_tactic(input: SuggestActionTacticInput) -> Optional[ActionTacticResult]:
        payload = http.post_json(f"{name} action-recovery", url, headers,
                                 _body(prompt.ACTION_RECOVERY_SYSTEM_PROMPT, prompt.build_action_recovery_user_prompt(input)),
                                 input.get("timeout_ms") or DEFAULT_TIMEOUT_MS)
        content = _content(payload)
        if not content:
            return None
        tactic = prompt.parse_action_tactic_suggestion(content)
        return {"tactic": tactic, "usage": _usage(payload)} if tactic is not None else None

    def diagnose(timeout_ms: float) -> ProviderDiagnosis:
        return http.probe_http_endpoint(
            url, headers,
            {"model": model, "stream": False, "messages": [{"role": "user", "content": "Reply with the single word OK."}]},
            timeout_ms / 1000, _content,
        )

    return HealProvider(name=name, suggest_selector=suggest_selector,
                        suggest_action_tactic=suggest_action_tactic, diagnose=diagnose)


def create_ollama_provider() -> Optional[HealProvider]:
    api_key = env.get("OLLAMA_API_KEY")
    model = env.get("OLLAMA_MODEL")
    if not api_key or not model:
        return None
    base_url = _env_or("OLLAMA_BASE_URL", "https://ollama.com")
    return _build(f"ollama:{model}", f"{base_url}/api/chat", {"authorization": f"Bearer {api_key}"}, model)


def create_ollama_local_provider() -> Optional[HealProvider]:
    model = env.get("OLLAMA_LOCAL_MODEL")
    if not model:
        return None
    base_url = _env_or("OLLAMA_LOCAL_BASE_URL", "http://localhost:11434")
    headers: dict = {}
    api_key = env.get("OLLAMA_LOCAL_API_KEY")
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return _build(f"ollama-local:{model}", f"{base_url}/api/chat", headers, model)
