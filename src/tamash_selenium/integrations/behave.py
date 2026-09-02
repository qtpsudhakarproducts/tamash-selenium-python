"""Behave integration — the counterpart of the Java Cucumber glue.

In your ``features/environment.py``::

    from tamash_selenium.integrations.behave import (
        tamash_before_all, tamash_before_scenario, tamash_after_scenario, tamash_after_all,
    )

    def before_all(context):      tamash_before_all(context)
    def before_scenario(context, scenario):  tamash_before_scenario(context, scenario)
    def after_scenario(context, scenario):   tamash_after_scenario(context, scenario)
    def after_all(context):       tamash_after_all(context)

Then every step gets a self-healing ``context.driver``. Browser via ``TAMASH_BROWSER`` /
``HEADLESS`` / ``TAMASH_REUSE_DRIVER``; ``TAMASH_REPORT=...`` writes the HTML step report.
If you already build your own driver in ``before_scenario``, wrap it instead:
``context.driver = SelfHealingDriver.wrap(context.driver)`` and skip the before/after-scenario hooks.
"""

from __future__ import annotations

from typing import Any

from .. import current_test, env, report
from ..current_test import TestInfo
from ..healer import heal_cache
from ..lifecycle import SeleniumSession

_ATTR = "_tamash_selenium"


def tamash_before_all(context: Any) -> None:
    env.load_env()
    report.enable_from_env()
    setattr(context, _ATTR, {"session": SeleniumSession(), "scope": None})


def tamash_before_scenario(context: Any, scenario: Any) -> None:
    state = getattr(context, _ATTR, None)
    if state is None:
        tamash_before_all(context)
        state = getattr(context, _ATTR)
    heal_cache.clear()
    state["scope"] = state["session"].open_scope()
    context.driver = state["scope"].driver
    scenario_id = _scenario_id(scenario)
    state["scenario_id"] = scenario_id
    current_test.set_current(TestInfo(test_id=scenario_id, title=scenario.name))
    report.set_current_test(scenario_id)


def tamash_after_scenario(context: Any, scenario: Any) -> None:
    from .. import tamash as _tamash

    state = getattr(context, _ATTR, None)
    if state is None:
        return
    scenario_id = state.get("scenario_id") or _scenario_id(scenario)
    status = "failed" if getattr(scenario, "status", None) in ("failed", "error") else "passed"
    report.set_test_status(scenario_id, status)
    report.flush_test(scenario_id, status)

    mine = [r for r in _healing_reports() if r.test_id == scenario_id]
    if mine:
        healed = sum(1 for r in mine if r.healed)
        try:
            scenario.tags  # noqa: B018 - touch to ensure scenario is usable
        except Exception:  # noqa: BLE001
            pass
        print(f"[tamash] {scenario.name}: {healed} healed, {len(mine) - healed} not healed")

    current_test.clear()
    report.set_current_test(None)
    _tamash.clear_hint()
    state["session"].close_scope(state["scope"])
    state["scope"] = None


def tamash_after_all(context: Any) -> None:
    state = getattr(context, _ATTR, None)
    if state and state.get("session"):
        state["session"].close()
    report.write_report_if_configured()


def _scenario_id(scenario: Any) -> str:
    location = getattr(scenario, "location", None)
    return f"{location}::{scenario.name}" if location else scenario.name


def _healing_reports():
    from ..healer.core import get_healing_reports
    return get_healing_reports()
