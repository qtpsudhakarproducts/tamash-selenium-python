"""Runtime self-healing orchestration — the Python translation of the Java ``Healer.java``
(itself the Selenium port of ``tamash-playwright``'s ``healer/index.ts``).

Pipeline, in order, stopping at the first that recovers:

1. **positive cache** — a selector already healed this run for that locator+page (any caller,
   including a wait's next poll) is reused instantly.
2. **negative cache** — a heal declined for this exact DOM state isn't retried until the DOM changes.
3. **disk cache** — a previously-confirmed selector for this exact source line (``heals.jsonl``).
4. **DOM snapshot + provider** — a JS accessibility tree; the provider names the element; a durable
   ``By`` is derived and verified against the live element before it's trusted.
5. **action recovery** (opt-in) — scroll / JS-click / wait / dispatch when the element is found
   but the action is blocked.

If nothing recovers, the original error is re-raised and the test fails exactly as it would have.
"""

from __future__ import annotations

import atexit
import contextvars
import datetime as _dt
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

from .. import current_test, env
from .. import tamash as _tamash
from .. import report as report_module
from . import dom_snapshot, heal_cache, heal_log
from .action_recovery import try_action_recovery
from .durable_locator import (
    AriaAiNode,
    Locator,
    derive_suggestion_from_element,
    find_adjacent_branch_path,
    find_sibling_anchor_texts,
    generate_replacement_call,
    infer_role_from_action,
    parse_aria_ai_tree,
    same_element,
    strip_generic_role_suffix,
    to_by,
)
from .durable_locator import extract_scoped_snapshot  # noqa: E402
from .page_context import PageContext
from .providers import get_heal_provider
from .providers.types import (
    HealProvider,
    TokenUsage,
    exclude_ref_strategy,
    format_token_usage,
    sum_token_usage,
)
from .replay_action import replay_action
from .self_healing_report import HealAttempt, SelfHealingReport

DEFAULT_TIMEOUT_MS = 20000.0

FAILURE_STAGES = {
    "disabled": "Healing is turned off (HEALER_ENABLED=false).",
    "reentrant": "Blocked by the recursion guard (this failure happened while replaying an already-healed locator).",
    "not-a-selector-issue": "The element was found, but the action itself could not complete — not a selector problem, so self-healing was not attempted.",
    "no_snapshot": "Could not capture the page's DOM snapshot to search.",
    "recently_declined": "A heal was just attempted for this locator and declined; the page hasn't changed since, so it wasn't retried.",
    "no_provider": "No AI provider is configured (missing API key/model).",
    "provider_error": "The AI call itself failed or returned nothing usable — see the console log for detail.",
    "ai_declined": "The AI found nothing in the snapshot plausibly matching the description.",
    "unbuildable_suggestion": "The AI's suggested strategy couldn't be turned into a locator.",
    "replay_failed": "The AI suggested a replacement locator, but acting on it failed too.",
    "action_recovery_declined": "The element was found, but none of the known recovery tactics would plausibly help.",
    "action_recovery_failed": "A recovery tactic was attempted, but the action still could not be completed.",
}

_reports: List[SelfHealingReport] = []
_reports_lock = threading.Lock()
_healing_in_progress: contextvars.ContextVar[bool] = contextvars.ContextVar("tamash_healing_in_progress", default=False)

_assertion_healed_tests: set = set()
_assertion_hook_registered = False


# --------------------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------------------


def is_healing_enabled() -> bool:
    value = (env.get("HEALER_ENABLED") or "").strip().lower()
    return value not in ("false", "0")


def is_action_recovery_enabled() -> bool:
    return (env.get("HEALER_ACTION_RECOVERY_ENABLED") or "").strip().lower() == "true"


def assertion_mode() -> str:
    value = (env.get("HEALER_ASSERTIONS") or "").strip().lower()
    return value if value in ("warn", "strict") else "heal"


def _effective_timeout() -> float:
    return env.get_float("TAMASH_ACTION_TIMEOUT_MS", DEFAULT_TIMEOUT_MS)


def _note_assertion_heal(test_id: Optional[str]) -> None:
    global _assertion_hook_registered
    _assertion_healed_tests.add(test_id or "(unattributed)")
    if not _assertion_hook_registered:
        _assertion_hook_registered = True
        atexit.register(print_assertion_heal_summary)


