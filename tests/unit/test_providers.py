import pytest

from tamash_selenium.healer.providers import get_heal_provider, reset_provider_cache


@pytest.fixture(autouse=True)
def _clean_provider_cache():
    reset_provider_cache()
    yield
    reset_provider_cache()


def test_default_is_tamash(monkeypatch):
    monkeypatch.delenv("HEALER_PROVIDER", raising=False)
    assert get_heal_provider().name == "tamash"


def test_unknown_provider_is_none(monkeypatch):
    monkeypatch.setenv("HEALER_PROVIDER", "nope")
    assert get_heal_provider() is None


def test_openai_missing_key_is_none(monkeypatch):
    monkeypatch.setenv("HEALER_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert get_heal_provider() is None


def test_openai_compatible_parses_response(monkeypatch):
    from tamash_selenium.healer.providers import http, openai_compatible

    captured = {}

    def fake_post(label, url, headers, body, timeout_ms):
        captured["url"] = url
        captured["model"] = body["model"]
        return {
            "choices": [{"message": {"content": '{"strategy":"id","id":"username"}'}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }

    monkeypatch.setattr(http, "post_json", fake_post)
    provider = openai_compatible.create("openai:gpt-x", "https://api/chat/completions",
                                        {"authorization": "Bearer k"}, "gpt-x")
    result = provider.suggest_selector({"action": "send_keys", "description": "Username (textbox)",
                                        "aria_snapshot": "- textbox [ref=e1]"})
    assert result["suggestion"] == {"strategy": "id", "id": "username"}
    assert result["usage"]["total_tokens"] == 15
    assert captured["model"] == "gpt-x"


def test_openai_compatible_bad_json_returns_none(monkeypatch):
    from tamash_selenium.healer.providers import http, openai_compatible

    monkeypatch.setattr(http, "post_json", lambda *a, **k: {"choices": [{"message": {"content": "sorry no"}}]})
    provider = openai_compatible.create("x", "u", {}, "m")
    assert provider.suggest_selector({"action": "click", "description": "x", "aria_snapshot": "y"}) is None


def test_ollama_usage_shape(monkeypatch):
    from tamash_selenium.healer.providers import http, ollama_provider

    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setenv("OLLAMA_MODEL", "gpt-oss:120b")
    monkeypatch.setattr(http, "post_json", lambda *a, **k: {
        "message": {"content": '{"strategy":"css","css":".x"}'},
        "prompt_eval_count": 100, "eval_count": 20,
    })
    provider = ollama_provider.create_ollama_provider()
    result = provider.suggest_selector({"action": "click", "description": "X (button)", "aria_snapshot": "z"})
    assert result["suggestion"]["strategy"] == "css"
    assert result["usage"] == {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
