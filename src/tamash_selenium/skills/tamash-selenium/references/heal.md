# Reviewing, applying, verifying, and landing local heals

Prerequisite: `doctor` reports no `[WARN]`/`[FAIL]` and the driver is wrapped — see
[onboarding.md](onboarding.md) if not.

Every gate below defaults to **continue** except two — genuine ambiguity in REVIEW, and anything
past VERIFY.

## 1. RUN

```bash
pytest          # or the project's command; a nodeid for a named subset
```

Healing is already enabled. Every attempt is appended to `.tamash-selenium/heals.jsonl` and printed:

```
[self-healer] pages/add_employee.py:21 — driver.findElement "First Name (textbox)" -> HEALED
  [provider=tamash, actionRecovery=no, suggested="(By.NAME, \"firstName\")"] — no such element: …
```

Each `heals.jsonl` line carries a ready-to-read `newLocator` alongside the structured `suggestion`.

**GATE — did anything heal?**
- No `HEALED` lines, or no `heals.jsonl` entry with a `suggestion` → **stop.** Report "suite passed,
  nothing needed healing" (or "suite failed, but nothing self-healing can fix — see the failures").
- At least one `HEALED` line with a durable suggestion → continue.

Note but don't act on: lines where the action failed and was **not** healed (`stage=ai_declined`,
`stage=replay_failed`), and `HEALED` lines marked `needsReview=yes` with no durable selector. Carry
these into the final report as things a human must look at.

## 2. REVIEW

```bash
tamash-selenium apply-heals --dry-run
```

**GATE — is each fix trustworthy?**
- **Review column `-`** (the element's own identity: id / name / test id / attribute) → high
  confidence, continue.
- **Review column `! yes`** (a nearby label or structural fallback — `near` / `adjacent` / `scoped`
  XPath) → open the target file and the real page. Form a genuine opinion.
  - Confident it's correct → continue, but say so explicitly in the report.
  - Still unsure → **PAUSE.** Ask the user, naming the fix, its location, and why it's uncertain.

Anything in the **Skipped** table is informational.

## 3. APPLY

```bash
tamash-selenium apply-heals --yes
```

**Always pass `--yes` when you're the one running this.** Never pipe an answer into stdin.

Rewrites the recorded locator, writes `apply-heals-report.{md,json}` under `.tamash-selenium/`
(timestamped copies under `history/`), generates `.tamash-selenium/verify_heals.py`, then archives
and clears `heals.jsonl`.

**GATE**: same count of fixes as the dry-run, no extra skips → continue. Anything unexpected →
**stop** and surface it.

## 4. VERIFY

```bash
python .tamash-selenium/verify_heals.py
```

Sets `HEALER_ENABLED=false` and re-runs **only the affected tests**, proving the rewritten
selectors work standalone.

**GATE — hard gate, never soft:**
- Exit 0, all affected tests green → continue to LAND.
- Any failure → **STOP. Do not land.** Report which test/assertion failed and why.
  `git checkout -- <files>` reverts the rewrites.

## 5. LAND

**Never auto-continues.** Present a summary (fixes applied, anything needing review, still-broken
locators from step 1) and ask the user before committing or opening a PR.
