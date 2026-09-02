"""Framework integrations.

* **pytest** — the ``pytest11`` plugin auto-loads: a self-healing ``driver`` / ``tamash_driver``
  fixture, per-test heal attribution, ``--tamash-report``.
* **pytest-bdd** — covered by the pytest plugin; see :mod:`tamash_selenium.integrations.pytest_bdd`.
* **Behave** — delegate the four ``environment.py`` hooks to
  :mod:`tamash_selenium.integrations.behave`.
* **unittest** — extend :class:`tamash_selenium.integrations.unittest.TamashSeleniumTestCase`.
* **anything else** — ``SelfHealingDriver.wrap(driver)`` on the one line where the driver is made.
"""

from .unittest import TamashSeleniumTestCase

__all__ = ["TamashSeleniumTestCase"]
