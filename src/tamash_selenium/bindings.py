"""Wraps a Selenium ``WebDriver`` (and, transitively, every ``WebElement`` it finds) with
self-healing, by monkey-patching the relevant instance methods in place — the object stays a
genuine ``WebDriver`` / ``WebElement`` (``Select``, ``WebDriverWait``, ``isinstance`` all keep
working), only the patched methods' behaviour changes.

Healing model (matches the Java port):

* a broken ``find_element`` is healed at find time — including inside a ``WebDriverWait`` (the
  :mod:`heal_cache` keeps a wait's repeated polls to ~one heal);
* a ``StaleElementReferenceException`` at action time re-finds with the original locator first,
  then heals;
* an interactability error runs action recovery (opt-in, ``HEALER_ACTION_RECOVERY_ENABLED=true``).
"""

from __future__ import annotations

import time
from typing import Any, List, Optional, Tuple

from selenium.webdriver.common.by import By

from . import current_test, env, report, source_locations
from .healer import core
from .healer.core import HealContext

_READ_ACTIONS = {"get_attribute", "get_dom_attribute", "get_dom_property", "get_property",
                 "value_of_css_property", "is_displayed", "is_enabled", "is_selected"}
_VALUE_ACTIONS = {"send_keys", "get_attribute", "get_dom_attribute", "get_dom_property"}
_NAV_METHODS = ("get",)

Locator = Tuple[str, str]

_BOUND_ATTR = "_tamash_bound"
_BY_ATTR = "_tamash_by"
_PARENT_ATTR = "_tamash_parent"
_FRAME_CHAIN_ATTR = "_tamash_frame_chain"
_CALL_SITE_ATTR = "_tamash_call_site"

_ELEMENT_ACTIONS = (
    "click", "submit", "send_keys", "clear",
    "get_attribute", "get_dom_attribute", "get_dom_property", "get_property",
    "value_of_css_property", "is_displayed", "is_enabled", "is_selected",
)

_IMPLICIT_WAIT_NOTED = [False]


# --------------------------------------------------------------------------------------------------
# unwrap
# --------------------------------------------------------------------------------------------------


def unwrap(obj: Any) -> Any:
    """No-op in the monkey-patch model — a wrapped object is still the real Selenium object.
    Kept for source-compatibility with the Java API and callers that expect it."""
    return obj


# --------------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------------


def bind_driver(driver: Any) -> Any:
    if driver is None or getattr(driver, _BOUND_ATTR, False):
        return driver
    setattr(driver, _BOUND_ATTR, True)
    env.load_env()
    report.enable_from_env()
    _pin_implicit_wait(driver)
    _patch_finds(driver, driver, kind="driver", frame_chain=[])
    _patch_navigation(driver)
    return driver