def print_assertion_heal_summary() -> None:
    if not _assertion_healed_tests:
        return
    print(f"[tamash] {len(_assertion_healed_tests)} test(s) had a locator healed inside an "
          f"assertion (HEALER_ASSERTIONS=warn):")
    for test_id in sorted(_assertion_healed_tests):
        print(f"  - {test_id}")
    print("  Review these — a wrong heal in an assertion can hide a real bug. "
          "Run with HEALER_ASSERTIONS=strict to fail instead of heal.")


# --------------------------------------------------------------------------------------------------
# Error classification
# --------------------------------------------------------------------------------------------------

_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def normalize_error(error: Optional[BaseException]) -> str:
    if error is None:
        return "Unknown action failure"
    message = _ANSI_CSI_RE.sub("", str(error))
    return message.split("\n", 1)[0].strip()


def _error_class_name(error: Optional[BaseException]) -> str:
    return type(error).__name__ if error is not None else ""


def is_missing_element(error: Optional[BaseException]) -> bool:
    return _error_class_name(error) in ("NoSuchElementException", "InvalidSelectorException", "StaleElementReferenceException")


def is_actionability_failure(error: Optional[BaseException]) -> bool:
    return _error_class_name(error) in (
        "ElementNotInteractableException", "ElementClickInterceptedException", "InvalidElementStateException",
    )


def is_stale_failure(error: Optional[BaseException]) -> bool:
    return _error_class_name(error) == "StaleElementReferenceException"


# --------------------------------------------------------------------------------------------------
# HealContext + result
# --------------------------------------------------------------------------------------------------


@dataclass
class HealContext:
    action: Optional[str]  # click | send_keys | ... | None (bare find failure)
    kind: str  # driver | element
    description: Optional[str]
    error: BaseException
    driver: Any
    by: Optional[Locator]
    original_by_string: Optional[str] = None
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    source_location: Optional[str] = None
    raw_variable_name: Optional[str] = None
    enclosing_class: Optional[str] = None
    in_assertion: bool = False
    in_wait: bool = False
    frame_chain: List[Locator] = field(default_factory=list)
    test_id: Optional[str] = None
    test_title: Optional[str] = None
    # A callable that re-runs the original failed action against a healed raw element.
    replay: Optional[Callable[[Any], Any]] = None


@dataclass
class HealResult:
    report: SelfHealingReport
    recovered: bool
    result: Any


# --------------------------------------------------------------------------------------------------
# Page context / snapshot helpers
# --------------------------------------------------------------------------------------------------


def _resolve_page_context(ctx: HealContext) -> PageContext:
    return PageContext(driver=ctx.driver, frame_chain=list(ctx.frame_chain or []))


def _capture_snapshot(page_context: Optional[PageContext]) -> Optional[str]:
    if page_context is None:
        return None
    try:
        page_context.enter_frame()
        return dom_snapshot.capture(page_context.driver)
    except Exception:  # noqa: BLE001
        return None
    finally:
        page_context.exit_frame()


def _page_key_of(driver: Any) -> str:
    try:
        url = driver.current_url or ""
    except Exception:  # noqa: BLE001
        return ""
    for sep in ("?", "#"):
        idx = url.find(sep)
        if idx >= 0:
            url = url[:idx]
    return url


def _dom_key_of(driver: Any) -> str:
    try:
        value = driver.execute_script(
            "return document.readyState + ':' + document.querySelectorAll('*').length + ':' + (document.title||'');"
        )
        return str(value) if value is not None else ""
    except Exception:  # noqa: BLE001
        return ""


def _safe_find(page_context: Optional[PageContext], by: Optional[Locator]) -> Optional[Any]:
    if page_context is None or by is None:
        return None
    try:
        page_context.enter_frame()
        return page_context.find_or_none(by)
    finally:
        page_context.exit_frame()


# --------------------------------------------------------------------------------------------------
# Locator construction from a suggestion
# --------------------------------------------------------------------------------------------------


@dataclass
class _Built:
    element: Any
    by: Locator
    resolved_suggestion: dict


def _build_locator_from_suggestion(page_context: PageContext, suggestion: dict, action: Optional[str]) -> Optional[_Built]:
    by = to_by(suggestion)
    if by is None:
        inferred = infer_role_from_action(action)
        text = suggestion.get("text")
        if not inferred or not text:
            return None
        suggestion = {"strategy": "near", "anchorText": text, "role": inferred, "parentLevels": 1}
        by = to_by(suggestion)
        if by is None:
            return None
    page_context.enter_frame()
    try:
        element = page_context.find_or_none(by)
        return _Built(element, by, suggestion) if element is not None else None
    finally:
        page_context.exit_frame()


