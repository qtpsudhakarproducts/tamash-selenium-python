from tamash_selenium.healer.durable_locator import (
    find_rule_based_match,
    generate_replacement_call,
    is_positional_selector_text,
    looks_auto_generated,
    parse_aria_ai_tree,
    role_node_test,
    strip_generic_role_suffix,
    to_by,
    xpath_literal,
)

SNAPSHOT = """- generic [ref=e1] [box=0,0,1000,600]:
  - heading "Sign in" [ref=e2] [box=0,0,300,40]
  - textbox "Username" [ref=e3] [box=0,50,200,30]
  - textbox "Password" [ref=e4] [box=0,90,200,30]
  - button "Log in" [ref=e5] [box=0,130,120,36]
"""


def test_parse_tree_shapes():
    nodes = parse_aria_ai_tree(SNAPSHOT)
    roles = [n.role for n in nodes if n.role]
    assert "heading" in roles and roles.count("textbox") == 2 and "button" in roles
    names = [n.name for n in nodes if n.name]
    assert "Username" in names and "Password" in names and "Log in" in names


def test_rule_based_match_by_nearby_label():
    nodes = parse_aria_ai_tree(SNAPSHOT)
    match = find_rule_based_match(nodes, "Username", "textbox")
    assert match["strategy"] == "ref" and match["ref"] == "e3"


def test_rule_based_match_named_button():
    nodes = parse_aria_ai_tree(SNAPSHOT)
    match = find_rule_based_match(nodes, "Log in", "button")
    assert match == {"strategy": "ref", "ref": "e5"}


def test_rule_based_declines_unknown_phrase():
    nodes = parse_aria_ai_tree(SNAPSHOT)
    assert find_rule_based_match(nodes, "word that is nowhere", "textbox")["strategy"] == "none"


def test_to_by_variants():
    assert to_by({"strategy": "id", "id": "u"}) == ("id", "u")
    assert to_by({"strategy": "name", "name": "u"}) == ("name", "u")
    assert to_by({"strategy": "css", "css": ".x"}) == ("css selector", ".x")
    assert to_by({"strategy": "xpath", "xpath": "//x"}) == ("xpath", "//x")
    assert to_by({"strategy": "none"}) is None


def test_generate_replacement_call():
    assert generate_replacement_call({"strategy": "id", "id": "u"}) == '(By.ID, "u")'
    assert generate_replacement_call({"strategy": "name", "name": "u"}) == '(By.NAME, "u")'
    assert generate_replacement_call({"strategy": "ref", "ref": "e1"}) is None


def test_positional_detection():
    assert is_positional_selector_text("//div[3]")
    assert is_positional_selector_text("ul li:nth-child(2)")
    assert not is_positional_selector_text("#username")


def test_auto_generated_ids():
    assert looks_auto_generated(":r3:")
    assert looks_auto_generated("mui-1523")
    assert not looks_auto_generated("username")


def test_strip_role_suffix():
    assert strip_generic_role_suffix("Employee Id Textbox") == "Employee Id"
    assert strip_generic_role_suffix("Save Button") == "Save"


def test_xpath_literal_quoting():
    assert xpath_literal("plain") == "'plain'"
    assert xpath_literal("it's") == '"it\'s"'
    assert "concat(" in xpath_literal("a'b\"c")


def test_role_node_test():
    assert "input" in role_node_test("textbox")
    assert role_node_test("link") == "a"
