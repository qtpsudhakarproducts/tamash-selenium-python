# tamash-selenium (Python)

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

Plug-and-play self-healing for **Selenium + Python**. Wrap your `WebDriver` once and every
`find_element` through it — in Page Objects, helper/util layers, inside a `WebDriverWait` —
recovers automatically when a locator breaks. Nothing else changes.

```python
from selenium import webdriver
from tamash_selenium import SelfHealingDriver

driver = SelfHealingDriver.wrap(webdriver.Chrome())
```

That's the whole integration.

> Also available for **Selenium Java** (`com.vibetestq.qtpsudhakar:tamash-selenium` on Maven
> Central) and for **Playwright** — TypeScript & Python (`tamash-playwright`). Same idea, one
> package per ecosystem.

## Why you need this

Websites change. A button gets renamed or moved and your test can't find it anymore — even though
the app works fine for real users. Normally that's a broken test.

`tamash-selenium` fixes it: when `find_element` can't find an element, it locates it on the live
page — with a rule-based matcher (default, no key, no network) or an AI model — and retries. If it
can't, the test fails exactly as it would have without the package. Healing never masks a real
failure.

## Step 1: Install

```sh
pip install tamash-selenium
```

Pulls in Selenium 4 (which provisions the browser drivers itself since 4.6). Requires **Python 3.9+**.

Optional AI-provider extras: `pip install 'tamash-selenium[anthropic]'` /
`'tamash-selenium[claude-subscription]'` / `'tamash-selenium[copilot-subscription]'`. The
`openai` / `gemini` / `ollama` providers need nothing extra.

## Step 2: Wrap the driver

Wherever you create the driver — a fixture, a `DriverFactory`, a `setUp`:

```python
from tamash_selenium import SelfHealingDriver

driver = SelfHealingDriver.wrap(my_driver)   # Remote / Grid / cloud all fine
```

Everything downstream is now healing-aware — plain `find_element`, Page Objects, waits.

Wrapping also pins Selenium's implicit wait to 0 (mixing implicit + explicit waits is an
anti-pattern, and a high implicit wait delays healing) — set `TAMASH_KEEP_IMPLICIT_WAIT=true` to
keep yours.

### Or let an integration own the lifecycle

| Framework | How |
|---|---|
| **pytest** | The plugin auto-loads. Use the `driver` (or `tamash_driver`) fixture — or wrap your own `driver` fixture with `SelfHealingDriver.wrap`. |
| **pytest-bdd** | Same — scenarios are pytest tests; use `tamash_driver` in step functions. |
| **Behave** | Delegate the four `environment.py` hooks to `tamash_selenium.integrations.behave` (see its docstring). |
| **unittest** | `class LoginTest(TamashSeleniumTestCase): ...` — use `self.driver`. |

## Step 3 (optional): connect an AI provider

With no configuration, healing uses the rule-based **`tamash`** provider — no key, no network, no
tokens; it text-matches the element's decoded name against the page's accessibility tree and never
guesses. Good for well-named suites.

For stronger healing, set a provider in a `.env` at your project root (or real env vars, or a
`[tool.tamash-selenium]` table in `pyproject.toml`):

| Provider | Auth |
|---|---|
| `ollama` | `OLLAMA_API_KEY` + `OLLAMA_MODEL` (Ollama Cloud — free key) |
| `ollama-local` | `OLLAMA_LOCAL_MODEL` (+ `OLLAMA_LOCAL_BASE_URL`; key optional) |
| `openai` | `OPENAI_API_KEY` + `OPENAI_MODEL` |
| `anthropic` | `ANTHROPIC_API_KEY` + `ANTHROPIC_MODEL` (needs the `[anthropic]` extra) |
| `gemini` | `GEMINI_API_KEY` + `GEMINI_MODEL` |
| `claude-subscription` | `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) — bills your Claude subscription |
| `copilot-subscription` | the `[copilot-subscription]` extra + the `copilot` CLI signed in |
| `tamash` | **nothing** — the default |

```sh
HEALER_PROVIDER=ollama
OLLAMA_MODEL=gpt-oss:120b
OLLAMA_API_KEY=paste_your_key_here
```

`HEALER_ENABLED=false` turns healing off entirely (e.g. per-CI-run).

## Step 4: Check your setup

```sh
tamash-selenium doctor
```

Provider connectivity (a live call), the implicit-wait note, and a scan for brittle locators
bound to non-descriptive names.

## How it heals

When `find_element` can't find its element:

1. **Cache** — a selector already healed this run for that locator (any caller, including a wait's
   next poll) is reused instantly.
2. **DOM snapshot** — a JS accessibility tree of the page is captured; the provider is shown the
   relevant slice (matched to the element's decoded name), or the full tree.
3. **`ref` + durable derivation** — the provider picks the element; a stable locator is derived
   for it (`By.ID` → `By.NAME` → a `data-testid` / `aria-label` CSS → link text → a structural
   XPath), verified against the live element before it's trusted.
4. **Action recovery** (opt-in, `HEALER_ACTION_RECOVERY_ENABLED=true`) — scroll / JS-click / wait
   / dispatch when the element is found but the action is blocked.

Every heal logs `[self-healer] … -> HEALED [provider=…, suggested="(By.ID, \"username\")"]`.

## Writing locators the healer can work with

`(By.ID, ...)` / `(By.NAME, ...)` carry their own meaning. A raw `(By.CSS_SELECTOR, ...)` /
`(By.XPATH, ...)` doesn't — bind it to a descriptive variable / attribute and the healer decodes
the name: `txt_employee_id` → "Employee Id (textbox)", `submit_button` → "Submit (button)"
(deterministic, no AI). Decoding works when the locator is on the same line as its `find_element`
call, or is a page-object attribute the call references by name.

**Explicit hint** — for keyword-driven suites or heavy indirection:

```python
from tamash_selenium import hint

