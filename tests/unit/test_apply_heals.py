import json
import textwrap

from tamash_selenium.cli import apply_heals


def _seed(tmp_path, rel, source, entries):
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(textwrap.dedent(source).lstrip("\n"), encoding="utf-8")
    log = tmp_path / ".tamash-selenium" / "heals.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_inline_find_element_rewrite(tmp_path):
    _seed(tmp_path, "pages/p.py", '''
        from selenium.webdriver.common.by import By

        def go(driver):
            driver.find_element(By.CSS_SELECTOR, "#old").click()
    ''', [{"file": "pages/p.py", "line": 4, "action": "click",
           "suggestion": {"strategy": "id", "id": "submit"}, "timestamp": "2026-01-01T00:00:00Z",
           "test_id": "tests/test_p.py::test_go"}])
    plan = apply_heals.plan_fixes(str(tmp_path))
    applied = [o for o in plan["outcomes"] if o.applied]
    assert len(applied) == 1
    assert applied[0].before == 'By.CSS_SELECTOR, "#old"'
    assert applied[0].after == 'By.ID, "submit"'
    new_source = plan["file_contents"][str(tmp_path / "pages/p.py")]
    assert 'driver.find_element(By.ID, "submit").click()' in new_source
    assert plan["affected_tests"] == ["tests/test_p.py::test_go"]


def test_tuple_declaration_rewrite(tmp_path):
    _seed(tmp_path, "pages/p.py", '''
        from selenium.webdriver.common.by import By

        LOGIN = (By.XPATH, "//old")
    ''', [{"file": "pages/p.py", "line": 10, "action": "click",
           "suggestion": {"strategy": "css", "css": "[data-testid='login']"},
           "declarationLocation": "pages/p.py:3", "timestamp": "2026-01-01T00:00:00Z"}])
    plan = apply_heals.plan_fixes(str(tmp_path))
    applied = [o for o in plan["outcomes"] if o.applied]
    assert len(applied) == 1 and applied[0].after == '(By.CSS_SELECTOR, "[data-testid=\'login\']")'


def test_self_attr_rewrite(tmp_path):
    _seed(tmp_path, "pages/p.py", '''
        from selenium.webdriver.common.by import By

        class P:
            def __init__(self):
                self.user = (By.CSS_SELECTOR, "#u-old")
    ''', [{"file": "pages/p.py", "line": 5, "action": "send_keys",
           "suggestion": {"strategy": "name", "name": "username"},
           "declarationLocation": "pages/p.py:5", "timestamp": "2026-01-01T00:00:00Z"}])
    plan = apply_heals.plan_fixes(str(tmp_path))
    applied = [o for o in plan["outcomes"] if o.applied]
    assert applied and applied[0].after == '(By.NAME, "username")'


def test_missing_file_reported(tmp_path):
    log = tmp_path / ".tamash-selenium" / "heals.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"file": "gone.py", "line": 1, "suggestion": {"strategy": "id", "id": "x"},
                               "timestamp": "2026-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
    plan = apply_heals.plan_fixes(str(tmp_path))
    assert plan["outcomes"] and not plan["outcomes"][0].applied
    assert "no longer exists" in plan["outcomes"][0].reason


def test_latest_per_location_prefers_suggestion(tmp_path):
    _seed(tmp_path, "p.py", "from selenium.webdriver.common.by import By\nX = (By.XPATH, '//a')\n", [
        {"file": "p.py", "line": 2, "suggestion": {"strategy": "id", "id": "real"},
         "declarationLocation": "p.py:2", "timestamp": "2026-01-01T00:00:00Z"},
        {"file": "p.py", "line": 2, "suggestion": None, "declarationLocation": "p.py:2",
         "timestamp": "2026-06-01T00:00:00Z"},
    ])
    plan = apply_heals.plan_fixes(str(tmp_path))
    applied = [o for o in plan["outcomes"] if o.applied]
    assert applied and applied[0].after == '(By.ID, "real")'