def _describe_suggestion(suggestion: dict) -> Optional[str]:
    if suggestion.get("strategy") == "ref":
        return f"ref:{suggestion['ref']} (transient — not persisted)"
    return generate_replacement_call(suggestion)


# --------------------------------------------------------------------------------------------------
# Durable-locator derivation (widening search)
# --------------------------------------------------------------------------------------------------


@dataclass
class DerivedDurableLocator:
    element: Any
    by: Locator
    suggestion: dict
    initial_selector: Optional[str]
    needs_review: bool
    review_note: Optional[str]


@dataclass
class _TreeContext:
    snapshot: str
    candidate_refs: List[str]
    ai_nearby_ref: Optional[str] = None
    ai_nearby_text: Optional[str] = None


def _verify_structural(page_context: PageContext, suggestion: dict, anchor: Any,
                       initial_selector: Optional[str], note: str) -> Optional[DerivedDurableLocator]:
    by = to_by(suggestion)
    if by is None:
        return None
    page_context.enter_frame()
    try:
        matches = page_context.find_all(by)
        if len(matches) == 1 and same_element(page_context.driver, matches[0], anchor):
            return DerivedDurableLocator(matches[0], by, suggestion, initial_selector, True, note)
    except Exception:  # noqa: BLE001
        pass
    finally:
        page_context.exit_frame()
    return None


def _derive_durable_locator(page_context: PageContext, anchor: Any, action: Optional[str],
                            tree: Optional[_TreeContext], initial_selector: Optional[str]) -> Optional[DerivedDurableLocator]:
    # (1) does the element stand on its own?
    page_context.enter_frame()
    try:
        own = derive_suggestion_from_element(page_context.driver, anchor)
        if own is not None:
            by = to_by(own)
            candidate = page_context.find_or_none(by) if by else None
            if candidate is not None and same_element(page_context.driver, candidate, anchor):
                return DerivedDurableLocator(candidate, by, own, initial_selector, False, None)
    except Exception:  # noqa: BLE001
        pass
    finally:
        page_context.exit_frame()

    if tree is None:
        return None

    nodes: List[AriaAiNode] = parse_aria_ai_tree(tree.snapshot)
    for ref in tree.candidate_refs:
        target_node = next((n for n in nodes if n.ref == ref), None)
        inferred_role = (target_node.role if target_node and target_node.role and target_node.role != "generic"
                         else infer_role_from_action(action))
        if not inferred_role:
            continue

        if tree.ai_nearby_ref:
            branch_path = find_adjacent_branch_path(nodes, ref, tree.ai_nearby_ref)
            anchor_node = next((n for n in nodes if n.ref == tree.ai_nearby_ref), None)
            anchor_text = (anchor_node.text or anchor_node.name) if anchor_node else None
            if branch_path and anchor_text:
                adj = {"strategy": "adjacent", "anchorText": anchor_text, "role": inferred_role,
                       "anchorClimbLevels": branch_path.anchor_climb_levels or None}
                derived = _verify_structural(page_context, adj, anchor, initial_selector,
                                             "Durable selector anchors on the adjacent label — verify if the page layout changes.")
                if derived:
                    return derived

        texts: List[str] = []
        if tree.ai_nearby_text:
            texts.append(tree.ai_nearby_text)
        for candidate in find_sibling_anchor_texts(nodes, ref):
            if candidate.text != tree.ai_nearby_text:
                texts.append(candidate.text)
        for text in texts:
            for levels in (1, 2):
                near = {"strategy": "near", "anchorText": text, "role": inferred_role, "parentLevels": levels}
                derived = _verify_structural(page_context, near, anchor, initial_selector,
                                             "Durable selector anchors on nearby text — verify if the page layout changes.")
                if derived:
                    return derived
    return None