def _patch_navigation(driver: Any) -> None:
    for name in _NAV_METHODS:
        real = getattr(driver, name, None)
        if not callable(real):
            continue

        def make(action_name: str, real_method: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> Any:
                started = time.perf_counter()
                try:
                    result = real_method(*args, **kwargs)
                    _record(action_name, f"driver.{action_name}", None,
                            str(args[0]) if args else None, started, healed=False)
                    return result
                except Exception as error:  # noqa: BLE001
                    _record(action_name, f"driver.{action_name}", None,
                            str(args[0]) if args else None, started, healed=False, error=str(error))
                    raise
            return wrapper

        setattr(driver, name, make(name, real))


def _record(action: str, element: Optional[str], locator: Optional[str], value: Optional[str],
            started: float, *, healed: bool, error: Optional[str] = None,
            heal_report: Any = None) -> None:
    if not report.is_report_enabled():
        return
    kw = dict(action=action, element=element, locator=locator, value=value,
              duration_ms=(time.perf_counter() - started) * 1000, healed=healed, error=error)
    if heal_report is not None:
        kw.update(
            healed=heal_report.healed,
            error=None if heal_report.healed else heal_report.warning,
            suggested_selector=heal_report.suggested_selector,
            provider=heal_report.provider,
            token_usage=heal_report.token_usage,
            failure_stage=heal_report.failure_stage,
            used_action_recovery=heal_report.used_action_recovery,
            needs_review=heal_report.needs_review,
            review_note=heal_report.review_note,
            aria_snapshot=None if heal_report.healed else heal_report.aria_snapshot_for_report,
        )
    report.record_step(**kw)


def _describe_value(action: str, args: tuple) -> Optional[str]:
    if action not in _VALUE_ACTIONS or not args:
        return None
    first = args[0]
    if isinstance(first, (list, tuple)):
        return "".join(str(a) for a in first)
    return str(first)


def _pin_implicit_wait(driver: Any) -> None:
    if env.get_bool("TAMASH_KEEP_IMPLICIT_WAIT", False):
        return
    try:
        driver.implicitly_wait(0)
        if not _IMPLICIT_WAIT_NOTED[0]:
            _IMPLICIT_WAIT_NOTED[0] = True
            print("[tamash] implicit wait set to 0 for self-healing "
                  "(use explicit WebDriverWait; TAMASH_KEEP_IMPLICIT_WAIT=true to keep yours)")
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------------------------------
# find_element / find_elements patching (shared by driver + element)
# --------------------------------------------------------------------------------------------------


def _patch_finds(obj: Any, driver: Any, kind: str, frame_chain: List[Locator]) -> None:
    real_find_element = obj.find_element
    real_find_elements = obj.find_elements

    def find_element(by: str = By.ID, value: Optional[str] = None) -> Any:
        call_site = source_locations.capture_call_site(depth=2)
        locator: Locator = (by, value)
        try:
            found = real_find_element(by, value)
            return _wrap_element(found, locator, obj, driver, frame_chain, call_site)
        except Exception as error:  # noqa: BLE001
            if not core.is_missing_element(error) or not core.is_healing_enabled():
                raise
            healed = _heal_find(driver, locator, kind, frame_chain, call_site, error)
            if healed is not None:
                return _wrap_element(healed, locator, obj, driver, frame_chain, call_site)
            raise

    def find_elements(by: str = By.ID, value: Optional[str] = None) -> List[Any]:
        call_site = source_locations.capture_call_site(depth=2)
        locator: Locator = (by, value)
        found = real_find_elements(by, value)
        return [_wrap_element(el, locator, obj, driver, frame_chain, call_site) for el in found]

    setattr(obj, "find_element", find_element)
    setattr(obj, "find_elements", find_elements)


def _heal_find(driver: Any, locator: Locator, kind: str, frame_chain: List[Locator],
               call_site: Optional[Tuple[str, int]], error: BaseException) -> Optional[Any]:
    chain = source_locations.resolve_consumer_chain(3)
    in_assertion, negative = source_locations.classify_call_site(chain)
    if negative or (in_assertion and core.assertion_mode() == "strict"):
        return None

    in_wait = source_locations.called_from_wait()
    from .healer import heal_cache
    if in_wait and not heal_cache.ever_healed(locator) and heal_cache.record_failing(locator) <= 3:
        return None

    name_and_loc = source_locations.resolve_locator_name(chain)
    raw_name = name_and_loc[0] if name_and_loc else None
    resolved_source = (name_and_loc[1] if name_and_loc else None) or source_locations.resolve_source_location(call_site)
    info = current_test.get()

    ctx = HealContext(
        action=None, kind=kind,
        description=source_locations.describe_from(raw_name, str(locator)),
        error=error, driver=driver, by=locator, original_by_string=str(locator),
        source_location=resolved_source, raw_variable_name=raw_name,
        enclosing_class=chain[0].simple_class_name if chain else None,
        in_assertion=in_assertion, in_wait=in_wait, frame_chain=frame_chain,
        test_id=info.test_id if info else None, test_title=info.title if info else None,
        replay=None,
    )
    started = time.perf_counter()
    result = core.heal_action_failure(ctx)
    _record("findElement", ctx.description or str(locator), str(locator), None, started,
            healed=result.recovered, heal_report=result.report)
    if result.recovered and result.result is not None:
        return result.result
    return None


# --------------------------------------------------------------------------------------------------
# Element
# --------------------------------------------------------------------------------------------------


def _wrap_element(element: Any, originating_by: Optional[Locator], parent: Any, driver: Any,
                  frame_chain: List[Locator], call_site: Optional[Tuple[str, int]]) -> Any:
    if element is None or getattr(element, _BOUND_ATTR, False):
        return element
    setattr(element, _BOUND_ATTR, True)
    setattr(element, _BY_ATTR, originating_by)
    setattr(element, _PARENT_ATTR, parent)
    setattr(element, _FRAME_CHAIN_ATTR, frame_chain)
    setattr(element, _CALL_SITE_ATTR, call_site)
    _patch_finds(element, driver, kind="element", frame_chain=frame_chain)
    _patch_element_actions(element, driver)
    return element


def bind_element(element: Any) -> Any:
    return _wrap_element(element, None, None, _driver_of(element), [], None)


def _driver_of(element: Any) -> Any:
    return getattr(element, "parent", None)


def _patch_element_actions(element: Any, driver: Any) -> None:
    for name in _ELEMENT_ACTIONS:
        real = getattr(element, name, None)
        if not callable(real):
            continue
        setattr(element, name, _make_action_wrapper(element, driver, name, real))


def _make_action_wrapper(element: Any, driver: Any, name: str, real: Any) -> Any:
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        originating_by_ok: Optional[Locator] = getattr(element, _BY_ATTR, None)
        try:
            result = real(*args, **kwargs)
            if report.is_report_enabled():
                value = str(result) if name in _READ_ACTIONS and result is not None else _describe_value(name, args)
                _record(name, str(originating_by_ok) if originating_by_ok else f"element.{name}",
                        str(originating_by_ok) if originating_by_ok else None, value, started, healed=False)
            return result
        except Exception as error:  # noqa: BLE001
            stale = core.is_stale_failure(error)
            interactability = core.is_actionability_failure(error)
            originating_by: Optional[Locator] = getattr(element, _BY_ATTR, None)
            if (not stale and not interactability) or not core.is_healing_enabled() or originating_by is None:
                raise

            parent = getattr(element, _PARENT_ATTR, None)
            frame_chain = getattr(element, _FRAME_CHAIN_ATTR, []) or []

            if stale and parent is not None:
                try:
                    fresh = _raw_find(parent, originating_by)
                    return getattr(fresh, name)(*args, **kwargs)
                except Exception:  # noqa: BLE001
                    pass

            chain = source_locations.resolve_consumer_chain(3)
            in_assertion, negative = source_locations.classify_call_site(chain)
            if negative or (in_assertion and core.assertion_mode() == "strict"):
                raise

            name_and_loc = source_locations.resolve_locator_name(chain)
            raw_name = name_and_loc[0] if name_and_loc else None
            resolved_source = (
                (name_and_loc[1] if name_and_loc else None)
                or source_locations.resolve_source_location(getattr(element, _CALL_SITE_ATTR, None))
            )
            info = current_test.get()

            ctx = HealContext(
                action=name, kind="element",
                description=source_locations.describe_from(raw_name, str(originating_by)),
                error=error, driver=driver, by=originating_by, original_by_string=str(originating_by),
                args=args, kwargs=kwargs, source_location=resolved_source, raw_variable_name=raw_name,
                enclosing_class=chain[0].simple_class_name if chain else None,
                in_assertion=in_assertion, in_wait=False, frame_chain=list(frame_chain),
                test_id=info.test_id if info else None, test_title=info.title if info else None,
                replay=lambda healed_el: getattr(healed_el, name)(*args, **kwargs),
            )
            result = core.heal_action_failure(ctx)
            _record(name, ctx.description or str(originating_by), str(originating_by),
                    _describe_value(name, args), started, healed=result.recovered, heal_report=result.report)
            if result.recovered:
                return result.result
            raise

    return wrapper


def _raw_find(search_context: Any, locator: Locator) -> Any:
    # `search_context.find_element` may itself be our patched wrapper — that's fine, it re-finds
    # with the original locator and (on failure) would heal, which is acceptable here.
    return search_context.find_element(*locator)
