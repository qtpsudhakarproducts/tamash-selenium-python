# Changelog

## 0.1.0

First real release on PyPI — replaces the `0.0.1` placeholder that raised `ImportError`.
`pip install tamash-selenium`.

Full feature parity with the Java `tamash-selenium`, ported to Python + Selenium:

- **`SelfHealingDriver.wrap(driver)`** — instance monkey-patching of `find_element` /
  `find_elements` and the interactive `WebElement` methods; iframe-aware; implicit wait pinned to 0.
- **Healer** — positive / negative / disk caches, DOM-snapshot capture (injected JS accessibility
  tree), rule-based `tamash` provider (default, no key), AI providers (`openai`, `gemini`,
  `ollama`, `ollama-local`, `anthropic`, `claude-subscription`, `copilot-subscription`), durable
  locator derivation, opt-in action recovery, assert-absent / `WebDriverWait` handling.
- **CLI** — `tamash-selenium doctor` / `apply-heals` / `init-skill`.
- **HTML step report** — `--tamash-report` (pytest) / `TAMASH_REPORT` (env).
- **Integrations** — pytest plugin (`driver` / `tamash_driver` fixtures), pytest-bdd, Behave hooks,
  `TamashSeleniumTestCase` for unittest, plus plain `wrap()`.

Improvements over the Java port:

- `apply-heals` rewrites source via Python's `ast` (not regex) — handles inline
  `find_element(By.X, "…")` args and `LOGIN = (By.X, "…")` tuple constants.
- Exact caller `file:line` via `traceback` — no source-root probing heuristics.
- Native `os.environ` + `.env` + a `[tool.tamash-selenium]` `pyproject.toml` table.
- `HEALER_PARALLEL=true` races the scoped and full-snapshot provider calls concurrently.
