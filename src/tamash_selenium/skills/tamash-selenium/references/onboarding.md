# Onboarding a project to tamash-selenium's standards

Use this when `doctor` reports a `[WARN]`/`[FAIL]`, or the `WebDriver` isn't wrapped. Sections are
independent — skip any that don't apply. After each fix, confirm it worked before moving on.
`[INFO]` rows are context, not a checklist.

## 1. The `WebDriver` isn't wrapped (doctor can't detect this — check it yourself)

Self-healing only happens for elements found through a wrapped driver. Find where the driver is
created (`webdriver.Chrome(...)`, a factory, a pytest fixture, a Behave `before_all`). Exactly one
must be true:

- **Plain wrap** — the driver passes through `SelfHealingDriver.wrap(...)` before any test uses it:

  ```python
  from selenium import webdriver
  from tamash_selenium import SelfHealingDriver

  driver = SelfHealingDriver.wrap(webdriver.Chrome(options=options))
  ```

- **An integration owns the lifecycle** — the test gets its driver from the `tamash_selenium`
  pytest `driver` fixture, `TamashSeleniumTestCase` (unittest), or the Behave / pytest-bdd hooks.
  Those wrap internally.

`SelfHealingDriver.wrap(...)` pins Selenium's implicit wait to 0 (`TAMASH_KEEP_IMPLICIT_WAIT=true`
to keep yours — but mixing implicit + explicit waits is a Selenium anti-pattern).

**Confirm**: add a throwaway test with a deliberately broken locator on a page the suite visits
(change `(By.ID, "username")` to `(By.ID, "user_name")`), run it, look for `[self-healer] … -> HEALED`
on the console. Remove the throwaway test afterward.

## 2. AI provider — pick one (or stay on the free rule-based default)

- **`[INFO] HEALER_PROVIDER is not set — defaulting to the rule-based tamash provider`** → not a
  problem. `tamash` needs no key, no network, never guesses. Only move to an AI provider if the
  user wants a higher recovery rate. **Ask — don't assume.**
- **`[FAIL] HEALER_PROVIDER=<x>, ... env vars are missing`** → misconfigured; fix it (below).
- **`[OK] Connected to <provider>`** → done.

Providers (set in a `.env` at the project root, or real env vars, or `[tool.tamash-selenium]` in
`pyproject.toml`):

- Free AI start: `HEALER_PROVIDER=ollama`, `OLLAMA_MODEL=gpt-oss:120b`, `OLLAMA_API_KEY=` (free key
  from `ollama.com/settings/keys`).
- API-key: `openai` / `anthropic` / `gemini` (`*_API_KEY` + `*_MODEL`). `anthropic` needs
  `pip install 'tamash-selenium[anthropic]'`.
- Subscription: `claude-subscription` (`CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`;
  `pip install 'tamash-selenium[claude-subscription]'`) or `copilot-subscription`
  (`pip install 'tamash-selenium[copilot-subscription]'`, Python 3.11+, `copilot` CLI signed in).
- Self-hosted Ollama: `ollama-local` — `OLLAMA_LOCAL_BASE_URL` + `OLLAMA_LOCAL_MODEL`.
- Zero AI: `tamash` (the default).

**Never handle the real key value** — write the variable name with an empty value and have the
user paste the key into the file. Never echo a key in chat, a commit, a log, or a report. Ensure
`.env` is gitignored.

**Confirm**: re-run `tamash-selenium doctor` — the AI Provider section must be `[OK]`.

## 3. Brittle locators with no descriptive name

`doctor` lists these:

```
[WARN] Found 4 brittle CSS/XPath locator(s) with no descriptive name:
```

tamash-selenium derives the element's description from the **variable / attribute the locator is
bound to** (`username_field = (By.CSS_SELECTOR, ...)` → "Username (textbox)"). A raw
`(By.XPATH, "//div/input[2]")` passed inline, or bound to `loc1`, gives the healer nothing.

For each flagged locator: open the file, read the real page/component, choose a genuinely accurate
name, and bind the locator to a well-named constant or page-object attribute — a pure rename, safe
to apply across all flagged locators in one pass. For a keyword layer where the name can't reach
the call site, wrap the action in `with hint("First name field"): ...` (`from tamash_selenium import hint`).

**Confirm**: re-run `doctor` — the count should drop.

## 4. Locators written directly in test files (should be in a Page Object)

Reported as `[INFO]`, not `[WARN]` — inline locators still heal fine; this is maintainability.
**Do not mechanically extract every one without asking.** Look for an existing Page Object pattern
and follow it; check whether a flagged file is deliberately inline (a `demo`/`inline` name, a
README note); ask the user for scope.
