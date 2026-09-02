"""Self-healing backed by a GitHub Copilot subscription — via the ``github-copilot-sdk`` package
(requires Python 3.11+) driving the ``copilot`` CLI. Auth is an existing ``copilot`` CLI login or
an ambient ``GITHUB_TOKEN``; always constructs, failure is deferred per call.
"""

from __future__ import annotations

from typing import Optional

from ... import env
from . import prompt
from ._async_utils import run_async
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


def _warn(reason: str, not_installed: bool) -> None:
    if not_installed:
        print("[self-healer] copilot-subscription: the 'github-copilot-sdk' package isn't installed "
              "(requires Python 3.11+) — install it with: pip install 'tamash-selenium[copilot-subscription]', "
              "or use HEALER_PROVIDER=openai/anthropic/gemini + an API key instead.")
        return
    print(f"[self-healer] copilot-subscription: {reason} — not authenticated? Sign in with the "
          "`copilot` CLI, or for CI set GITHUB_TOKEN, or use an API-key provider instead.")


def _github_token() -> Optional[str]:
    # A PAT with Copilot access (CI). Falls back to the `copilot` CLI's own login when unset.
    # Stripped — a stray newline in a CI secret otherwise becomes an invalid Authorization header.
    raw = env.get("COPILOT_GITHUB_TOKEN") or env.get("GITHUB_TOKEN")
    return raw.strip() if raw and raw.strip() else None


async def _send_async(model: str, system_prompt: str, user_prompt: str, timeout_s: float) -> Optional[dict]:
    from copilot import CopilotClient

    token = _github_token()
    client = CopilotClient(github_token=token) if token else CopilotClient()
    await client.start()
    try:
        session = await client.create_session(model=model, available_tools=[])
        reply = await session.send_and_wait(f"{system_prompt}\n\n{user_prompt}", timeout=timeout_s)
        if reply is None:
            return None
        content = getattr(reply.data, "content", None)
        if not content:
            return None
        return {"content": content, "output_tokens": getattr(reply.data, "output_tokens", None)}
    finally:
        try:
            await client.stop()
        except Exception:  # noqa: BLE001
            pass


def _send(model: str, system_prompt: str, user_prompt: str, timeout_s: float) -> Optional[dict]:
    try:
        import copilot  # noqa: F401
    except ImportError:
        _warn("", not_installed=True)
        return None
    try:
        return run_async(lambda: _send_async(model, system_prompt, user_prompt, timeout_s), timeout_s + 10)
    except Exception as error:  # noqa: BLE001
        _warn(str(error), not_installed=False)
        return None


def _usage(result: dict) -> Optional[dict]:
    output_tokens = result.get("output_tokens")
    return None if output_tokens is None else {"output_tokens": output_tokens}


def create_copilot_subscription_provider() -> HealProvider:
    model = env.get("COPILOT_SUBSCRIPTION_MODEL") or "mai-code-1-flash-picker"
    name = f"copilot-subscription:{model}"

    def _timeout_s(input) -> float:
        return (input.get("timeout_ms") or DEFAULT_TIMEOUT_MS) / 1000

    def suggest_selector(input: SuggestSelectorInput) -> Optional[ProviderResult]:
        result = _send(model, prompt.SYSTEM_PROMPT, prompt.build_user_prompt(input), _timeout_s(input))
        if not result:
            return None
        suggestion = prompt.parse_suggestion(result["content"])
        return {"suggestion": suggestion, "usage": _usage(result)} if suggestion is not None else None

    def suggest_action_tactic(input: SuggestActionTacticInput) -> Optional[ActionTacticResult]:
        result = _send(model, prompt.ACTION_RECOVERY_SYSTEM_PROMPT,
                       prompt.build_action_recovery_user_prompt(input), _timeout_s(input))
        if not result:
            return None
        tactic = prompt.parse_action_tactic_suggestion(result["content"])
        return {"tactic": tactic, "usage": _usage(result)} if tactic is not None else None

    def diagnose(timeout_ms: float) -> ProviderDiagnosis:
        try:
            import copilot  # noqa: F401
        except ImportError as error:
            return {"category": "not-installed", "detail": str(error)}
        try:
            result = run_async(lambda: _send_async(model, "Reply with the single word OK.", "OK", timeout_ms / 1000),
                               timeout_ms / 1000 + 10)
            if result and result["content"].strip():
                return {"category": "ok", "detail": f"{model} responded within the timeout"}
            return {"category": "unknown", "detail": "copilot-subscription returned no content (often an auth or model problem)"}
        except Exception as error:  # noqa: BLE001
            return classify_thrown_error(error)

    return HealProvider(name=name, suggest_selector=suggest_selector,
                        suggest_action_tactic=suggest_action_tactic, diagnose=diagnose)
