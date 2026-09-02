from tamash_selenium.source_locations import decode_variable_name


def test_prefix_style():
    d = decode_variable_name("txtEmployeeId")
    assert d is not None and d.name == "Employee Id" and d.type_hint == "textbox"


def test_snake_prefix():
    d = decode_variable_name("btn_submit")
    assert d is not None and d.name == "Submit" and d.type_hint == "button"


def test_suffix_style():
    d = decode_variable_name("submit_button")
    assert d is not None and d.name == "Submit" and d.type_hint == "button"


def test_camel_words():
    d = decode_variable_name("usernameField")
    assert d is not None and d.name == "Username" and d.type_hint == "textbox"


def test_no_type_hint():
    d = decode_variable_name("loginPage")
    assert d is not None and d.type_hint is None and d.name == "Login Page"


def test_meaningless_declines():
    assert decode_variable_name("el1") is None
    assert decode_variable_name("locator") is None
    assert decode_variable_name("temp") is None


def test_acronym_split():
    d = decode_variable_name("txtIDNumber")
    assert d is not None and d.name == "ID Number"