def get_durable_locator(driver: Any, broken: Locator, action: Optional[str] = None,
                        frame_chain: Optional[List[Locator]] = None) -> Locator:
    """Public counterpart backing ``Bindings.get_durable`` — resolves a locator to a durable
    equivalent using the same logic self-healing uses internally. Raises if nothing durable
    could be derived."""
    page_context = PageContext(driver=driver, frame_chain=list(frame_chain or []))
    page_context.enter_frame()
    try:
        anchor = page_context.find(broken)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("get_durable(): the given locator does not resolve to an element.") from exc
    finally:
        page_context.exit_frame()

    snapshot = _capture_snapshot(page_context)
    tree: Optional[_TreeContext] = None
    if snapshot:
        try:
            ref_attr = anchor.get_dom_attribute(dom_snapshot.REF_ATTRIBUTE)
        except Exception:  # noqa: BLE001
            ref_attr = None
        if ref_attr:
            tree = _TreeContext(snapshot=snapshot, candidate_refs=[ref_attr])

    derived = _derive_durable_locator(page_context, anchor, action or "", tree, str(broken))
    if derived is None:
        raise RuntimeError("get_durable(): could not derive a durable locator for this element.")
    return derived.by


# --------------------------------------------------------------------------------------------------
# Console formatting
# --------------------------------------------------------------------------------------------------


def _format_console_line(report: SelfHealingReport) -> str:
    outcome = "HEALED" if report.healed else "NOT healed"
    meta = [f"provider={report.provider}", f"actionRecovery={'yes' if report.used_action_recovery else 'no'}"]
    if report.suggested_selector:
        meta.append(f'suggested="{report.suggested_selector}"')
    if report.failure_stage:
        meta.append(f"stage={report.failure_stage}")
    if report.token_usage:
        meta.append(format_token_usage(report.token_usage))
    if report.needs_review:
        meta.append("needsReview=yes")
    if report.healed_in_assertion:
        meta.append("assertion=yes")
    tag = "[self-healer][assertion] " if report.healed_in_assertion else "[self-healer] "
    description = f' "{report.description}"' if report.description else ""
    location = f"{report.source_location} — " if report.source_location else ""
    return (f"{tag}{location}{report.kind}.{report.action}{description} -> {outcome} "
            f"[{', '.join(meta)}] — {report.reason.split(chr(10), 1)[0]}")


def _format_attempts_block(attempts: List[HealAttempt]) -> str:
    lines = ["  attempts:"]
    for i, attempt in enumerate(attempts):
        parts = [f"{i + 1}. {attempt.method}", "OK" if attempt.succeeded else "FAILED"]
        if attempt.provider:
            parts.append(f"provider={attempt.provider}")
        if attempt.suggested_selector:
            parts.append(f'tried="{attempt.suggested_selector}"')
        if attempt.stage:
            parts.append(f"stage={attempt.stage}")
        if attempt.error:
            parts.append(f"error: {attempt.error.split(chr(10), 1)[0]}")
        lines.append("    " + "  ".join(parts))
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------------
# heal log
# --------------------------------------------------------------------------------------------------


def _log_eligible_heal(report: SelfHealingReport, suggestion: Optional[dict], used_action_recovery: bool,
                       used_cache: bool, ctx: HealContext) -> None:
    if (not report.healed or not report.source_location
            or (suggestion is None and report.review_note is None) or used_action_recovery):
        return
    location = heal_log.parse_source_location(report.source_location)
    if location is None:
        return
    file_name, line = location

    entry = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "file": file_name,
        "line": line,
        "action": report.action,
        "description": report.description,
        "suggestion": suggestion,
        "test_id": ctx.test_id,
        "test_title": ctx.test_title,
        "used_cache": used_cache,
        "initial_selector": report.initial_selector,
        "needs_review": report.needs_review,
        "review_note": report.review_note,
    }
    if suggestion is not None:
        entry["newLocator"] = generate_replacement_call(suggestion)
    if ctx.raw_variable_name:
        from ..source_locations import locate_locator_declaration
        decl = locate_locator_declaration(report.source_location, ctx.raw_variable_name)
        if decl and decl != report.source_location:
            entry["declarationLocation"] = decl
    heal_log.append_heal_log_entry(entry)


def get_healing_reports() -> List[SelfHealingReport]:
    with _reports_lock:
        return list(_reports)


# --------------------------------------------------------------------------------------------------
# Text heal (scoped-then-full)
# --------------------------------------------------------------------------------------------------


@dataclass
class _TextHealState:
    failure_stage: Optional[str] = None
    healing: Optional[dict] = None
    usage: Optional[TokenUsage] = None
    suggested_selector: Optional[str] = None
    captured_suggestion: Optional[dict] = None
    initial_selector: Optional[str] = None
    needs_review: Optional[bool] = None
    review_note: Optional[str] = None
    used_action_recovery: bool = False


