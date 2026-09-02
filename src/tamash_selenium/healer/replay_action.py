"""Re-runs the original failed action against a (healed) element.

For a find-time heal (``action is None``) "replaying" just means handing back the freshly-found
element. For an element-action heal it re-invokes the same method with the original arguments.
Anything outside :data:`REPLAYABLE_ACTIONS` (e.g. ``Actions`` chains) can't be safely healed by
guessing a substitute element and acting on it — so those raise rather than silently do the
wrong thing.
"""

from __future__ import annotations

from typing import Any, Optional

REPLAYABLE_ACTIONS = {
    "click", "submit", "send_keys", "clear",
    "get_attribute", "get_dom_attribute", "get_dom_property", "get_property", "value_of_css_property",
    "is_displayed", "is_enabled", "is_selected", "get_attribute",
    "screenshot", "location_once_scrolled_into_view",
}

# Read-only property names we can serve off a healed element (WebElement exposes these as
# properties, not methods, so they're read after re-find rather than "replayed").
REPLAYABLE_PROPERTIES = {"text", "tag_name", "size", "location", "rect", "accessible_name", "aria_role"}


def replay_action(element: Any, action: Optional[str], args: tuple = (), kwargs: Optional[dict] = None) -> Any:
    if action is None:
        return element
    if action in REPLAYABLE_PROPERTIES:
        return getattr(element, action)
    if action not in REPLAYABLE_ACTIONS:
        raise RuntimeError(f'Action "{action}" cannot be safely replayed by the self-healer.')
    method = getattr(element, action)
    return method(*args, **(kwargs or {}))
