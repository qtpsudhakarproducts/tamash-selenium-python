import json

from tamash_selenium.healer import heal_log


def test_append_and_read(tmp_path):
    cwd = str(tmp_path)
    heal_log.append_heal_log_entry({"file": "a.py", "line": 3, "suggestion": {"strategy": "id", "id": "u"},
                                    "timestamp": "2026-01-01T00:00:00Z"}, cwd=cwd)
    entries = heal_log.read_heal_log(cwd)
    assert len(entries) == 1 and entries[0]["line"] == 3


def test_find_cached_suggestion_newest_wins(tmp_path):
    cwd = str(tmp_path)
    heal_log.append_heal_log_entry({"file": "a.py", "line": 3, "suggestion": {"strategy": "id", "id": "old"},
                                    "timestamp": "2026-01-01T00:00:00Z"}, cwd=cwd)
    heal_log.append_heal_log_entry({"file": "a.py", "line": 3, "suggestion": {"strategy": "id", "id": "new"},
                                    "timestamp": "2026-02-01T00:00:00Z"}, cwd=cwd)
    cached = heal_log.find_cached_suggestion("a.py:3", cwd=cwd)
    assert cached["suggestion"]["id"] == "new"


def test_find_cached_ignores_audit_only(tmp_path):
    cwd = str(tmp_path)
    heal_log.append_heal_log_entry({"file": "a.py", "line": 3, "suggestion": {"strategy": "id", "id": "real"},
                                    "timestamp": "2026-01-01T00:00:00Z"}, cwd=cwd)
    heal_log.append_heal_log_entry({"file": "a.py", "line": 3, "suggestion": None,
                                    "timestamp": "2026-03-01T00:00:00Z"}, cwd=cwd)
    cached = heal_log.find_cached_suggestion("a.py:3", cwd=cwd)
    assert cached["suggestion"]["id"] == "real"


def test_corrupt_line_survives(tmp_path):
    cwd = str(tmp_path)
    path = tmp_path / ".tamash-selenium" / "heals.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text('{"file":"a.py","line":1,"suggestion":{"strategy":"id","id":"u"}}\nnot json\n', encoding="utf-8")
    assert len(heal_log.read_heal_log(cwd)) == 1


def test_parse_source_location():
    assert heal_log.parse_source_location("pages/login.py:42") == ("pages/login.py", 42)
    assert heal_log.parse_source_location("nope") is None
