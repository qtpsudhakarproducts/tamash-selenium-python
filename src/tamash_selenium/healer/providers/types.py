"""Provider-facing types. A suggestion is a plain ``dict`` with a ``strategy`` tag (mirrors the
Java ``AiSuggestion`` flattened union / the TS discriminated union).

Selenium strategies: ``none, ref, css, xpath, id, name, text, near, adjacent, scoped, containing,
normalized``. ``ref`` is heal-time-only (it resolves to the exact element the snapshot enumerated
via ``[data-tamash-ref=...]`` but only lives for the current document instance) — route anything
that might carry it through :func:`exclude_ref_strategy` before it reaches the heal log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, TypedDict


class TokenUsage(TypedDict, total=False):
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    total_tokens: Optional[int]


class SuggestSelectorInput(TypedDict, total=False):
    action: Optional[str]
    description: Optional[str]
    aria_snapshot: str
    timeout_ms: Optional[float]
    # Extra raw context for the AI finder (the model can expand a terse name / read intent from the
    # broken selector better than the deterministic decoder).
    raw_name: Optional[str]
    broken_selector: Optional[str]
    context_class: Optional[str]


SelectorSuggestion = dict


def exclude_ref_strategy(suggestion: Optional[SelectorSuggestion]) -> Optional[SelectorSuggestion]:
    """``None`` for a ``ref``/``none`` suggestion, the suggestion unchanged otherwise — the one
    place a transient ref could otherwise leak toward the persisted heal log."""
    if suggestion is None or suggestion.get("strategy") in ("ref", "none"):
        return None
    return suggestion


class ProviderResult(TypedDict, total=False):
    suggestion: SelectorSuggestion
    usage: Optional[TokenUsage]


ActionTactic = str  # 'none' | 'scroll' | 'force' | 'wait' | 'dispatch'


class SuggestActionTacticInput(TypedDict, total=False):
    action: str
    error_message: str
    timeout_ms: Optional[float]


class ActionTacticResult(TypedDict, total=False):
    tactic: ActionTactic
    usage: Optional[TokenUsage]


DiagnosisCategory = str  # ok | not-installed | not-authenticated | timeout | bad-model | network | bad-response | unknown


class ProviderDiagnosis(TypedDict):
    category: DiagnosisCategory
    detail: str


@dataclass
class HealProvider:
    name: str
    suggest_selector: Callable[[SuggestSelectorInput], Optional[ProviderResult]]
    suggest_action_tactic: Optional[Callable[[SuggestActionTacticInput], Optional[ActionTacticResult]]] = None
    # Diagnostics-only (used by ``tamash-selenium doctor``): one trivial round trip, structured
    # outcome. Optional — doctor falls back to a ``suggest_selector`` probe. Must never raise.
    diagnose: Optional[Callable[[float], ProviderDiagnosis]] = None


def sum_token_usage(a: Optional[TokenUsage], b: Optional[TokenUsage]) -> Optional[TokenUsage]:
    if a is None:
        return b
    if b is None:
        return a

    def _add(x: Optional[int], y: Optional[int]) -> Optional[int]:
        if x is None and y is None:
            return None
        return (x or 0) + (y or 0)

    return {
        "input_tokens": _add(a.get("input_tokens"), b.get("input_tokens")),
        "output_tokens": _add(a.get("output_tokens"), b.get("output_tokens")),
        "total_tokens": _add(a.get("total_tokens"), b.get("total_tokens")),
    }


def format_token_usage(usage: TokenUsage) -> str:
    parts = []
    if usage.get("input_tokens") is not None:
        parts.append(f"{usage['input_tokens']} input")
    if usage.get("output_tokens") is not None:
        parts.append(f"{usage['output_tokens']} output")
    breakdown = f" ({' + '.join(parts)})" if parts else ""
    total = usage.get("total_tokens")
    return f"{total} tokens{breakdown}" if total is not None else f"tokens{breakdown}"
