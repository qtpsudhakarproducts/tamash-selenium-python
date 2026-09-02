"""A strictly second-order fallback, only ever called after a locator has already been
successfully healed but replaying the original action on it still failed for a non-selector
reason. Bounded by design: the AI only ever picks among the fixed tactic menu
(``scroll`` / ``force`` / ``wait`` / ``dispatch`` / ``none``).

Port of the Java ``ActionRecovery`` — Selenium tactics via ``execute_script``.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from .providers.types import HealProvider, TokenUsage
from .replay_action import replay_action

_CLICK_ACTIONS = {"click", "submit"}
_DISPATCH_EVENT_MAP = {"click": "click", "submit": "submit", "send_keys": "input", "clear": "input"}
_WAIT_TACTIC_DELAY_S = 0.5


def _first_arg_string(args: tuple) -> str:
    if not args or args[0] is None:
        return ""
    value = args[0]
    if isinstance(value, (list, tuple)):
        return "".join(str(v) for v in value)
    return str(value)


def apply_action_tactic(tactic: str, driver: Any, element: Any, action: str, args: tuple,
                        kwargs: dict) -> Any:
    if tactic == "scroll":
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", element)
        return replay_action(element, action, args, kwargs)
    if tactic == "wait":
        time.sleep(_WAIT_TACTIC_DELAY_S)
        return replay_action(element, action, args, kwargs)
    if tactic == "force":
        if action in _CLICK_ACTIONS:
            driver.execute_script("arguments[0].click();", element)
            return None
        if action in ("send_keys", "fill", "type"):
            value = _first_arg_string(args)
            driver.execute_script(
                "arguments[0].value = arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                element, value,
            )
            return None
        from selenium.webdriver.common.action_chains import ActionChains
        ActionChains(driver).move_to_element(element).click().perform()
        return None
    if tactic == "dispatch":
        event_type = _DISPATCH_EVENT_MAP.get(action, "click")
        driver.execute_script(
            "arguments[0].dispatchEvent(new MouseEvent(arguments[1], "
            "{bubbles:true, cancelable:true, view:window}));",
            element, event_type,
        )
        return None
    raise RuntimeError(f'Unknown action tactic "{tactic}".')


def try_action_recovery(provider: HealProvider, driver: Any, element: Any, action: str, args: tuple,
                        kwargs: dict, replay_error_message: str, timeout_ms: Optional[float]) -> dict:
    if provider.suggest_action_tactic is None:
        return {"healing": None, "usage": None, "stage": "action_recovery_failed"}

    result = provider.suggest_action_tactic(
        {"action": action, "error_message": replay_error_message, "timeout_ms": timeout_ms}
    )
    if not result:
        return {"healing": None, "usage": None, "stage": "action_recovery_failed"}

    tactic = result.get("tactic")
    usage: Optional[TokenUsage] = result.get("usage")
    if tactic in (None, "none"):
        return {"healing": None, "usage": usage, "stage": "action_recovery_declined"}

    try:
        tactic_result = apply_action_tactic(tactic, driver, element, action, args, kwargs)
        return {
            "healing": {
                "provider": provider.name,
                "warning": f"Recovered using {provider.name} via action recovery ({tactic}).",
                "result": tactic_result,
            },
            "usage": usage,
        }
    except Exception:  # noqa: BLE001
        return {"healing": None, "usage": usage, "stage": "action_recovery_failed"}
