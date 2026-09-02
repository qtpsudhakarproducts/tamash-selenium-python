from tamash_selenium.healer.providers.tamash_rule_based_provider import create_tamash_rule_based_provider

SNAPSHOT = """- generic [ref=e1] [box=0,0,1000,600]:
  - textbox "Employee Id" [ref=e2] [box=0,50,200,30]
  - button "Save" [ref=e3] [box=0,90,120,36]
"""

ADJACENT_SNAPSHOT = """- generic [ref=e1] [box=0,0,1000,600]:
  - generic [ref=e10] [box=0,0,400,40]:
    - text: Employee Id
    - textbox [ref=e2] [box=0,50,200,30]
"""


def test_matches_via_type_hint_in_description():
    provider = create_tamash_rule_based_provider()
    result = provider.suggest_selector({"action": "send_keys", "description": "Employee Id (textbox)",
                                        "aria_snapshot": SNAPSHOT})
    assert result["suggestion"]["ref"] == "e2"


def test_matches_via_adjacent_label():
    provider = create_tamash_rule_based_provider()
    result = provider.suggest_selector({"action": "send_keys", "description": "Employee Id (textbox)",
                                        "aria_snapshot": ADJACENT_SNAPSHOT})
    assert result["suggestion"]["ref"] == "e2"


def test_matches_named_button():
    provider = create_tamash_rule_based_provider()
    result = provider.suggest_selector({"action": "click", "description": "Save (button)",
                                        "aria_snapshot": SNAPSHOT})
    assert result["suggestion"]["ref"] == "e3"


def test_declines_when_no_description():
    provider = create_tamash_rule_based_provider()
    result = provider.suggest_selector({"action": "click", "description": None, "aria_snapshot": SNAPSHOT})
    assert result["suggestion"] == {"strategy": "none"}


def test_declines_unknown_phrase():
    provider = create_tamash_rule_based_provider()
    result = provider.suggest_selector({"action": "click", "description": "Nonexistent Field (textbox)",
                                        "aria_snapshot": SNAPSHOT})
    assert result["suggestion"] == {"strategy": "none"}


def test_action_tactic_always_declines():
    provider = create_tamash_rule_based_provider()
    assert provider.suggest_action_tactic({"action": "click", "error_message": "x"})["tactic"] == "none"
