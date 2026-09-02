"""pytest plugin — loaded via the ``pytest11`` entry point.

Provides:

* ``--tamash-report <path>`` — write the self-healing-aware HTML step report.
* per-test heal attribution — the healer records which test exercised a healed locator (so
  ``apply-heals`` re-verifies exactly those), and a ``tamash-self-healing.json`` artifact is
  attached to each test that healed.
* a ``tamash_driver`` fixture factory hook (the full self-healing ``driver`` fixture lands with
  the rest of the framework integrations; this plugin already sets up the per-test context so a
  project's own ``driver`` fixture wrapped with ``SelfHealingDriver.wrap`` gets attribution).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import current_test, env, report
from ..current_test import TestInfo

_STORE_DIR = ".tamash-report"


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("tamash-selenium")
    group.addoption("--tamash-report", action="store", default=None, metavar="path",
                    help="Write a self-healing-aware HTML step report to this path.")


def pytest_configure(config: Any) -> None:
    env.load_env()
    config.addinivalue_line("markers", "tamash: mark a test as using a self-healing driver")
    output = config.getoption("--tamash-report") or env.get("TAMASH_REPORT")
    if output:
        report.enable(store_dir=Path.cwd() / _STORE_DIR, output_path=Path(output))


def pytest_runtest_setup(item: Any) -> None:
    current_test.set_current(TestInfo(test_id=item.nodeid, title=item.name))
    report.set_current_test(item.nodeid)


def pytest_runtest_teardown(item: Any) -> None:
    current_test.clear()
    report.set_current_test(None)
    from ..healer import heal_cache
    from .. import tamash as _tamash
    heal_cache.clear()
    _tamash.clear_hint()


try:
    import pytest

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item: Any, call: Any):  # type: ignore[no-redef]
        outcome = yield
        result = outcome.get_result()
        report.record_phase_duration(item.nodeid, result.when, result.duration * 1000)
        if result.when == "call":
            report.set_test_status(item.nodeid, result.outcome)
            _attach_heals(item)
        if result.when == "teardown":
            status = report.get_test_status(item.nodeid) or result.outcome
            report.flush_test(item.nodeid, status)

    def pytest_sessionfinish(session: Any) -> None:  # type: ignore[no-redef]
        if hasattr(session.config, "workerinput"):  # xdist worker — controller aggregates
            return
        report.write_report_if_configured()

except ImportError:  # pragma: no cover - pytest always present when this plugin loads
    pass


def _attach_heals(item: Any) -> None:
    from ..healer.core import get_healing_reports

    mine = [r for r in get_healing_reports() if r.test_id == item.nodeid]
    if not mine:
        return
    healed = sum(1 for r in mine if r.healed)
    summary = f"{healed} healed, {len(mine) - healed} not healed"
    try:
        item.add_report_section("call", "tamash-self-healing", summary)
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------------------------------

try:
    import pytest as _pytest

    @_pytest.fixture(scope="session")
    def _tamash_session():
        from ..lifecycle import SeleniumSession
        session = SeleniumSession()
        yield session
        session.close()

    @_pytest.fixture
    def tamash_driver(_tamash_session):
        """A self-healing ``WebDriver`` managed by tamash-selenium (browser via ``TAMASH_BROWSER`` /
        ``HEADLESS`` / ``TAMASH_REUSE_DRIVER``). Always available under this name."""
        from ..healer import heal_cache
        heal_cache.clear()
        scope = _tamash_session.open_scope()
        try:
            yield scope.driver
        finally:
            _tamash_session.close_scope(scope)

    @_pytest.fixture
    def driver(tamash_driver):
        """Convenience alias — only takes effect when the project doesn't define its own ``driver``
        fixture (a conftest.py fixture always wins over this plugin one). Projects that manage their
        own driver should wrap it: ``driver = SelfHealingDriver.wrap(driver)``."""
        return tamash_driver

except ImportError:  # pragma: no cover
    pass
