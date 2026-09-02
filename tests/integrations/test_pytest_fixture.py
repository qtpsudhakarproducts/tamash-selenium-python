"""The pytest `driver` / `tamash_driver` fixture (from the auto-loaded pytest11 plugin)."""

from __future__ import annotations

import pytest
from selenium.webdriver.common.by import By


pytestmark = pytest.mark.e2e


def test_tamash_driver_fixture_heals(tamash_driver, monkeypatch, tmp_path, fixture_login):
    monkeypatch.chdir(tmp_path)
    tamash_driver.get(fixture_login)
    username_field = (By.ID, "user_name_WRONG")
    tamash_driver.find_element(*username_field).send_keys("admin")
    assert tamash_driver.find_element(By.ID, "username").get_attribute("value") == "admin"

    from tamash_selenium import get_healing_reports
    mine = [r for r in get_healing_reports() if r.test_id and r.test_id.endswith("test_tamash_driver_fixture_heals")]
    assert mine and mine[-1].healed


def test_driver_alias_also_works(driver, fixture_login):
    driver.get(fixture_login)
    assert driver.find_element(By.ID, "submit").text == "Log in"
