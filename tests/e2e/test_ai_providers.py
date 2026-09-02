"""Real-provider heal tests — one per configured provider. Run with:

    HEALER_PROVIDER=openai OPENAI_API_KEY=... OPENAI_MODEL=gpt-4o-mini \\
        pytest tests/e2e/test_ai_providers.py --provider-live -q

With ``HEALER_PROVIDER`` set to an AI provider, the rule-based ``tamash`` provider is never
loaded, so a pass here proves *that provider's* full round trip: snapshot capture -> real API/SDK
call -> parse -> build a locator -> replay the action -> verify it hit the real element.
"""

from __future__ import annotations

import os

import pytest
from selenium.webdriver.common.by import By

from tests.conftest import FIXTURE_LOGIN

pytestmark = [pytest.mark.e2e, pytest.mark.provider_live]

_PROVIDER = os.environ.get("HEALER_PROVIDER", "")


@pytest.fixture()
def ai_driver(raw_chrome, tmp_path, monkeypatch):
    if not _PROVIDER or _PROVIDER == "tamash":
        pytest.skip("set HEALER_PROVIDER to a real AI provider")
    monkeypatch.chdir(tmp_path)
    from tamash_selenium import SelfHealingDriver
    from tamash_selenium.healer import heal_cache
    from tamash_selenium.healer.providers import get_heal_provider, reset_provider_cache

    reset_provider_cache()
    heal_cache.clear()
    if get_heal_provider() is None:
        pytest.skip(f"HEALER_PROVIDER={_PROVIDER} set but its key/model env vars are missing")
    return SelfHealingDriver.wrap(raw_chrome)


def _last_find_heal():
    from tamash_selenium import get_healing_reports
    heals = [r for r in get_healing_reports() if r.healed and r.action == "findElement"]
    return heals[-1] if heals else None


def test_provider_heals_broken_id(ai_driver):
    ai_driver.get(FIXTURE_LOGIN)
    username_field = (By.ID, "username-was-renamed")
    ai_driver.find_element(*username_field).send_keys("tomsmith")

    # Recovered the *real* field — the typed value landed in #username, not "some element".
    assert ai_driver.find_element(By.ID, "username").get_attribute("value") == "tomsmith"

    heal = _last_find_heal()
    assert heal is not None, "expected an AI heal"
    assert heal.provider.split(":")[0] == _PROVIDER, f"healed via {heal.provider}, expected {_PROVIDER}"
    assert heal.suggested_selector in ('(By.ID, "username")', '(By.NAME, "username")'), heal.suggested_selector


def test_provider_heals_broken_css_on_button(ai_driver):
    ai_driver.get(FIXTURE_LOGIN)
    ai_driver.find_element(By.ID, "username").send_keys("admin")
    login_button = (By.CSS_SELECTOR, "button#does-not-exist")
    ai_driver.find_element(*login_button).click()
    assert ai_driver.find_element(By.ID, "result").text == "hello admin"

    heal = _last_find_heal()
    assert heal is not None and heal.provider.split(":")[0] == _PROVIDER


def test_provider_declines_gracefully_on_absent_element(ai_driver):
    """A locator for something genuinely not on the page — the provider should decline and the
    original error re-raise (healing never invents an element)."""
    from selenium.common.exceptions import NoSuchElementException

    ai_driver.get(FIXTURE_LOGIN)
    nonexistent_widget = (By.ID, "a-calendar-datepicker-that-is-not-here")
    with pytest.raises(NoSuchElementException):
        ai_driver.find_element(*nonexistent_widget).click()
