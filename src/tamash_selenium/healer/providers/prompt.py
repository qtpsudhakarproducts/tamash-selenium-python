"""Shared system prompts, user-prompt builders, and lenient JSON response parsers for every AI
provider. Selenium-flavoured: the snapshot is a JS-serialised DOM accessibility tree and the
fallback strategies are native Selenium locators (id / name / css / xpath / link text).

Port of the Java ``Prompt.java`` with ``tamash-playwright-python``'s tolerant JSON extraction.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from .types import ActionTactic, SuggestActionTacticInput, SuggestSelectorInput, TokenUsage

MAX_SNAPSHOT_CHARS = 16000

SYSTEM_PROMPT = """You are a Selenium self-healing assistant.
You will be given a DOM accessibility snapshot of a web page, an action that just failed, and a human description of the element the test intended to interact with. Every element in the snapshot has its own [ref=eN] id, and where available its on-screen position as [box=x,y,width,height] in CSS pixels. The snapshot preserves the real parent/child/sibling structure of the page — read it as a tree, not a flat list.
Pick the single best-matching element and respond with strict JSON only (no markdown, no prose):
{"strategy":"ref","ref":"<the [ref=...] id of the target element itself>","nearbyRef":"<optional: the [ref=...] id of a nearby label/heading/element that told you what this is, if it has one>","nearbyText":"<optional: the literal nearby text that told you what this is, if it's plain text with no ref of its own>","nearbyRole":"<optional: that nearby text/element's own role in the snapshot, e.g. \\"text\\", \\"legend\\", \\"heading\\">"}
Prefer "ref" whenever you can identify the target element anywhere in the snapshot tree, even if it has no accessible name of its own (a plain, unlabelled "textbox" or "generic" node is a perfectly good ref to pick — a separate step on our side reads the tree structure around it to build a resilient permanent selector, the same way a sighted user would read a nearby label before writing one by hand). When the target has no accessible name of its own, also report whatever nearby label/heading/text actually told you what it is — include nearbyRef if that nearby thing has its own [ref=...], or nearbyText (plus its nearbyRole) if it's plain text with none. Include whichever apply; omit any you don't have.
Only if NOTHING in the snapshot plausibly matches the description, fall back to one of:
{"strategy":"id","id":"<the element's id attribute>"}
{"strategy":"name","name":"<the element's name attribute>"}
{"strategy":"css","css":"<a CSS selector>"}
{"strategy":"xpath","xpath":"<an XPath expression>"}
{"strategy":"text","text":"<exact visible text of a link or button>"}
{"strategy":"near","anchorText":"<nearby visible text>","role":"<html tag or aria role of the TARGET element itself, e.g. input, button, select>"}
{"strategy":"none"}
Never invent a ref, element, attribute, or id that isn't literally in the snapshot."""


def build_user_prompt(input: SuggestSelectorInput) -> str:
    snapshot = input.get("aria_snapshot") or ""
    if len(snapshot) > MAX_SNAPSHOT_CHARS:
        snapshot = snapshot[:MAX_SNAPSHOT_CHARS] + "\n... (truncated)"

    description = input.get("description")
    lines = [
        f"Failed action: {input.get('action') or '(unknown — element not found)'}",
        "",
        f"Element description: {description or '(none provided)'}",
    ]
    _append_hint(lines, "Locator variable/field name", input.get("raw_name"), description)
    _append_hint(lines, "Broken selector (no longer matches)", input.get("broken_selector"), description)
    _append_hint(lines, "Defined in", input.get("context_class"), None)
    lines += ["", "DOM snapshot:", "", snapshot]
    return "\n".join(lines)


def _append_hint(lines: list, label: str, value: Optional[str], description: Optional[str]) -> None:
    if not value or not str(value).strip():
        return
    v = str(value).strip()
    if description and description.strip().lower() == v.lower():
        return
    lines.append(f"{label}: {v}")


