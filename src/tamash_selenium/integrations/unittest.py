"""``TamashSeleniumTestCase`` — a stdlib ``unittest`` base class (the counterpart of the Java
``TamashSeleniumTestNgTest``).

    from tamash_selenium.integrations.unittest import TamashSeleniumTestCase
    from selenium.webdriver.common.by import By

    class LoginTest(TamashSeleniumTestCase):
        def test_logs_in(self):
            self.driver.get("https://the-internet.herokuapp.com/login")
            self.driver.find_element(By.ID, "username").send_keys("tomsmith")   # healed if it breaks

Browser via ``TAMASH_BROWSER`` / ``HEADLESS``; ``TAMASH_REUSE_DRIVER=true`` reuses one driver per
class. Per-test heal attribution and the HTML step report (``TAMASH_REPORT=...``) both work.
"""

from __future__ import annotations

import unittest
from typing import Optional

from .. import current_test, env, report
from ..current_test import TestInfo
from ..healer import heal_cache
from ..lifecycle import Scope, SeleniumSession


class TamashSeleniumTestCase(unittest.TestCase):
    _tamash_session: Optional[SeleniumSession] = None
    _tamash_scope: Optional[Scope] = None
    driver = None  # type: ignore[assignment]

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        env.load_env()
        report.enable_from_env()
        cls._tamash_session = SeleniumSession()

    @classmethod
    def tearDownClass(cls) -> None:
        if cls._tamash_session is not None:
            cls._tamash_session.close()
            cls._tamash_session = None
        super().tearDownClass()

    def setUp(self) -> None:
        super().setUp()
        heal_cache.clear()
        assert self._tamash_session is not None
        self.__class__._tamash_scope = self._tamash_session.open_scope()
        self.driver = self.__class__._tamash_scope.driver
        test_id = self.id()
        current_test.set_current(TestInfo(test_id=test_id, title=self._testMethodName))
        report.set_current_test(test_id)

    def tearDown(self) -> None:
        from .. import tamash as _tamash

        test_id = self.id()
        outcome = "failed" if self._outcome_failed() else "passed"
        report.set_test_status(test_id, outcome)
        report.flush_test(test_id, outcome)
        current_test.clear()
        report.set_current_test(None)
        _tamash.clear_hint()
        if self._tamash_session is not None:
            self._tamash_session.close_scope(self.__class__._tamash_scope)
        self.__class__._tamash_scope = None
        super().tearDown()

    def _outcome_failed(self) -> bool:
        try:
            outcome = getattr(self, "_outcome", None)
            errors = getattr(outcome, "errors", None) if outcome is not None else None
            if errors:
                return any(exc for _, exc in errors)
        except Exception:  # noqa: BLE001
            pass
        return False