def _maybe_action_recovery(provider: HealProvider, ctx: HealContext, element: Any, replay_error: BaseException,
                           timeout_ms: float, suggested_selector_for_report: Optional[str],
                           attempts: List[HealAttempt], st: _TextHealState) -> None:
    if not is_action_recovery_enabled() or ctx.action is None:
        st.healing = None
        return
    outcome = try_action_recovery(provider, ctx.driver, element, ctx.action, ctx.args, ctx.kwargs,
                                  normalize_error(replay_error), timeout_ms)
    st.usage = sum_token_usage(st.usage, outcome.get("usage"))
    st.used_action_recovery = True
    if outcome.get("healing"):
        healing = outcome["healing"]
        st.healing = {"provider": healing["provider"], "warning": healing["warning"],
                      "suggested_selector": suggested_selector_for_report, "result": healing["result"]}
        st.failure_stage = None
        attempts.append(HealAttempt("action-recovery", provider=provider.name, succeeded=True,
                                    suggested_selector=suggested_selector_for_report))
    else:
        st.healing = None
        st.failure_stage = outcome.get("stage")
        attempts.append(HealAttempt("action-recovery", provider=provider.name, succeeded=False,
                                    stage=outcome.get("stage"),
                                    error=FAILURE_STAGES.get(outcome.get("stage") or "")))


def _safe_future(future: Any) -> Optional[dict]:
    try:
        return future.result()
    except Exception:  # noqa: BLE001
        return None


def _provider_suggest(provider: HealProvider, ctx: HealContext, snapshot_for_prompt: str,
                      timeout_ms: float) -> Optional[dict]:
    return provider.suggest_selector({
        "action": ctx.action,
        "description": ctx.description,
        "aria_snapshot": snapshot_for_prompt,
        "timeout_ms": timeout_ms,
        "raw_name": ctx.raw_variable_name,
        "broken_selector": ctx.original_by_string,
        "context_class": ctx.enclosing_class,
    })


def _attempt_text_heal(provider: HealProvider, page_context: PageContext, ctx: HealContext,
                       full_snapshot: str, result: Optional[dict], scoped: bool, timeout_ms: float,
                       attempts: List[HealAttempt], st: _TextHealState) -> None:
    st.failure_stage = "provider_error"
    if result is None:
        return
    st.usage = sum_token_usage(st.usage, result.get("usage"))
    suggestion = result.get("suggestion")
    if not suggestion or suggestion.get("strategy") == "none":
        st.failure_stage = "ai_declined"
        return

    def _run_replay(element: Any) -> Any:
        with report_module.suppress():
            return ctx.replay(element) if ctx.replay else replay_action(element, ctx.action, ctx.args, ctx.kwargs)

    if suggestion.get("strategy") == "ref":
        built = _build_locator_from_suggestion(page_context, suggestion, ctx.action)
        if built is None:
            st.failure_stage = "unbuildable_suggestion"
            return
        st.failure_stage = "replay_failed"
        derived = _derive_durable_locator(
            page_context, built.element, ctx.action,
            _TreeContext(snapshot=full_snapshot, candidate_refs=[suggestion["ref"]],
                         ai_nearby_ref=suggestion.get("nearbyRef"), ai_nearby_text=suggestion.get("nearbyText")),
            ctx.original_by_string,
        )
        primary = derived.element if derived else built.element
        try:
            used_derived = derived is not None
            try:
                replay_result = _run_replay(primary)
            except Exception:
                if derived is None:
                    raise
                replay_result = _run_replay(built.element)
                used_derived = False
            if used_derived and derived:
                st.captured_suggestion = derived.suggestion
                st.initial_selector = derived.initial_selector
                st.needs_review = derived.needs_review
                st.review_note = derived.review_note
                st.suggested_selector = _describe_suggestion(derived.suggestion)
            else:
                st.captured_suggestion = None
                st.needs_review = True
                st.review_note = ("Healed via a one-shot element reference this run; no durable "
                                  "selector could be derived for future runs.")
                st.suggested_selector = _describe_suggestion(suggestion)
            st.healing = {"provider": provider.name,
                          "warning": f"Recovered using {provider.name} ({st.suggested_selector}).",
                          "suggested_selector": st.suggested_selector, "result": replay_result}
            st.failure_stage = None
            attempts.append(HealAttempt("ref", provider=provider.name, succeeded=True,
                                        suggested_selector=st.suggested_selector, scoped=scoped,
                                        ai_ref=suggestion.get("ref"), ai_nearby_ref=suggestion.get("nearbyRef"),
                                        ai_nearby_text=suggestion.get("nearbyText"), ai_nearby_role=suggestion.get("nearbyRole")))
        except Exception as replay_error:  # noqa: BLE001
            attempts.append(HealAttempt("ref", provider=provider.name, succeeded=False,
                                        suggested_selector=st.suggested_selector, stage="replay_failed",
                                        error=normalize_error(replay_error), scoped=scoped))
            _maybe_action_recovery(provider, ctx, built.element, replay_error, timeout_ms,
                                   st.suggested_selector, attempts, st)
        return

    # structured (non-ref) suggestion
    built = _build_locator_from_suggestion(page_context, suggestion, ctx.action)
    if built is None:
        st.failure_stage = "unbuildable_suggestion"
        return
    st.suggested_selector = _describe_suggestion(built.resolved_suggestion)
    st.captured_suggestion = exclude_ref_strategy(built.resolved_suggestion)
    st.failure_stage = "replay_failed"
    try:
        replay_result = _run_replay(built.element)
        st.healing = {"provider": provider.name,
                      "warning": f"Recovered using {provider.name} ({st.suggested_selector}).",
                      "suggested_selector": st.suggested_selector, "result": replay_result}
        st.failure_stage = None
        attempts.append(HealAttempt("text", provider=provider.name, succeeded=True,
                                    suggested_selector=st.suggested_selector, scoped=scoped))
    except Exception as replay_error:  # noqa: BLE001
        attempts.append(HealAttempt("text", provider=provider.name, succeeded=False,
                                    suggested_selector=st.suggested_selector, stage="replay_failed",
                                    error=normalize_error(replay_error), scoped=scoped))
        _maybe_action_recovery(provider, ctx, built.element, replay_error, timeout_ms,
                               st.suggested_selector, attempts, st)


