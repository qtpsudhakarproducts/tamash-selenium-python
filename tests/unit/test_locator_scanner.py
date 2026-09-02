import textwrap

from tamash_selenium.cli import locator_scanner


def _scan(src):
    return locator_scanner.scan_file("test_x.py", textwrap.dedent(src).lstrip("\n"))


def test_brittle_undescribed_is_high():
    occ = _scan("""
        from selenium.webdriver.common.by import By
        loc1 = (By.CSS_SELECTOR, "div > input:nth-child(2)")
    """)
    assert len(occ) == 1 and occ[0].by == "CSS_SELECTOR" and occ[0].priority == "high"


def test_brittle_described_is_normal():
    occ = _scan("""
        from selenium.webdriver.common.by import By
        username_field = (By.CSS_SELECTOR, "input[name='username']")
    """)
    assert occ[0].priority == "normal" and occ[0].described


def test_by_id_never_high():
    occ = _scan("""
        from selenium.webdriver.common.by import By
        x = (By.ID, "whatever")
    """)
    assert occ[0].priority == "normal"


def test_inline_find_element():
    occ = _scan("""
        from selenium.webdriver.common.by import By
        def f(driver):
            driver.find_element(By.XPATH, "//a[3]").click()
    """)
    assert occ[0].by == "XPATH" and occ[0].priority == "high" and occ[0].in_test_file


def test_self_attr_named():
    occ = locator_scanner.scan_file("pages/login_page.py", textwrap.dedent("""
        from selenium.webdriver.common.by import By
        class P:
            def __init__(self):
                self.login_button = (By.CSS_SELECTOR, ".btn-primary")
    """).lstrip("\n"))
    assert occ[0].described and not occ[0].in_test_file
