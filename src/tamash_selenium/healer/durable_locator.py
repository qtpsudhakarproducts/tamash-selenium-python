"""ARIA-tree reading + Selenium locator derivation.

The tree-reading half (:func:`parse_aria_ai_tree`, :func:`find_adjacent_branch_path`,
:func:`find_sibling_anchor_texts`, :func:`extract_scoped_snapshot`, :func:`find_rule_based_match`)
is DOM-agnostic and carried over from ``tamash-playwright-python``'s ``durable_locator.py`` almost
verbatim — it parses the YAML tree emitted by :mod:`tamash_selenium.healer.dom_snapshot`.

The Selenium half — :func:`same_element` (JS identity check), :func:`derive_suggestion_from_element`
(a stable locator from a resolved element), :func:`to_by` (an ``AiSuggestion`` -> a real ``(by,
value)`` tuple), and :func:`generate_replacement_call` (an ``AiSuggestion`` -> the Python locator
source ``apply-heals`` writes) — is ported from the Java ``DurableLocator.java``.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from selenium.webdriver.common.by import By

Locator = Tuple[str, str]

REF_ATTRIBUTE = "data-tamash-ref"


# --------------------------------------------------------------------------------------------------
# DOM identity
# --------------------------------------------------------------------------------------------------


def same_element(driver: Any, a: Any, b: Any) -> bool:
    """DOM identity, not markup or position: two elements can share identical outerHTML or bounding
    box while being genuinely different nodes."""
    if a is None or b is None:
        return False
    try:
        return bool(driver.execute_script("return arguments[0] === arguments[1];", a, b))
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------------------------------
# ARIA AI tree parsing (verbatim from the Playwright port)
# --------------------------------------------------------------------------------------------------


@dataclass
class AriaAiNode:
    depth: int
    line_index: int
    role: Optional[str] = None
    name: Optional[str] = None
    ref: Optional[str] = None
    box: Optional[dict] = None
    text: Optional[str] = None


_LINE_RE = re.compile(r"^(\s*)-\s(.*)$")
_TEXT_RE = re.compile(r"^text:\s?(.*)$")
_REF_RE = re.compile(r"\[ref=([^\]]+)\]")
_BOX_RE = re.compile(r"\[box=(-?[\d.]+),(-?[\d.]+),(-?[\d.]+),(-?[\d.]+)\]")
_NAME_RE = re.compile(r'^(.+?)\s*"([^"]*)"$')
_TRAILING_RE = re.compile(r'^:\s*(?:"([^"]*)"|(.+))$')


def parse_aria_ai_tree(snapshot: Optional[str]) -> List[AriaAiNode]:
    nodes: List[AriaAiNode] = []
    if not snapshot:
        return nodes

    for line_index, raw_line in enumerate(snapshot.split("\n")):
        match = _LINE_RE.match(raw_line)
        if not match:
            continue
        depth = len(match.group(1)) // 2
        content = match.group(2)

        text_match = _TEXT_RE.match(content)
        if text_match:
            nodes.append(AriaAiNode(depth=depth, line_index=line_index, text=text_match.group(1).strip()))
            continue

        if content.startswith("/"):
            continue
        if len(content) >= 2 and content[0] == "'" and content[-1] == "'":
            content = content[1:-1]

        ref_match = _REF_RE.search(content)
        if not ref_match:
            continue

        box_match = _BOX_RE.search(content)
        box = (
            {
                "x": float(box_match.group(1)),
                "y": float(box_match.group(2)),
                "width": float(box_match.group(3)),
                "height": float(box_match.group(4)),
            }
            if box_match
            else None
        )

        first_bracket = content.find("[")
        head = (content if first_bracket == -1 else content[:first_bracket]).strip()
        name_match = _NAME_RE.match(head)
        role = (name_match.group(1) if name_match else re.sub(r":$", "", head)).strip() or None

        last_bracket_end = content.rfind("]")
        trailing = "" if last_bracket_end == -1 else content[last_bracket_end + 1 :]
        trailing_match = _TRAILING_RE.match(trailing)
        trailing_text = (
            (trailing_match.group(1) if trailing_match.group(1) is not None else trailing_match.group(2)).strip()
            if trailing_match
            else None
        )

        name = name_match.group(2) if name_match else trailing_text
        nodes.append(AriaAiNode(depth=depth, line_index=line_index, role=role, name=name, ref=ref_match.group(1), box=box))

    return nodes


# --------------------------------------------------------------------------------------------------
# Role inference / suffix stripping
# --------------------------------------------------------------------------------------------------


def infer_role_from_action(action: Optional[str]) -> Optional[str]:
    if not action:
        return None
    if action in ("send_keys", "fill", "type", "clear"):
        return "textbox"
    if action == "submit":
        return "button"
    return None


_GENERIC_ROLE_SUFFIX_RE = re.compile(
    r"\s+(text ?box|input|field|drop ?down|select|combo ?box|button|link|check ?box|radio( ?button)?|label|heading|icon|list ?box|menu)$",
    re.IGNORECASE,
)


def strip_generic_role_suffix(description: Optional[str]) -> Optional[str]:
    if description is None:
        return None
    return _GENERIC_ROLE_SUFFIX_RE.sub("", description).strip()


# --------------------------------------------------------------------------------------------------
# Sibling / adjacent tree search (verbatim from the Playwright port)
# --------------------------------------------------------------------------------------------------


@dataclass
class SiblingAnchorCandidate:
    text: str
    levels_up: int


def _find_ancestor(nodes: List[AriaAiNode], from_index: int, want_depth: int) -> Optional[int]:
    for i in range(from_index - 1, -1, -1):
        if nodes[i].depth == want_depth:
            return i
        if nodes[i].depth < want_depth:
            return None
    return None


def find_sibling_anchor_texts(nodes: List[AriaAiNode], target_ref: str, max_levels: int = 2) -> List[SiblingAnchorCandidate]:
    target_index = next((i for i, n in enumerate(nodes) if n.ref == target_ref), -1)
    if target_index == -1:
        return []
    target = nodes[target_index]

    results: List[SiblingAnchorCandidate] = []
    ancestor_index = target_index
    ancestor_depth = target.depth

    for levels_up in range(1, max_levels + 1):
        parent_index = _find_ancestor(nodes, ancestor_index, ancestor_depth - 1)
        if parent_index is None:
            break
        parent_depth = nodes[parent_index].depth
        sibling_depth = ancestor_depth

        candidates: List[Tuple[str, int]] = []
        i = parent_index + 1
        while i < len(nodes):
            if nodes[i].depth <= parent_depth:
                break
            if nodes[i].depth != sibling_depth:
                i += 1
                continue
            if nodes[i].ref == target_ref:
                i += 1
                continue
            if nodes[i].name:
                candidates.append((nodes[i].name, nodes[i].line_index))
            if nodes[i].text:
                candidates.append((nodes[i].text, nodes[i].line_index))
            i += 1

        candidates.sort(key=lambda c: abs(c[1] - target.line_index))
        results.extend(SiblingAnchorCandidate(text=text, levels_up=levels_up) for text, _ in candidates)

        ancestor_index = parent_index
        ancestor_depth = parent_depth

    seen: set = set()
    filtered: List[SiblingAnchorCandidate] = []
    for candidate in results:
        if candidate.text in seen:
            continue
        seen.add(candidate.text)
        filtered.append(candidate)
    return filtered


@dataclass
class AdjacentBranchPath:
    anchor_climb_levels: int


def find_adjacent_branch_path(nodes: List[AriaAiNode], target_ref: str, anchor_ref: str) -> Optional[AdjacentBranchPath]:
    target_index = next((i for i, n in enumerate(nodes) if n.ref == target_ref), -1)
    anchor_index = next((i for i, n in enumerate(nodes) if n.ref == anchor_ref), -1)
    if target_index == -1 or anchor_index == -1:
        return None

    def ancestor_chain(index: int) -> List[int]:
        chain = [index]
        depth = nodes[index].depth
        for i in range(index - 1, -1, -1):
            if nodes[i].depth < depth:
                chain.append(i)
                depth = nodes[i].depth
        return chain

    anchor_chain = ancestor_chain(anchor_index)
    target_chain = ancestor_chain(target_index)
    target_chain_set = set(target_chain)

    for i, anchor_chain_index in enumerate(anchor_chain):
        if anchor_chain_index not in target_chain_set:
            continue
        target_chain_idx = target_chain.index(anchor_chain_index)
        if i == 0 and target_chain_idx == 0:
            return None
        if i == 0 or target_chain_idx == 0:
            return None

        anchor_branch_index = anchor_chain[i - 1]
        target_branch_index = target_chain[target_chain_idx - 1]
        branch_depth = nodes[anchor_branch_index].depth

        if nodes[target_branch_index].depth != branch_depth or target_branch_index <= anchor_branch_index:
            return None
        for k in range(anchor_branch_index + 1, target_branch_index):
            if nodes[k].depth <= branch_depth:
                return None
        return AdjacentBranchPath(anchor_climb_levels=nodes[anchor_index].depth - branch_depth)

    return None


def extract_scoped_snapshot(full_snapshot_text: str, phrase: str) -> Optional[str]:
    nodes = parse_aria_ai_tree(full_snapshot_text)
    needle = phrase.lower()
    matches = [n for n in nodes if (n.text and needle in n.text.lower()) or (n.name and needle in n.name.lower())]
    if len(matches) != 1:
        return None
    match_index = nodes.index(matches[0])

    included: set = set()

    def include_subtree(i: int) -> None:
        depth = nodes[i].depth
        included.add(i)
        for k in range(i + 1, len(nodes)):
            if nodes[k].depth <= depth:
                break
            included.add(k)

    include_subtree(match_index)
    idx = match_index
    depth = nodes[match_index].depth
    while depth > 0:
        parent_index: Optional[int] = None
        for k in range(idx - 1, -1, -1):
            if nodes[k].depth == depth - 1:
                parent_index = k
                break
            if nodes[k].depth < depth - 1:
                break
        if parent_index is None:
            break
        included.add(parent_index)
        for k in range(parent_index + 1, len(nodes)):
            if nodes[k].depth <= depth - 1:
                break
            if nodes[k].depth == depth:
                include_subtree(k)
        idx = parent_index
        depth -= 1

    included_lines = {nodes[i].line_index for i in included}
    return "\n".join(line for line_index, line in enumerate(full_snapshot_text.split("\n")) if line_index in included_lines)


# --------------------------------------------------------------------------------------------------
# Rule-based matching (for the `tamash` provider) — verbatim from the Playwright port
# --------------------------------------------------------------------------------------------------

_INTERACTIVE_ROLES = {"button", "link", "checkbox", "radio", "combobox", "textbox", "switch", "tab", "menuitem", "option"}
_ROLE_SYNONYMS = {"dropdown": "combobox", "select": "combobox", "radio button": "radio"}


def _normalize_role_for_match(role: Optional[str]) -> Optional[str]:
    if not role:
        return None
    key = role.lower().strip()
    return _ROLE_SYNONYMS.get(key, key)


def _role_is_plausible_target(actual_role: Optional[str], expected_role: Optional[str]) -> bool:
    actual = _normalize_role_for_match(actual_role)
    if not actual:
        return False
    if not expected_role:
        return actual in _INTERACTIVE_ROLES
    return actual == _normalize_role_for_match(expected_role)


def find_rule_based_match(nodes: List[AriaAiNode], phrase: str, expected_role: Optional[str]) -> dict:
    needle = phrase.lower()
    matches = [n for n in nodes if (n.text and needle in n.text.lower()) or (n.name and needle in n.name.lower())]

    if not matches:
        tokens = [w for w in re.split(r"[^0-9A-Za-z]+", needle) if len(w) >= 2 and w not in _MATCH_STOPWORDS]
        if tokens:
            for n in nodes:
                hay = ((n.name or "") + " " + (n.text or "")).lower()
                if hay.strip() and all(t in hay for t in tokens):
                    matches.append(n)

    real_candidates = [n for n in matches if n.ref and _role_is_plausible_target(n.role, expected_role)]
    if len(real_candidates) == 1:
        return {"strategy": "ref", "ref": real_candidates[0].ref}
    if len(real_candidates) > 1:
        return {"strategy": "none"}

    if len(matches) != 1:
        return {"strategy": "none"}
    anchor = matches[0]
    anchor_index = nodes.index(anchor)

    idx = anchor_index
    depth = anchor.depth
    levels_up = 1
    while levels_up <= 2 and depth > 0:
        parent_index = _find_ancestor(nodes, idx, depth - 1)
        if parent_index is None:
            break
        parent_depth = nodes[parent_index].depth
        candidates: List[AriaAiNode] = []
        for i in range(parent_index + 1, len(nodes)):
            if nodes[i].depth <= parent_depth:
                break
            if i == anchor_index:
                continue
            if nodes[i].ref and _role_is_plausible_target(nodes[i].role, expected_role):
                candidates.append(nodes[i])
        if len(candidates) == 1:
            target = candidates[0]
            if anchor.ref:
                return {"strategy": "ref", "ref": target.ref, "nearbyRef": anchor.ref}
            return {"strategy": "ref", "ref": target.ref, "nearbyText": anchor.text or anchor.name,
                    "nearbyRole": anchor.role or "text"}
        if len(candidates) > 1:
            return {"strategy": "none"}
        idx = parent_index
        depth = parent_depth
        levels_up += 1

    return {"strategy": "none"}


_MATCH_STOPWORDS = {
    "the", "a", "an", "field", "input", "box", "textbox", "button", "link", "icon",
    "dropdown", "select", "checkbox", "radio", "label", "element", "control",
}


# --------------------------------------------------------------------------------------------------
# Positional-selector detection
# --------------------------------------------------------------------------------------------------

_POSITIONAL_RE = re.compile(r"\[\d+\]\s*$|:nth-child\(|:nth-of-type\(|following-sibling::\*\[1\]")


def is_positional_selector_text(selector_text: Optional[str]) -> bool:
    return bool(selector_text and _POSITIONAL_RE.search(selector_text))


# --------------------------------------------------------------------------------------------------
# Deriving a stable locator from a resolved element (from Java DurableLocator)
# --------------------------------------------------------------------------------------------------

_AUTO_ID_RE = re.compile(
    r"^(:r[0-9a-z]+:|mui-\d+|radix-|headlessui-|react-|ember\d+|ext-gen\d+|yui_|[0-9a-f]{8,}$).*|.*[-_]\d{3,}$",
    re.IGNORECASE,
)
_TESTID_ATTRS = ("data-testid", "data-test", "data-test-id", "data-cy", "data-qa")
_STACKABLE_ATTRS = ("name", "type", "role", "placeholder", "aria-label", "title", "data-name")


def looks_auto_generated(value: Optional[str]) -> bool:
    if value is None or not value.strip():
        return True
    if len(value) > 40:
        return True
    return bool(_AUTO_ID_RE.match(value))


def _attr(element: Any, name: str) -> Optional[str]:
    try:
        value = element.get_dom_attribute(name)
        if value is not None:
            return value
    except Exception:  # noqa: BLE001
        pass
    try:
        return element.get_attribute(name)
    except Exception:  # noqa: BLE001
        return None


def _safe_tag(element: Any) -> Optional[str]:
    try:
        return element.tag_name.lower() if element.tag_name else None
    except Exception:  # noqa: BLE001
        return None


def _count_css(driver: Any, css: str) -> int:
    try:
        return len(driver.find_elements(By.CSS_SELECTOR, css))
    except Exception:  # noqa: BLE001
        return -1


def _count_xpath(driver: Any, xpath: str) -> int:
    try:
        return len(driver.find_elements(By.XPATH, xpath))
    except Exception:  # noqa: BLE001
        return -1


def _css_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _css_escape(ident: str) -> str:
    return re.sub(r"([^A-Za-z0-9_-])", r"\\\1", ident)


def _stacked_attribute_css(element: Any, tag: Optional[str]) -> Optional[str]:
    parts = [tag or "*"]
    used = 0
    for attr in _STACKABLE_ATTRS:
        value = _attr(element, attr)
        if value and value.strip() and len(value) <= 60 and not looks_auto_generated(value):
            parts.append(f"[{attr}={_css_quote(value)}]")
            used += 1
            if used == 3:
                break
    return "".join(parts) if used >= 2 else None


def derive_suggestion_from_element(driver: Any, element: Any) -> Optional[dict]:
    """Inspects a resolved element for a stable identity. Returns ``None`` when nothing durable
    stands on its own (the caller then widens to structural near/adjacent anchoring)."""
    if element is None:
        return None
    try:
        id_attr = _attr(element, "id")
        if id_attr and id_attr.strip() and not looks_auto_generated(id_attr) \
                and _count_css(driver, "#" + _css_escape(id_attr)) == 1:
            return {"strategy": "id", "id": id_attr}

        name = _attr(element, "name")
        if name and name.strip() and _count_css(driver, f"[name={_css_quote(name)}]") == 1:
            return {"strategy": "name", "name": name}

        for attr in _TESTID_ATTRS:
            value = _attr(element, attr)
            if value and value.strip():
                css = f"[{attr}={_css_quote(value)}]"
                if _count_css(driver, css) == 1:
                    return {"strategy": "css", "css": css}

        aria_label = _attr(element, "aria-label")
        if aria_label and aria_label.strip():
            css = f"[aria-label={_css_quote(aria_label)}]"
            if _count_css(driver, css) == 1:
                return {"strategy": "css", "css": css}

        placeholder = _attr(element, "placeholder")
        if placeholder and placeholder.strip():
            css = f"[placeholder={_css_quote(placeholder)}]"
            if _count_css(driver, css) == 1:
                return {"strategy": "css", "css": css}

        tag = _safe_tag(element)
        if tag == "a":
            try:
                link_text = (element.text or "").strip()
            except Exception:  # noqa: BLE001
                link_text = ""
            if link_text and len(link_text) <= 60 \
                    and _count_xpath(driver, f"//a[normalize-space(.)={xpath_literal(link_text)}]") == 1:
                return {"strategy": "text", "text": link_text}

        cls = _attr(element, "class")
        if cls and cls.strip():
            classes = [c for c in cls.split() if re.match(r"[A-Za-z_][\w-]*$", c) and not looks_auto_generated(c)][:3]
            if classes:
                combo = (tag or "") + "." + ".".join(classes)
                if not combo.endswith(".") and _count_css(driver, combo) == 1:
                    return {"strategy": "css", "css": combo}

        stacked = _stacked_attribute_css(element, tag)
        if stacked and _count_css(driver, stacked) == 1:
            return {"strategy": "css", "css": stacked}
    except Exception:  # noqa: BLE001
        return None
    return None


# --------------------------------------------------------------------------------------------------
# AiSuggestion -> By  /  -> source text
# --------------------------------------------------------------------------------------------------


def xpath_literal(value: Optional[str]) -> str:
    if value is None:
        return "''"
    if "'" not in value:
        return f"'{value}'"
    if '"' not in value:
        return f'"{value}"'
    parts = value.split("'")
    return "concat(" + ', "\'", '.join(f"'{p}'" for p in parts) + ")"


def role_node_test(role: Optional[str]) -> str:
    if role is None:
        return "*"
    key = re.sub(r"\s+", "", role.lower())
    if key in ("textbox", "input"):
        return ("*[self::input[not(@type) or @type='text' or @type='email' or @type='password' "
                "or @type='search' or @type='tel' or @type='url' or @type='number'] or self::textarea]")
    if key == "button":
        return "*[self::button or self::input[@type='button' or @type='submit' or @type='reset'] or @role='button']"
    if key == "checkbox":
        return "input[@type='checkbox']"
    if key in ("radio", "radiobutton"):
        return "input[@type='radio']"
    if key in ("combobox", "dropdown", "select", "listbox"):
        return "*[self::select or @role='combobox' or @role='listbox']"
    if key == "link":
        return "a"
    if key == "heading":
        return "*[self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6 or @role='heading']"
    safe = re.sub(r"[^a-z0-9-]", "", role.lower())
    return "*" if not safe else f"*[local-name()='{safe}' or @role='{safe}']"


def _near_xpath(anchor_text: str, role: Optional[str], parent_levels: int) -> str:
    xpath = f"(//*[normalize-space(text())={xpath_literal(anchor_text)}])[1]"
    xpath += "/parent::*" * max(1, parent_levels)
    return xpath + "/descendant-or-self::" + role_node_test(role)


def _adjacent_xpath(anchor_text: str, role: Optional[str], climb: int) -> str:
    xpath = f"(//*[normalize-space(text())={xpath_literal(anchor_text)}])[1]"
    xpath += "/parent::*" * climb
    return xpath + "/following-sibling::*[1]/descendant-or-self::" + role_node_test(role)


def _scoped_xpath(container_role: Optional[str], container_name: Optional[str],
                  role: Optional[str], name: Optional[str]) -> str:
    container = "//" + role_node_test(container_role)
    if container_name and container_name.strip():
        container += (f"[@aria-label={xpath_literal(container_name)} "
                      f"or .//*[normalize-space(text())={xpath_literal(container_name)}]]")
    target = "descendant::" + role_node_test(role)
    if name and name.strip():
        target += f"[@aria-label={xpath_literal(name)} or normalize-space(.)={xpath_literal(name)}]"
    return container + "/" + target


def to_by(suggestion: Optional[dict]) -> Optional[Locator]:
    """Builds a real ``(by, value)`` tuple from a persistable (or ``ref``) suggestion. ``None`` for
    ``none`` / an unrenderable shape."""
    if suggestion is None:
        return None
    strategy = suggestion.get("strategy")
    if strategy == "ref":
        return (By.CSS_SELECTOR, f"[{REF_ATTRIBUTE}='{suggestion['ref']}']")
    if strategy == "id":
        return (By.ID, suggestion["id"])
    if strategy == "name":
        return (By.NAME, suggestion["name"])
    if strategy == "css":
        return (By.CSS_SELECTOR, suggestion["css"])
    if strategy == "xpath":
        return (By.XPATH, suggestion["xpath"])
    if strategy == "text":
        text = suggestion["text"]
        return (By.XPATH,
                f"//*[self::a or self::button][normalize-space(.)={xpath_literal(text)}]"
                f" | //*[normalize-space(text())={xpath_literal(text)}]")
    if strategy == "near":
        return (By.XPATH, _near_xpath(suggestion["anchorText"], suggestion.get("role"),
                                      suggestion.get("parentLevels") or 1))
    if strategy == "adjacent":
        return (By.XPATH, _adjacent_xpath(suggestion["anchorText"], suggestion.get("role"),
                                          suggestion.get("anchorClimbLevels") or 0))
    if strategy == "scoped":
        return (By.XPATH, _scoped_xpath(suggestion.get("containerRole"), suggestion.get("containerName"),
                                        suggestion.get("role"), suggestion.get("name")))
    if strategy == "containing":
        return (By.XPATH, "//" + role_node_test(suggestion.get("role"))
                + f"[contains(normalize-space(.), {xpath_literal(suggestion['anchorText'])})]")
    if strategy == "normalized":
        code = suggestion.get("code")
        if not code:
            return None
        stripped = code.strip()
        return (By.XPATH, code) if stripped.startswith(("/", "(")) else (By.CSS_SELECTOR, code)
    return None


_BY_CONST = {
    "id": "By.ID", "name": "By.NAME", "css selector": "By.CSS_SELECTOR", "xpath": "By.XPATH",
    "link text": "By.LINK_TEXT", "partial link text": "By.PARTIAL_LINK_TEXT",
    "class name": "By.CLASS_NAME", "tag name": "By.TAG_NAME",
}


def generate_replacement_call(suggestion: Optional[dict]) -> Optional[str]:
    """Turns a persistable suggestion into the exact Python locator tuple it describes —
    ``(By.ID, "username")`` — the source ``apply-heals`` writes and the string shown in
    console lines / reports. ``None`` for ``ref``/``none``/an unrenderable ``normalized``."""
    by = to_by(suggestion)
    if by is None or suggestion.get("strategy") in ("ref", "none"):
        return None
    by_name, value = by
    return f"({_BY_CONST.get(by_name, 'By.XPATH')}, {json.dumps(value)})"


def parse_normalized_selector_to_suggestion(selector_text: Optional[str]) -> Optional[dict]:
    """A raw derived selector string that fit no structured shape — treated as css or xpath."""
    if not selector_text or is_positional_selector_text(selector_text):
        return None
    stripped = selector_text.strip()
    if stripped.startswith(("/", "(", "./", "//")):
        return {"strategy": "xpath", "xpath": selector_text}
    return {"strategy": "css", "css": selector_text}
