---
name: tamash-selenium
description: Set up and run tamash-selenium's self-healing Selenium + Python workflow locally — onboard a pytest / pytest-bdd / Behave / unittest project to its standards, then review, apply, verify, and land runtime heals as permanent fixes.
allowed-tools: Bash(python:*) Bash(pytest:*) Bash(tamash-selenium:*) Bash(behave:*) Bash(git:*) Bash(gh:*) Read Edit Write Grep Glob
---

# tamash-selenium — local self-healing workflow

`tamash-selenium` is a self-healing add-on for Selenium + Python: when `find_element` can't find its
element, a rule-based matcher (default, no key) or an AI model locates the element on the live page
and retries the call at runtime. This skill drives the local loop: run → review → `apply-heals` →
verify → land.

## Start here: run `doctor`

```bash
tamash-selenium doctor
```

- **Any `[FAIL]` or `[WARN]`**, or the driver isn't wrapped with `SelfHealingDriver.wrap(...)` /
  a `tamash-selenium` integration (doctor can't see this — check it yourself) → follow
  **[references/onboarding.md](references/onboarding.md)** first.
- **No `[FAIL]`/`[WARN]`**, driver wrapped → follow **[references/heal.md](references/heal.md)**.
  `[INFO]` rows are observational, never a blocker.

## What this skill does NOT do

- It never invents a healing strategy. Every action is one of tamash-selenium's own commands
  (`tamash-selenium doctor` / `apply-heals`, the generated `verify_heals.py`).
- It never commits or opens a PR without asking first.
- It never touches anything `apply-heals` itself skips (one-shot ref heals with no durable
  selector, assert-absent / `wait.until(...)`-context exclusions).

## Getting this skill into a project

```bash
tamash-selenium init-skill
```

Copies `SKILL.md` + `references/` into `.claude/skills/tamash-selenium/` and
`.agents/skills/tamash-selenium/`. `--target claude|agents` installs one; `--user` installs for
every project on the machine; `--force` overwrites a hand-edited copy. A version marker
(`.tamash-selenium-skill`) lets `doctor` flag a stale copy.
