from __future__ import annotations

import pytest
from selenium.webdriver.common.by import By

from tamash_selenium.integrations.unittest import TamashSeleniumTestCase
from tests.conftest import FIXTURE_LOGIN

pytestmark = pytest.mark.e2e


class TamashUnittestSmoke(TamashSeleniumTestCase):
    def test_heals_broken_locator(self):
        self.driver.get(FIXTURE_LOGIN)
        username_field = (By.ID, "user_name_WRONG")
        self.driver.find_element(*username_field).send_keys("admin")
        self.assertEqual(self.driver.find_element(By.ID, "username").get_attribute("value"), "admin")

        from tamash_selenium import get_healing_reports
        mine = [r for r in get_healing_reports() if r.test_id and "test_heals_broken_locator" in r.test_id]
        self.assertTrue(mine and mine[-1].healed)
