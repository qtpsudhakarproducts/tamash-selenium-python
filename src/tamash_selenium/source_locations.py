"""Resolves the consumer's real call site of a ``find_element`` / element action, and — when no
explicit :func:`tamash_selenium.hint` was set — derives a human-readable description from the
locator's own variable name.

Port of the Java ``SourceLocations`` + the variable-name-decoding half of
``tamash-playwright-python``'s ``bindings.py``. Python-specific: where Java has to probe Maven
source roots to turn a ``StackTraceElement`` into a file path, :mod:`traceback` gives us the real
absolute path of every frame directly — so the whole "guess the repo-relative path" machinery
collapses to :func:`os.path.relpath`.
"""

from __future__ import annotations

import os
import re
import sys
import traceback
from dataclasses import dataclass
from typing import List, Optional, Tuple

# --------------------------------------------------------------------------------------------------
# Frame classification
# --------------------------------------------------------------------------------------------------

_PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))

# Third-party / stdlib path fragments that are never the consumer's own call site.
_INFRA_FRAGMENTS = (
    os.sep + "selenium" + os.sep,
    os.sep + "_pytest" + os.sep,
    os.sep + "pytest" + os.sep,
    os.sep + "pluggy" + os.sep,
    os.sep + "behave" + os.sep,
    os.sep + "pytest_bdd" + os.sep,
    os.sep + "unittest" + os.sep,
    os.sep + "importlib" + os.sep,
)


def _is_consumer_frame(filename: str) -> bool:
    if not filename or filename.startswith("<"):
        return False
    abspath = os.path.abspath(filename)
    if abspath.startswith(_PACKAGE_ROOT + os.sep):
        return False
    norm = abspath.replace("/", os.sep)
    if any(fragment in norm for fragment in _INFRA_FRAGMENTS):
        return False
    # stdlib (…/lib/python3.x/…) that isn't site-packages
    parts = norm.split(os.sep)
    if "lib" in parts and "site-packages" not in parts and any(p.startswith("python3") for p in parts):
        return False
    return True


@dataclass(frozen=True)
class Caller:
    location: str  # "relpath:line"
    simple_class_name: Optional[str]


def capture_call_site(depth: int = 2) -> Optional[Tuple[str, int]]:
    """Cheap ``(filename, lineno)`` of the consumer frame ``depth`` levels above the caller of
    this function. Captured eagerly on every ``find_element``; resolved lazily on failure."""
    try:
        frame = sys._getframe(depth)
    except ValueError:
        return None
    try:
        # Walk out of any tamash / infra frames to the first real consumer frame.
        while frame is not None and not _is_consumer_frame(frame.f_code.co_filename):
            frame = frame.f_back
        if frame is None:
            return None
        return frame.f_code.co_filename, frame.f_lineno
    finally:
        del frame


def resolve_source_location(call_site: Optional[Tuple[str, int]]) -> Optional[str]:
    if call_site is None:
        return None
    filename, lineno = call_site
    try:
        rel = os.path.relpath(filename)
    except ValueError:
        rel = filename
    return f"{rel.replace(os.sep, '/')}:{lineno}"


def resolve_consumer_chain(max_frames: int = 3) -> List[Caller]:
    """The first ``max_frames`` consumer frames on the live stack (skipping selenium / tamash /
    test-infra). Lets name resolution follow a locator passed through a ``click(driver, login_btn)``
    wrapper — the real name lives at the util's caller, not inside it."""
    out: List[Caller] = []
    for frame_summary in reversed(traceback.extract_stack()[:-1]):
        if not _is_consumer_frame(frame_summary.filename):
            continue
        try:
            rel = os.path.relpath(frame_summary.filename)
        except ValueError:
            rel = frame_summary.filename
        out.append(Caller(f"{rel.replace(os.sep, '/')}:{frame_summary.lineno}", _simple_class_name(frame_summary)))
        if len(out) >= max_frames:
            break
    return out


