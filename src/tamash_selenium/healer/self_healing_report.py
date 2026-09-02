"""The per-heal report (``SelfHealingReport``) and the ordered per-attempt trail (``HealAttempt``).
Mutable during a single :func:`heal_action_failure` call, then handed back and appended to the
module-level list :func:`get_healing_reports` returns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .providers.types import TokenUsage


@dataclass
class HealAttempt:
    method: str  # cache | ref | text | action-recovery
    provider: Optional[str] = None
    suggested_selector: Optional[str] = None
    succeeded: bool = False
    stage: Optional[str] = None
    error: Optional[str] = None
    ai_ref: Optional[str] = None
    ai_nearby_ref: Optional[str] = None
    ai_nearby_text: Optional[str] = None
    ai_nearby_role: Optional[str] = None
    scoped: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"method": self.method, "succeeded": self.succeeded}
        for key in ("provider", "suggested_selector", "stage", "error",
                    "ai_ref", "ai_nearby_ref", "ai_nearby_text", "ai_nearby_role", "scoped"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


@dataclass
class SelfHealingReport:
    action: str
    kind: str
    description: Optional[str]
    provider: str
    healed: bool
    warning: str
    reason: str
    suggested_selector: Optional[str] = None
    token_usage: Optional[TokenUsage] = None
    failure_stage: Optional[str] = None
    used_action_recovery: bool = False
    source_location: Optional[str] = None
    test_id: Optional[str] = None
    initial_selector: Optional[str] = None
    needs_review: Optional[bool] = None
    review_note: Optional[str] = None
    healed_in_assertion: bool = False
    attempts: List[HealAttempt] = field(default_factory=list)
    # The exact ARIA tree the AI reasoned over — attached to the step report on an unrecovered
    # failure, deliberately NOT persisted to the heal log (it's page content, not audit data).
    aria_snapshot_for_report: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "action": self.action,
            "kind": self.kind,
            "provider": self.provider,
            "healed": self.healed,
            "warning": self.warning,
            "reason": self.reason,
            "usedActionRecovery": self.used_action_recovery,
            "attempts": [a.to_dict() for a in self.attempts],
        }
        optional = {
            "description": self.description,
            "suggestedSelector": self.suggested_selector,
            "failureStage": self.failure_stage,
            "sourceLocation": self.source_location,
            "testId": self.test_id,
            "initialSelector": self.initial_selector,
            "needsReview": self.needs_review,
            "reviewNote": self.review_note,
        }
        for key, value in optional.items():
            if value is not None:
                out[key] = value
        if self.healed_in_assertion:
            out["healedInAssertion"] = True
        if self.token_usage:
            out["tokenUsage"] = {
                k: v for k, v in {
                    "inputTokens": self.token_usage.get("input_tokens"),
                    "outputTokens": self.token_usage.get("output_tokens"),
                    "totalTokens": self.token_usage.get("total_tokens"),
                }.items() if v is not None
            }
        return out