# --------------------------------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------------------------------

_TRIED_STAGES = {"ai_declined", "unbuildable_suggestion", "replay_failed", "no_snapshot", "provider_error"}


def heal_action_failure(ctx: HealContext) -> HealResult:
    ctx.driver = _unwrap(ctx.driver)
    hint = _tamash.current_hint()
    if hint:
        ctx.description = hint
        ctx.raw_variable_name = hint

    reason = normalize_error(ctx.error)
    healing_enabled = is_healing_enabled()
    reentrant = _healing_in_progress.get()
    actionability_failure = is_actionability_failure(ctx.error) and not is_action_recovery_enabled()
    attempt_healing = healing_enabled and not reentrant and not actionability_failure
    timeout_ms = _effective_timeout()

    if not healing_enabled:
        failure_stage: Optional[str] = "disabled"
    elif reentrant:
        failure_stage = "reentrant"
    elif actionability_failure:
        failure_stage = "not-a-selector-issue"
    else:
        failure_stage = "no_snapshot"

    page_context = _resolve_page_context(ctx) if attempt_healing else None
    page_key = _page_key_of(ctx.driver)
    dom_key = _dom_key_of(ctx.driver)
    negative_skip = (attempt_healing and ctx.by is not None
                     and heal_cache.positive(ctx.by, page_key) is None
                     and heal_cache.recently_declined(ctx.by, dom_key))

    report = SelfHealingReport(
        action=ctx.action or "findElement", kind=ctx.kind, description=ctx.description,
        provider="none", healed=False, warning="", reason=reason,
        source_location=ctx.source_location, test_id=ctx.test_id,
    )

    healing: Optional[dict] = None
    usage: Optional[TokenUsage] = None
    suggested_selector: Optional[str] = None
    provider_name: Optional[str] = None
    used_action_recovery = False
    used_cache = False
    captured_suggestion: Optional[dict] = None
    initial_selector = ctx.original_by_string
    needs_review: Optional[bool] = None
    review_note: Optional[str] = None
    attempts = report.attempts
    snapshot: Optional[str] = None

    guard_token = _healing_in_progress.set(True) if attempt_healing else None
    try:
        def _run_replay(element: Any) -> Any:
            with report_module.suppress():
                return ctx.replay(element) if ctx.replay else replay_action(element, ctx.action, ctx.args, ctx.kwargs)

        # --- pure action-recovery path ---
        if attempt_healing and is_actionability_failure(ctx.error) and ctx.action is not None:
            current = _safe_find(page_context, ctx.by)
            if current is not None:
                provider = get_heal_provider()
                if provider is not None:
                    provider_name = provider.name
                    outcome = try_action_recovery(provider, ctx.driver, current, ctx.action, ctx.args, ctx.kwargs,
                                                  reason, timeout_ms)
                    usage = outcome.get("usage")
                    used_action_recovery = True
                    if outcome.get("healing"):
                        h = outcome["healing"]
                        healing = {"provider": h["provider"], "warning": h["warning"], "suggested_selector": None,
                                   "result": h["result"]}
                        failure_stage = None
                        attempts.append(HealAttempt("action-recovery", provider=provider.name, succeeded=True))
                    else:
                        failure_stage = outcome.get("stage")
                        attempts.append(HealAttempt("action-recovery", provider=provider.name, succeeded=False,
                                                    stage=outcome.get("stage"),
                                                    error=FAILURE_STAGES.get(outcome.get("stage") or "")))
                else:
                    failure_stage = "no_provider"

        # --- positive cache ---
        if attempt_healing and healing is None and page_context is not None and ctx.by is not None:
            hit = heal_cache.positive(ctx.by, page_key)
            if hit is not None:
                element = _safe_find(page_context, hit.healed_locator)
                if element is not None:
                    try:
                        result = _run_replay(element)
                        suggested_selector = hit.described_as
                        captured_suggestion = hit.suggestion if hit.suggestion and exclude_ref_strategy(hit.suggestion) else None
                        used_cache = True
                        healing = {"provider": "cache",
                                   "warning": f"Recovered using a selector healed earlier this run ({hit.described_as}) — no snapshot, no AI.",
                                   "suggested_selector": hit.described_as, "result": result}
                        failure_stage = None
                        attempts.append(HealAttempt("cache", succeeded=True, suggested_selector=hit.described_as))
                    except Exception as exc:  # noqa: BLE001
                        attempts.append(HealAttempt("cache", succeeded=False, suggested_selector=hit.described_as,
                                                    error=normalize_error(exc)))

        # --- negative cache ---
        if attempt_healing and healing is None and negative_skip:
            failure_stage = "recently_declined"
            attempt_healing = False

        # --- disk cache ---
        if attempt_healing and healing is None and page_context is not None and ctx.source_location:
            cached = heal_log.find_cached_suggestion(ctx.source_location)
            if (cached and cached.get("suggestion") and cached.get("initial_selector")
                    and ctx.original_by_string and cached["initial_selector"] != ctx.original_by_string):
                cached = None
            if cached and cached.get("suggestion"):
                built = _build_locator_from_suggestion(page_context, cached["suggestion"], ctx.action)
                if built is not None:
                    desc = _describe_suggestion(built.resolved_suggestion)
                    try:
                        result = _run_replay(built.element)
                        suggested_selector = desc
                        captured_suggestion = exclude_ref_strategy(built.resolved_suggestion)
                        used_cache = True
                        initial_selector = cached.get("initial_selector")
                        needs_review = cached.get("needs_review")
                        review_note = cached.get("review_note")
                        healing = {"provider": "cache",
                                   "warning": f"Recovered using a previously-confirmed selector ({desc}) — no AI call needed.",
                                   "suggested_selector": desc, "result": result}
                        failure_stage = None
                        attempts.append(HealAttempt("cache", succeeded=True, suggested_selector=desc))
                    except Exception as exc:  # noqa: BLE001
                        attempts.append(HealAttempt("cache", succeeded=False, suggested_selector=desc,
                                                    error=normalize_error(exc)))

        snapshot = _capture_snapshot(page_context) if (attempt_healing and healing is None) else None

        if attempt_healing and healing is None and page_context is not None:
            provider = get_heal_provider()
            if provider is None:
                failure_stage = "no_provider"
            else:
                provider_name = provider.name
                if snapshot:
                    scoped_phrase = strip_generic_role_suffix(ctx.description) if ctx.description else None
                    scoped_snapshot = (extract_scoped_snapshot(snapshot, scoped_phrase)
                                       if scoped_phrase else None)
                    st = _TextHealState(failure_stage=failure_stage)
                    parallel = env.get_bool("HEALER_PARALLEL", False) and scoped_snapshot is not None

                    if parallel:
                        # Race the two provider calls (pure network) concurrently; the live
                        # build+replay below stays strictly sequential (one WebDriver).
                        from concurrent.futures import ThreadPoolExecutor
                        with ThreadPoolExecutor(max_workers=2) as pool:
                            f_scoped = pool.submit(_provider_suggest, provider, ctx, scoped_snapshot, timeout_ms)
                            f_full = pool.submit(_provider_suggest, provider, ctx, snapshot, timeout_ms)
                            scoped_result = _safe_future(f_scoped)
                            full_result = _safe_future(f_full)
                        _attempt_text_heal(provider, page_context, ctx, snapshot, scoped_result, True, timeout_ms, attempts, st)
                        if st.healing is None:
                            _attempt_text_heal(provider, page_context, ctx, snapshot, full_result, False, timeout_ms, attempts, st)
                    else:
                        if scoped_snapshot:
                            scoped_result = _provider_suggest(provider, ctx, scoped_snapshot, timeout_ms)
                            _attempt_text_heal(provider, page_context, ctx, snapshot, scoped_result, True, timeout_ms, attempts, st)
                        if st.healing is None:
                            full_result = _provider_suggest(provider, ctx, snapshot, timeout_ms)
                            _attempt_text_heal(provider, page_context, ctx, snapshot, full_result, False, timeout_ms, attempts, st)
                    healing = st.healing
                    usage = sum_token_usage(usage, st.usage)
                    suggested_selector = st.suggested_selector or suggested_selector
                    captured_suggestion = st.captured_suggestion
                    if st.initial_selector is not None:
                        initial_selector = st.initial_selector
                    needs_review = st.needs_review
                    review_note = st.review_note
                    used_action_recovery = used_action_recovery or st.used_action_recovery
                    failure_stage = None if st.healing is not None else st.failure_stage
    finally:
        if guard_token is not None:
            _healing_in_progress.reset(guard_token)

    # --- assemble ---
    if healing is not None:
        warning = healing["warning"]
    elif failure_stage == "replay_failed":
        warning = f'Action "{report.action}" failed: {reason}. AI suggested "{suggested_selector}", but that failed too.'
    elif failure_stage and failure_stage in FAILURE_STAGES:
        warning = f'Action "{report.action}" failed: {reason}. ({FAILURE_STAGES[failure_stage]})'
    else:
        warning = f'Action "{report.action}" failed: {reason}.'

    report.provider = (healing["provider"] if healing else
                       (provider_name or ("skipped" if actionability_failure else ("none" if healing_enabled else "disabled"))))
    report.token_usage = usage
    report.healed = healing is not None
    report.warning = warning
    report.suggested_selector = (healing.get("suggested_selector") if healing else suggested_selector)
    report.failure_stage = failure_stage
    report.used_action_recovery = used_action_recovery
    report.initial_selector = initial_selector
    report.needs_review = needs_review
    report.review_note = review_note
    report.healed_in_assertion = report.healed and ctx.in_assertion
    report.aria_snapshot_for_report = None if report.healed else snapshot
    if report.healed_in_assertion and assertion_mode() == "warn":
        _note_assertion_heal(ctx.test_id)

    with _reports_lock:
        _reports.append(report)

    quiet = (ctx.in_wait and not report.healed
             and (report.failure_stage == "recently_declined" or heal_cache.fail_count(ctx.by) <= 6))
    show_attempts = len(attempts) > 1 or (len(attempts) == 1 and not attempts[0].succeeded)
    if not quiet:
        print(_format_console_line(report))
        if show_attempts:
            print(_format_attempts_block(attempts))

    _log_eligible_heal(report, captured_suggestion, used_action_recovery, used_cache, ctx)

    # feed heal cache
    if ctx.by is not None and report.failure_stage != "reentrant":
        if report.healed and not used_cache and captured_suggestion and exclude_ref_strategy(captured_suggestion):
            healed_by = to_by(captured_suggestion)
            if healed_by is not None:
                heal_cache.record_positive(ctx.by, page_key, healed_by, report.suggested_selector, captured_suggestion)
        elif not report.healed and report.failure_stage in _TRIED_STAGES:
            heal_cache.record_declined(ctx.by, dom_key)

    return HealResult(report, report.healed, healing["result"] if healing else None)


def _unwrap(obj: Any) -> Any:
    from ..bindings import unwrap
    return unwrap(obj)