def click(locator, name):
    with hint(name):
        driver.find_element(*locator).click()
```

## What gets healed (and what doesn't)

Intercepted on `WebElement`: `click`, `send_keys`, `clear`, `submit`, and the read methods
(`get_attribute`, `get_dom_attribute`, `get_dom_property`, `get_property`, `value_of_css_property`,
`is_displayed`, `is_enabled`, `is_selected`). Plus `find_element` / `find_elements` on the driver
and on elements.

Not touched: the `ActionChains` API, `WebElement.text` (a Python property — can't be intercepted
per-instance; use `get_attribute("textContent")` if you need it healed), and `find_elements`
(never healed — use `driver.find_elements(by, value)` for absence checks).

**Assert-absent is never healed**: `pytest.raises(NoSuchElementException)`,
`EC.invisibility_of_element_located`, `EC.staleness_of`, or a helper whose name contains
`absent` / `not_present` / `gone`. `HEALER_ASSERTIONS=strict` also refuses to heal a locator
resolved inside an assertion; `HEALER_ASSERTIONS=warn` heals but prints an end-of-run summary.

## Making a heal permanent: `apply-heals`

A runtime heal fixes the current run; `apply-heals` writes it into source:

```sh
tamash-selenium apply-heals --dry-run   # preview
tamash-selenium apply-heals             # apply (prompts first)
#  (By.CSS_SELECTOR, "#old")   →  (By.ID, "username")
#  driver.find_element(By.CSS_SELECTOR, "#old")  →  driver.find_element(By.ID, "username")
```

It rewrites an inline `find_element(By.*, "…")` call or a `LOGIN = (By.*, "…")` tuple constant (via
the heal log's recorded declaration line), writes Markdown + JSON reports under
`.tamash-selenium/`, and generates `verify_heals.py` that re-runs exactly the affected pytest node
ids with `HEALER_ENABLED=false`.

## HTML step report

```sh
pytest --tamash-report=report.html          # pytest
TAMASH_REPORT=report.html python my_script.py   # plain / Behave / unittest
```

Per test: step timeline, which steps healed (recovered selector, provider, token cost), the DOM
snapshot on an unrecovered failure. Zero overhead when unset.

## Agent skill

```sh
tamash-selenium init-skill
```

Copies a coding-agent skill (`SKILL.md` + `references/`) into `.claude/skills/tamash-selenium/`
and `.agents/skills/tamash-selenium/` that drives the local run → review → `apply-heals` → verify
→ land loop.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `HEALER_ENABLED` | `true` | Master switch. `false` / `0` turns healing off. |
| `HEALER_PROVIDER` | `tamash` | `ollama` \| `ollama-local` \| `openai` \| `anthropic` \| `gemini` \| `claude-subscription` \| `copilot-subscription` \| `tamash`. |
| `HEALER_ASSERTIONS` | `heal` | `heal` \| `warn` \| `strict`. |
| `HEALER_ACTION_RECOVERY_ENABLED` | `false` | Opt-in scroll / force / wait / dispatch recovery. |
| `HEALER_PARALLEL` | `false` | Race the scoped + full-snapshot provider calls concurrently. |
| `TAMASH_KEEP_IMPLICIT_WAIT` | `false` | `true` keeps your implicit wait. |
| `TAMASH_BROWSER` | `chrome` | `chrome` \| `firefox` \| `edge` \| `safari` (integrations only). |
| `HEADLESS` | `true` | `false` runs headed (integrations only). |
| `TAMASH_REUSE_DRIVER` | `false` | One driver per class / feature instead of per test. |
| `TAMASH_ACTION_TIMEOUT_MS` | `20000` | Bounds the healer's own snapshot / JS calls. |
| `TAMASH_REPORT` | unset | Output path for the HTML step report. |
| `TAMASH_DEBUG` | unset | Print DOM-snapshot capture diagnostics. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` / `OPENAI_BASE_URL` | — | OpenAI. |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | — | Anthropic. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` / `GEMINI_THINKING` | — / — / `off` | Gemini. |
| `OLLAMA_API_KEY` / `OLLAMA_MODEL` / `OLLAMA_BASE_URL` | — / — / `https://ollama.com` | Ollama Cloud. |
| `OLLAMA_LOCAL_MODEL` / `OLLAMA_LOCAL_BASE_URL` / `OLLAMA_LOCAL_API_KEY` | — / `http://localhost:11434` / — | Self-hosted Ollama. |
| `CLAUDE_CODE_OAUTH_TOKEN` / `CLAUDE_SUBSCRIPTION_MODEL` | — / `claude-haiku-4-5` | `claude-subscription`. |
| `COPILOT_SUBSCRIPTION_MODEL` | `mai-code-1-flash-picker` | `copilot-subscription`. |

## License

[Apache License, Version 2.0](LICENSE).
