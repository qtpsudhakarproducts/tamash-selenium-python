from __future__ import annotations

import os

import pytest

FIXTURE_LOGIN = """data:text/html,
<html><body>
  <h1>Sign in</h1>
  <form>
    <label for="username">Username</label>
    <input id="username" name="username" type="text">
    <label for="password">Password</label>
    <input id="password" name="password" type="password">
    <button id="submit" type="button">Log in</button>
  </form>
  <div id="result"></div>
  <script>
    document.getElementById('submit').addEventListener('click', function () {
      document.getElementById('result').textContent =
        'hello ' + document.getElementById('username').value;
    });
  </script>
</body></html>
""".replace("\n", "")


@pytest.fixture()
def raw_chrome():
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    driver = webdriver.Chrome(options=options)
    try:
        yield driver
    finally:
        driver.quit()


@pytest.fixture()
def healing_driver(raw_chrome, monkeypatch, tmp_path):
    monkeypatch.delenv("HEALER_ENABLED", raising=False)
    monkeypatch.delenv("HEALER_PROVIDER", raising=False)  # default = tamash rule-based
    monkeypatch.chdir(tmp_path)  # isolate the on-disk .tamash-selenium/heals.jsonl per test
    from tamash_selenium import SelfHealingDriver
    from tamash_selenium.healer import heal_cache
    from tamash_selenium.healer.providers import reset_provider_cache

    reset_provider_cache()
    heal_cache.clear()
    return SelfHealingDriver.wrap(raw_chrome)