def _simple_class_name(frame_summary: traceback.FrameSummary) -> Optional[str]:
    # Best-effort: the enclosing class name, recovered from a "self" / "cls" local isn't available
    # from a FrameSummary, so fall back to the module basename (still useful context for the AI).
    name = os.path.splitext(os.path.basename(frame_summary.filename))[0]
    return name or None


def called_from_wait() -> bool:
    """True when the current failure surfaced from inside a ``WebDriverWait`` poll."""
    for frame_summary in traceback.extract_stack():
        norm = frame_summary.filename.replace("/", os.sep)
        if (os.sep + "selenium" + os.sep + "webdriver" + os.sep + "support" + os.sep) in norm:
            return True
    return False


# --------------------------------------------------------------------------------------------------
# Reading a source line
# --------------------------------------------------------------------------------------------------


def parse_source_location(source_location: Optional[str]) -> Optional[Tuple[str, int]]:
    if not source_location:
        return None
    sep = source_location.rfind(":")
    if sep == -1:
        return None
    try:
        return source_location[:sep], int(source_location[sep + 1 :])
    except ValueError:
        return None


def _source_line(source_location: Optional[str]) -> Optional[str]:
    parsed = parse_source_location(source_location)
    if parsed is None:
        return None
    path, line_no = parsed
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    if line_no < 1 or line_no > len(lines):
        return None
    return lines[line_no - 1]


# --------------------------------------------------------------------------------------------------
# Variable-name extraction
# --------------------------------------------------------------------------------------------------

_VAR_NAME_RE = re.compile(r"(\w+)\s*(?::\s*[\w.\[\]]+\s*)?$")


def _find_assignment_equals(line: str) -> int:
    """String-aware ``=`` finder — ignores ``=`` inside quotes and skips ``== != <= >=``."""
    in_string: Optional[str] = None
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = ch
            i += 1
            continue
        if ch != "=":
            i += 1
            continue
        prev_ch = line[i - 1] if i > 0 else ""
        next_ch = line[i + 1] if i + 1 < len(line) else ""
        if next_ch == "=" or prev_ch in ("=", "!", "<", ">"):
            i += 1
            continue
        return i
    return -1


def extract_variable_name(source_location: Optional[str]) -> Optional[str]:
    """Identifier immediately before the line's first real ``=`` (``self.x =``, ``x =``,
    ``x: WebElement =``)."""
    line = _source_line(source_location)
    if line is None:
        return None
    eq_index = _find_assignment_equals(line)
    if eq_index == -1:
        return None
    match = _VAR_NAME_RE.search(line[:eq_index])
    return match.group(1) if match else None


_NON_LOCATOR_IDENTS = {
    "driver", "wait", "webdriver", "js", "actions", "select", "d", "w",
    "by", "locator", "loc", "selector", "element", "elem", "el", "webelement", "target", "self",
}

# Identifier passed to a find / a Selenium wait condition.
_LOCATOR_ARG_RE = re.compile(
    r"\b(?:find_element|find_elements|element_to_be_clickable|visibility_of_element_located"
    r"|presence_of_element_located|presence_of_all_elements_located|invisibility_of_element_located"
    r"|text_to_be_present_in_element_located|frame_to_be_available_and_switch_to_it)"
    r"\s*\(\s*\*?(\w+)\s*[),]"
)

# Action called directly on a locator/element variable — ``login_button.click()``.
_ELEMENT_OP_RE = re.compile(
    r"\b(\w+)\.(?:click|send_keys|clear|submit|get_attribute|get_dom_attribute|is_displayed"
    r"|is_enabled|is_selected|select_by_visible_text|select_by_value|select_by_index)\s*\("
)

# An identifier in argument position.
_ARG_IDENTIFIER_RE = re.compile(r"[(,]\s*\*?([A-Za-z_]\w*)\s*(?=[),])")
_ARG_LITERALS = {"true", "false", "none", "self"}
_IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")
_METHOD_NAME_NOISE = {
    "get_element", "get_elements", "find_element", "find_elements", "webelement",
    "get_locator", "by_locator", "get_by",
}


