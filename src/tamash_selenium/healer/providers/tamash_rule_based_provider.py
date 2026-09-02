"""The zero-dependency, zero-token default provider: no model call, no API key, no network.

Resolves a broken locator by text-matching the element's decoded description against the
already-captured DOM accessibility snapshot (:func:`find_rule_based_match`), reusing the exact
same never-guess discipline the AI-backed providers' prompt enforces. Narrower success envelope
than an AI provider — it never guesses, and there is no action-recovery tactic (it always
declines).
"""

from __future__ import annotations

import re
from typing import Optional

from ..durable_locator import find_rule_based_match, infer_role_from_action, parse_aria_ai_tree, strip_generic_role_suffix
from .types import (
    ActionTacticResult,
    HealProvider,
    ProviderDiagnosis,
    ProviderResult,
    SuggestActionTacticInput,
    SuggestSelectorInput,
)

_HINT_RE = re.compile(r"^(.*)\s\(([^)]+)\)$")


def _parse_description_for_match(description: Optional[str]) -> Optional[dict]:
    if not description:
        return None
    stripped = strip_generic_role_suffix(description) or ""
    hint_match = _HINT_RE.match(stripped)
    if hint_match:
        phrase = hint_match.group(1).strip()
        return {"phrase": phrase, "type_hint": hint_match.group(2).strip()} if phrase else None
    return {"phrase": stripped, "type_hint": None} if stripped else None


def create_tamash_rule_based_provider() -> HealProvider:
    def suggest_selector(input: SuggestSelectorInput) -> Optional[ProviderResult]:
        parsed = _parse_description_for_match(input.get("description"))
        if not parsed:
            return {"suggestion": {"strategy": "none"}}
        nodes = parse_aria_ai_tree(input.get("aria_snapshot"))
        expected_role = parsed["type_hint"] or infer_role_from_action(input.get("action"))
        suggestion = find_rule_based_match(nodes, parsed["phrase"], expected_role)
        return {"suggestion": suggestion}

    def suggest_action_tactic(_input: SuggestActionTacticInput) -> Optional[ActionTacticResult]:
        return {"tactic": "none"}

    def diagnose(_timeout_ms: float) -> ProviderDiagnosis:
        return {"category": "ok", "detail": "rule-based matcher — no network, SDK or credentials involved"}

    return HealProvider(
        name="tamash",
        suggest_selector=suggest_selector,
        suggest_action_tactic=suggest_action_tactic,
        diagnose=diagnose,
    )
