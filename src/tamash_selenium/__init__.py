"""tamash-selenium is a Java / Maven package, not a Python one.

This PyPI name is a placeholder held by the maintainers of tamash-selenium so it can't be
squatted. There is no Python distribution and none is planned — the self-healing engine for
Selenium is a Java library.

  Maven Central : com.vibetestq.qtpsudhakar:tamash-selenium
  Docs          : https://qtpsudhakarproducts.github.io/tamash-selenium/
  Source        : https://github.com/qtpsudhakarproducts/tamash-selenium

For Python + Playwright self-healing, see `tamash-playwright` on PyPI instead.
"""

__version__ = "0.0.1"

_MESSAGE = (
    "tamash-selenium is a Java / Maven package, not a Python one.\n"
    "  Maven Central: com.vibetestq.qtpsudhakar:tamash-selenium\n"
    "  Docs: https://qtpsudhakarproducts.github.io/tamash-selenium/\n"
    "If you want Python + Playwright self-healing, install `tamash-playwright` instead."
)

raise ImportError(_MESSAGE)
