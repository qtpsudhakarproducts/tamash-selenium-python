"""Non-browser wiring checks for the Behave / unittest integrations — the browser paths are
covered by tests/integrations/*."""

from __future__ import annotations

import types

import pytest

from tamash_selenium.integrations import behave as behave_int


class _FakeScope:
    def __init__(self):
        self.driver = object()


class _FakeSession:
    instances = []

    def __init__(self):
        _FakeSession.instances.append(self)
        self.closed = False
        self.scopes_closed = []

    def open_scope(self):
        return _FakeScope()

    def close_scope(self, scope):
        self.scopes_closed.append(scope)

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _patch_session(monkeypatch):
    _FakeSession.instances = []
    monkeypatch.setattr(behave_int, "SeleniumSession", _FakeSession)
    from tamash_selenium import report
    monkeypatch.setattr(report, "enable_from_env", lambda: None)
    yield


def _scenario(name="s1", status="passed"):
    return types.SimpleNamespace(name=name, status=status, location="features/x.feature:3", tags=[])


def test_behave_hooks_full_cycle(monkeypatch):
    from tamash_selenium import current_test

    ctx = types.SimpleNamespace()
    behave_int.tamash_before_all(ctx)
    assert len(_FakeSession.instances) == 1

    sc = _scenario()
    behave_int.tamash_before_scenario(ctx, sc)
    assert ctx.driver is not None
    assert current_test.current_test_id() == "features/x.feature:3::s1"

    behave_int.tamash_after_scenario(ctx, sc)
    assert current_test.get() is None
    assert _FakeSession.instances[0].scopes_closed

    behave_int.tamash_after_all(ctx)
    assert _FakeSession.instances[0].closed


def test_behave_before_scenario_bootstraps_without_before_all():
    ctx = types.SimpleNamespace()
    behave_int.tamash_before_scenario(ctx, _scenario())
    assert ctx.driver is not None and len(_FakeSession.instances) == 1


def test_behave_failed_scenario_status(monkeypatch):
    from tamash_selenium import report

    recorded = {}
    monkeypatch.setattr(report, "flush_test", lambda nodeid, status: recorded.setdefault(nodeid, status))
    monkeypatch.setattr(report, "set_test_status", lambda *a: None)
    ctx = types.SimpleNamespace()
    behave_int.tamash_before_all(ctx)
    sc = _scenario(status="failed")
    behave_int.tamash_before_scenario(ctx, sc)
    behave_int.tamash_after_scenario(ctx, sc)
    assert recorded["features/x.feature:3::s1"] == "failed"
