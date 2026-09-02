import textwrap

from tamash_selenium import source_locations as sl


def _write(tmp_path, body):
    p = tmp_path / "sample_page.py"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_extract_variable_name_assignment(tmp_path):
    p = _write(tmp_path, """
        x = 1
        username_field = (By.ID, "old")
    """)
    assert sl.extract_variable_name(f"{p}:3") == "username_field"


def test_extract_variable_name_self_attr(tmp_path):
    p = _write(tmp_path, """
        class P:
            def __init__(self):
                self.login_button = (By.CSS_SELECTOR, "#old")
    """)
    assert sl.extract_variable_name(f"{p}:4") == "login_button"


def test_find_assignment_equals_ignores_string_eq():
    line = 'x = driver.find_element(By.CSS_SELECTOR, "input[name=\\"u\\"]")'
    idx = sl._find_assignment_equals(line)
    assert line[idx] == "=" and line[:idx].strip() == "x"


def test_extract_locator_reference(tmp_path):
    p = _write(tmp_path, """
        driver.find_element(*login_button).click()
    """)
    assert sl.extract_locator_reference(f"{p}:2") == "login_button"


def test_classify_assertion_and_negative():
    assert sl.is_assertion_line('assert driver.find_element(By.ID, "x").text == "Y"')
    assert sl.is_negative_line("wait.until(EC.invisibility_of_element_located(loc))")
    assert not sl.is_assertion_line("driver.find_element(By.ID, 'x').click()")


def test_describe_from_decodes():
    assert sl.describe_from("txtEmployeeId", "('id', 'x')") == "Employee Id (textbox)"
    assert sl.describe_from(None, "('id', 'x')") == "('id', 'x')"