def extract_locator_reference(source_location: Optional[str]) -> Optional[str]:
    line = _source_line(source_location)
    if line is None:
        return None
    m = _LOCATOR_ARG_RE.search(line)
    if m and m.group(1).lower() not in _NON_LOCATOR_IDENTS:
        return m.group(1)
    m2 = _ELEMENT_OP_RE.search(line)
    if m2 and m2.group(1).lower() not in _NON_LOCATOR_IDENTS:
        return m2.group(1)
    return None


def extract_arg_identifier(source_location: Optional[str]) -> Optional[str]:
    line = _source_line(source_location)
    if line is None:
        return None
    for m in _ARG_IDENTIFIER_RE.finditer(line):
        a = m.group(1)
        low = a.lower()
        if low not in _ARG_LITERALS and low not in _NON_LOCATOR_IDENTS and _looks_like_locator_name(a):
            return a
    return None


def extract_locatorish_token(source_location: Optional[str]) -> Optional[str]:
    line = _source_line(source_location)
    if line is None:
        return None
    for m in _IDENTIFIER_RE.finditer(line):
        ident = m.group(0)
        if ident.lower() not in _NON_LOCATOR_IDENTS and _looks_like_locator_name(ident):
            return ident
    return None


def _looks_like_locator_name(ident: str) -> bool:
    low = ident.lower()
    if low in _METHOD_NAME_NOISE:
        return False
    if (low.endswith("locator") or low.endswith("selector") or low.endswith("by")) and len(low) > 3:
        return True
    decoded = decode_variable_name(ident)
    return decoded is not None and decoded.type_hint is not None


def resolve_locator_name(chain: List[Caller]) -> Optional[Tuple[str, Optional[str]]]:
    """Walk the consumer chain and return ``(raw_name, location)`` from the first frame that
    yields a usable locator identifier."""
    for caller in chain:
        name = (
            extract_variable_name(caller.location)
            or extract_locator_reference(caller.location)
            or extract_arg_identifier(caller.location)
            or extract_locatorish_token(caller.location)
        )
        if name:
            return name, caller.location
    return None


# --------------------------------------------------------------------------------------------------
# Assertion / negative-find context
# --------------------------------------------------------------------------------------------------

_ASSERTION_LINE_RE = re.compile(
    r"\b(assert\w*|verif(?:y|ies)\w*|assert_that|expect|should\w*|check_that)\b",
    re.IGNORECASE,
)
_NEGATIVE_LINE_RE = re.compile(
    r"\b(?:invisibility_of_element_located|staleness_of|number_of_elements_to_be_less_than"
    r"|is_not_displayed|is_not_present|should_not_be\w*|to_be_gone|to_disappear|to_be_removed)\b"
    r"|(?:absent|not_present|notpresent|is_gone|has_disappeared|is_removed)"
    r"|assert_raises\s*\(\s*NoSuchElementException"
    r"|pytest\.raises\s*\(\s*NoSuchElementException",
    re.IGNORECASE,
)


def is_assertion_line(line: Optional[str]) -> bool:
    return bool(line and _ASSERTION_LINE_RE.search(line))


def is_negative_line(line: Optional[str]) -> bool:
    return bool(line and _NEGATIVE_LINE_RE.search(line))


def classify_call_site(chain: List[Caller]) -> Tuple[bool, bool]:
    """Returns ``(in_assertion, negative)`` OR-ed across the consumer chain."""
    in_assertion = False
    negative = False
    for caller in chain:
        line = _source_line(caller.location)
        if is_assertion_line(line):
            in_assertion = True
        if is_negative_line(line):
            negative = True
    return in_assertion, negative


# --------------------------------------------------------------------------------------------------
# decode_variable_name
# --------------------------------------------------------------------------------------------------

