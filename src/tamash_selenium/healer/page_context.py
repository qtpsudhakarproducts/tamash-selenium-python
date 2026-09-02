"""Python stand-in for the Java ``PageContext`` — "the thing a replacement locator is resolved
against". For Selenium that's a ``SearchContext`` (normally the ``WebDriver``, occasionally a
container ``WebElement`` for a scoped find) plus the owning driver, which the snapshot / JS-identity
calls need.

iframe healing threads a ``frame_chain`` (a list of ``(by, value)`` locator tuples) through: the
healer switches into it before capturing / finding and back to ``default_content()`` after —
Selenium finds never descend into a frame on their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

Locator = Tuple[str, str]


@dataclass
class PageContext:
    driver: Any
    search_context: Any = None
    frame_chain: List[Locator] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.search_context is None:
            self.search_context = self.driver

    # -- frame switching --------------------------------------------------

    def enter_frame(self) -> None:
        if not self.frame_chain:
            return
        self.driver.switch_to.default_content()
        for frame in self.frame_chain:
            self.driver.switch_to.frame(self.driver.find_element(*frame))

    def exit_frame(self) -> None:
        if self.frame_chain:
            try:
                self.driver.switch_to.default_content()
            except Exception:  # noqa: BLE001
                pass

    # -- finds ----------------------------------------------------------

    def find(self, locator: Locator) -> Any:
        return self.search_context.find_element(*locator)

    def find_all(self, locator: Locator) -> List[Any]:
        return self.search_context.find_elements(*locator)

    def count(self, locator: Locator) -> int:
        try:
            return len(self.search_context.find_elements(*locator))
        except Exception:  # noqa: BLE001
            return 0

    def find_or_none(self, locator: Locator) -> Optional[Any]:
        """First match or ``None`` (never raises — a candidate ladder tries many shapes)."""
        try:
            matches = self.search_context.find_elements(*locator)
            return matches[0] if matches else None
        except Exception:  # noqa: BLE001
            return None
