"""``tamash-selenium doctor`` — provider connectivity (a live call), the implicit-wait note, a scan
for brittle locators bound to non-descriptive names, and the agent-skill install state.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional

from .. import env
from ..healer.core import is_healing_enabled
from ..healer.providers import get_heal_provider
from ..healer.providers.types import HealProvider, ProviderDiagnosis
from . import locator_scanner, skill
from .console_style import bold, cyan, dim, green, red, render_table, section, truncate_end, truncate_start, yellow

CONNECTIVITY_TIMEOUT_MS = 15000.0
CONNECTIVITY_SNAPSHOT = '- generic "tamash-selenium doctor check" [ref=e1]:\n  - button "OK" [ref=e2]'

_TAG = {"OK": green("[OK]"), "WARN": yellow("[WARN]"), "FAIL": red("[FAIL]"), "INFO": cyan("[INFO]"), "HIGH": red("[HIGH]")}
_STATUS_COLOR = {"OK": green, "WARN": yellow, "FAIL": red, "INFO": cyan, "OFF": dim}
_summary: List[tuple] = []


def _record(check: str, status: str, detail: str) -> None:
    _summary.append((check, status, detail))


def _run_diagnosis(provider: HealProvider, timeout_ms: float) -> ProviderDiagnosis:
    if provider.diagnose is not None:
        try:
            return provider.diagnose(timeout_ms)
        except Exception as error:  # noqa: BLE001
            return {"category": "unknown", "detail": str(error)}
    started = time.monotonic()
    result = provider.suggest_selector({"action": "click", "description": "tamash-selenium doctor check",
                                        "aria_snapshot": CONNECTIVITY_SNAPSHOT, "timeout_ms": timeout_ms})
    if result:
        return {"category": "ok", "detail": "connected"}
    if (time.monotonic() - started) * 1000 >= timeout_ms * 0.9:
        return {"category": "timeout", "detail": f"no response within ~{timeout_ms:.0f}ms"}
    return {"category": "unknown", "detail": "no valid response"}


def _check_provider() -> None:
    section("AI Provider")
    print(f"  HEALER_ENABLED: {env.get('HEALER_ENABLED') or dim('(unset — defaults to true)')}")
    if not is_healing_enabled():
        print("  Healing is currently OFF. Set HEALER_ENABLED=true (or remove the line) to turn it back on.")
        _record("AI Provider", "OFF", "Healing disabled (HEALER_ENABLED=false)")
        return

    provider_name = (env.get("HEALER_PROVIDER") or "").strip()
    if not provider_name:
        print(f"  {_TAG['INFO']} HEALER_PROVIDER is not set — defaulting to the rule-based {bold('tamash')} provider")
        print("         (no key, no network, no tokens; never guesses). Set HEALER_PROVIDER")
        print("         (ollama | openai | anthropic | gemini | claude-subscription | copilot-subscription)")
        print("         + its API key/model for AI-backed healing.")
        provider_name = "tamash"

    provider = get_heal_provider()
    if provider is None:
        print(f"  {_TAG['FAIL']} HEALER_PROVIDER={provider_name}, but its required model/API key env vars are missing.")
        _record("AI Provider", "FAIL", f"HEALER_PROVIDER={provider_name}, missing required env vars")
        return

    print(f"  Testing connectivity to {bold(provider.name)}...")
    diagnosis = _run_diagnosis(provider, CONNECTIVITY_TIMEOUT_MS)
    category = diagnosis.get("category")
    detail = diagnosis.get("detail")
    if category == "ok":
        print(f"  {_TAG['OK']} Connected to {provider.name} successfully.")
        _record("AI Provider", "OK", f"Connected to {provider.name}")
    elif category == "not-installed":
        print(f"  {_TAG['FAIL']} {provider.name}'s SDK isn't installed. {detail}")
        print("         Install the matching extra, or switch to HEALER_PROVIDER=openai|gemini|ollama (no extra).")
        _record("AI Provider", "FAIL", f"{provider_name}: SDK not installed")
    elif category == "not-authenticated":
        print(f"  {_TAG['FAIL']} Reached {provider.name}, but it rejected the request — almost always auth.")
        print(f"         {dim(detail or '')}")
        _record("AI Provider", "FAIL", f"{provider_name}: not authenticated")
    elif category == "bad-model":
        print(f"  {_TAG['FAIL']} {provider.name} rejected the configured model id. {dim(detail or '')}")
        _record("AI Provider", "FAIL", f"{provider_name}: model id rejected")
    elif category in ("network", "timeout"):
        print(f"  {_TAG['FAIL']} Could not reach {provider.name} ({category}). {dim(detail or '')}")
        _record("AI Provider", "FAIL", f"{provider_name}: {category}")
    elif category == "bad-response":
        print(f"  {_TAG['WARN']} Connected to {provider.name}, but its reply couldn't be used — try a stronger model.")
        _record("AI Provider", "WARN", f"{provider_name}: response unusable")
    else:
        print(f"  {_TAG['FAIL']} Could not get a valid response from {provider.name}. {dim(detail or '')}")
        _record("AI Provider", "FAIL", f"{provider_name}: {detail or 'no valid response'}")


def _check_implicit_wait() -> None:
    section("Implicit Wait")
    print(f"  {_TAG['OK']} SelfHealingDriver.wrap(...) pins Selenium's implicit wait to 0 so a broken "
          "find_element surfaces immediately for self-healing.")
    print(dim("        Use explicit WebDriverWait for synchronisation (a locator broken inside wait.until "
              "heals a few polls in; a direct driver.find_element(broken) heals immediately)."))
    _record("Implicit Wait", "OK", "Implicit wait pinned to 0 on wrap")


def _check_locators(test_dir: str) -> None:
    section("Locators")
    resolved = os.path.abspath(test_dir)
    print(f"  Scanning {os.path.relpath(resolved) or resolved} for locators...")
    print(dim("  (AST scan of *.py — review before acting on findings)\n"))
    occurrences = locator_scanner.scan_directory(resolved)

    weak = [o for o in occurrences if o.priority == "high"]
    if not weak:
        print(f"  {_TAG['OK']} Every brittle locator is bound to a descriptive variable name.")
        _record("Locator naming", "OK", "No brittle locators with a non-descriptive name")
    else:
        print(f"  {_TAG['WARN']} Found {bold(str(len(weak)))} brittle CSS/XPath locator(s) with no descriptive name:\n")
        render_table(["Location", "Snippet"],
                     [[dim(truncate_start(f"{os.path.relpath(o.file)}:{o.line}", 42)), truncate_end(o.snippet, 70)]
                      for o in weak], "    ")
        _record("Locator naming", "WARN", f"{len(weak)} brittle locator(s) with a non-descriptive name")
        print(dim('\n    username_field = (By.CSS_SELECTOR, "input[name=\'username\']")  # a name the healer can decode'))

    inline = [o for o in occurrences if o.in_test_file and o.by in ("CSS_SELECTOR", "XPATH")]
    if inline:
        files = len({o.file for o in inline})
        print(f"\n  {_TAG['INFO']} {len(inline)} locator(s) defined directly inside {files} test file(s) — "
              "prefer moving locators into Page Object classes.")
        _record("Page Objects", "INFO", f"{len(inline)} locator(s) inline across {files} file(s)")
    else:
        _record("Page Objects", "OK", "No brittle locators defined directly inside test files")


def _check_skill() -> None:
    section("Skill")
    version = skill.get_package_version()
    cwd = os.getcwd()
    any_present = False
    any_stale = False
    for target in skill.TARGETS:
        state = skill.skill_state(cwd, target, version)
        status = state["status"]
        if status == "absent":
            print(f"  {dim(target.label + ' — not installed')}")
        elif status == "current":
            any_present = True
            print(f"  {target.label} — {state['version']} (current)")
        elif status == "outdated":
            any_present = True
            any_stale = True
            print(f"  {_TAG['WARN']} {target.label} — {state['installed']} installed, package is {state['version']}")
        else:
            any_present = True
            any_stale = True
            print(f"  {_TAG['WARN']} {target.label} — present, no version marker")

    if not any_present:
        print(dim('          run: tamash-selenium init-skill'))
        _record("Skill", "INFO", "Skill not installed (.claude/skills, .agents/skills)")
    elif any_stale:
        print(dim('          run: tamash-selenium init-skill  to refresh'))
        _record("Skill", "WARN", "Installed skill is behind the package or unmanaged")
    else:
        _record("Skill", "OK", "Skill installed and current")


def _print_summary() -> None:
    section("Summary")
    render_table(["Check", "Status", "Detail"],
                 [[c, _STATUS_COLOR.get(s, dim)(s), truncate_end(d, 78)] for c, s, d in _summary])


def run_doctor(test_dir: str = "tests") -> None:
    env.load_env()
    _summary.clear()
    print(bold("tamash-selenium doctor"))
    print(dim("─" * 25))
    _check_provider()
    _check_implicit_wait()
    _check_locators(test_dir)
    _check_skill()
    _print_summary()