_TYPE_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("txt", "textbox"), ("btn", "button"), ("chk", "checkbox"), ("cb", "checkbox"),
    ("rdo", "radio button"), ("ddl", "dropdown"), ("lnk", "link"), ("img", "image"), ("lbl", "label"),
)
_TYPE_SUFFIXES: Tuple[Tuple[str, str], ...] = (
    ("radiobutton", "radio button"), ("checkbox", "checkbox"), ("textarea", "textarea"),
    ("textbox", "textbox"), ("textfield", "textbox"), ("dropdown", "dropdown"), ("combobox", "dropdown"),
    ("button", "button"), ("select", "dropdown"), ("input", "textbox"), ("field", "textbox"),
    ("radio", "radio button"), ("link", "link"), ("image", "image"), ("label", "label"),
    ("btn", "button"), ("chk", "checkbox"), ("cb", "checkbox"), ("rdo", "radio button"),
    ("ddl", "dropdown"), ("lnk", "link"), ("img", "image"), ("lbl", "label"),
)
_MEANINGLESS_WORDS = {
    "el", "elem", "element", "obj", "val", "value", "loc", "locator", "ctrl", "control",
    "item", "temp", "tmp", "thing", "x", "y", "a", "b", "field", "box", "node",
}
_AFFIX_WORDS = {p for p, _ in _TYPE_PREFIXES} | {s for s, _ in _TYPE_SUFFIXES}

_WORD_SEPARATOR_RE = re.compile(r"[_-]+")
_LOWER_TO_UPPER_RE = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_TO_WORD_RE = re.compile(r"([A-Z]+)([A-Z][a-z])")
_TRAILING_DIGITS_RE = re.compile(r"\d+$")


@dataclass(frozen=True)
class Decoded:
    name: str
    type_hint: Optional[str]


def _split_identifier_into_words(identifier: str) -> List[str]:
    text = _WORD_SEPARATOR_RE.sub(" ", identifier)
    text = _LOWER_TO_UPPER_RE.sub(r"\1 \2", text)
    text = _ACRONYM_TO_WORD_RE.sub(r"\1 \2", text)
    return text.strip().split()


def decode_variable_name(raw: Optional[str]) -> Optional[Decoded]:
    if not raw:
        return None
    lower = raw.lower()
    remainder = raw
    type_hint: Optional[str] = None

    for prefix, kind in _TYPE_PREFIXES:
        if lower.startswith(prefix) and len(raw) > len(prefix) and re.match(r"[A-Z_-]", raw[len(prefix)]):
            remainder, type_hint = raw[len(prefix):], kind
            break
    if type_hint is None:
        for suffix, kind in _TYPE_SUFFIXES:
            if lower.endswith(suffix) and len(raw) > len(suffix):
                remainder, type_hint = raw[: len(raw) - len(suffix)], kind
                break

    words = _split_identifier_into_words(remainder)
    if not words:
        return None
    if all(_TRAILING_DIGITS_RE.sub("", w.lower()) in _MEANINGLESS_WORDS
           or _TRAILING_DIGITS_RE.sub("", w.lower()) in _AFFIX_WORDS for w in words):
        return None

    name = " ".join(w[:1].upper() + w[1:] for w in words)
    return Decoded(name=name, type_hint=type_hint)


def describe_from(raw_name: Optional[str], by_repr: Optional[str]) -> Optional[str]:
    """Human label from a resolved identifier, decoded — else the raw name, else the selector text."""
    if raw_name:
        decoded = decode_variable_name(raw_name)
        if decoded:
            return f"{decoded.name} ({decoded.type_hint})" if decoded.type_hint else decoded.name
        return raw_name
    return by_repr


# --------------------------------------------------------------------------------------------------
# apply-heals support: find a locator's declaration line
# --------------------------------------------------------------------------------------------------


def locate_locator_declaration(call_site_location: Optional[str], name: Optional[str]) -> Optional[str]:
    """When the failing call site references a locator held in a separate ``LOGIN = (By.ID, "old")``
    (or ``self.login = (By.ID, "old")``), the call site has no literal to rewrite — this finds the
    declaration line in the same file, as ``"path:line"``."""
    parsed = parse_source_location(call_site_location)
    if parsed is None or not name:
        return None
    path, _ = parsed
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    decl = re.compile(r"\b" + re.escape(name) + r"\b\s*[:=]\s*\(?\s*By\.")
    for i, text in enumerate(lines):
        if decl.search(text):
            return f"{path}:{i + 1}"
    return None