ACTION_RECOVERY_SYSTEM_PROMPT = """You are a Selenium self-healing assistant.
An element was already correctly located, but the action on it failed for the reason described below — this is NOT a selector problem, so do not suggest one. Given the error, choose the single tactic most likely to help:
{"tactic":"scroll"} — the element may be outside the current viewport; scroll it into view, then retry the same action.
{"tactic":"force"} — the error looks transient or overly strict rather than something genuinely blocking the interaction; retry the same action via a direct JavaScript / Actions call that bypasses Selenium's standard interactability checks. Note: this still targets the element itself, so it will NOT help if another element is genuinely covering this one — use "dispatch" for that instead.
{"tactic":"wait"} — the error suggests something transient (an animation or transition still settling, content still loading); wait briefly, then retry the same action.
{"tactic":"dispatch"} — the element is genuinely covered/intercepted by another element on top of it, or force did not help; dispatch the underlying DOM event directly on the element via JavaScript instead of a real interaction. Last resort, since it skips real hit-testing entirely.
{"tactic":"none"} — none of the above would plausibly help.
Respond with strict JSON only (no markdown, no prose), exactly one of the five objects above."""


def build_action_recovery_user_prompt(input: SuggestActionTacticInput) -> str:
    return f"Failed action: {input['action']}\n\nError: {input['error_message']}"


# --------------------------------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------------------------------

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")

_VALID_STRATEGIES = {
    "none": [],
    "ref": ["ref"],
    "id": ["id"],
    "name": ["name"],
    "css": ["css"],
    "xpath": ["xpath"],
    "text": ["text"],
    "near": ["anchorText", "role"],
    "adjacent": ["anchorText", "role"],
    "scoped": ["containerRole", "role"],
    "containing": ["role", "anchorText"],
}


def _try_parse_object(s: str) -> Optional[dict]:
    try:
        parsed = json.loads(s)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_json_object(content: str) -> Optional[dict]:
    whole = _try_parse_object(content.strip())
    if whole is not None:
        return whole

    spans: list = []
    depth = 0
    start = -1
    in_string = False
    i = 0
    while i < len(content):
        ch = content[i]
        if in_string:
            if ch == "\\":
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start != -1:
                spans.append(content[start : i + 1])
                start = -1
        i += 1

    for span in reversed(spans):
        obj = _try_parse_object(span)
        if obj is not None:
            return obj

    match = _JSON_OBJECT_RE.search(content)
    return _try_parse_object(match.group(0)) if match else None


def parse_suggestion(content: str) -> Optional[dict]:
    parsed = _parse_json_object(content)
    if parsed is None or "strategy" not in parsed:
        return None

    strategy = parsed.get("strategy")
    # A `role` reply despite the prompt — fold into an approximate css/xpath.
    if strategy == "role" and isinstance(parsed.get("role"), str):
        role = parsed["role"]
        name = parsed.get("name")
        if isinstance(name, str) and name:
            return {"strategy": "xpath",
                    "xpath": f"//*[@role='{role}' or local-name()='{role}']"
                             f"[normalize-space(.)={_xpath_literal(name)} or @aria-label={_xpath_literal(name)}]"}
        return {"strategy": "css", "css": f"[role='{role}']"}

    required_fields = _VALID_STRATEGIES.get(strategy)
    if required_fields is None:
        return None
    if strategy == "none":
        return parsed
    for field_name in required_fields:
        if not isinstance(parsed.get(field_name), str):
            return None
    return parsed


def _xpath_literal(value: str) -> str:
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    return "concat('" + value.replace("'", "', \"'\", '") + "')"


_ACTION_TACTICS = {"scroll", "force", "wait", "dispatch", "none"}


def parse_action_tactic_suggestion(content: str) -> Optional[ActionTactic]:
    parsed = _parse_json_object(content)
    if parsed is None or "tactic" not in parsed:
        return None
    tactic = parsed.get("tactic")
    return tactic if isinstance(tactic, str) and tactic in _ACTION_TACTICS else None


def extract_openai_compatible_usage(payload: dict) -> Optional[TokenUsage]:
    usage = payload.get("usage")
    if not usage:
        return None
    return {
        "input_tokens": usage.get("prompt_tokens"),
        "output_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
    }
