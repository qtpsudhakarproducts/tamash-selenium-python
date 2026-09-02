"""End-to-end: the HTML step report via TAMASH_REPORT (the plain, non-pytest-plugin path)."""

from __future__ import annotations

import pytest
from selenium.webdriver.common.by import By


pytestmark = pytest.mark.e2e


def test_report_records_actions_and_heals(raw_chrome, tmp_path, monkeypatch, fixture_login):
    out = tmp_path / "report.html"
    monkeypatch.setenv("TAMASH_REPORT", str(out))
    monkeypatch.delenv("HEALER_PROVIDER", raising=False)
    monkeypatch.chdir(tmp_path)

    from tamash_selenium import SelfHealingDriver
    from tamash_selenium import report
    from tamash_selenium.healer import heal_cache

    report.reset()
    heal_cache.clear()
    report.enable_from_env()

    driver = SelfHealingDriver.wrap(raw_chrome)
    driver.get(fixture_login)
    username_field = (By.ID, "user_name_WRONG")
    driver.find_element(*username_field).send_keys("tomsmith")
    driver.find_element(By.ID, "submit").click()

    report._finalize_session()
    html = out.read_text(encoding="utf-8")
    assert "tamash-selenium report" in html
    assert "healed" in html.lower()
    assert "(By.ID, &quot;username&quot;)" in html or "By.ID" in html
    assert "send_keys" in html and "click" in html
