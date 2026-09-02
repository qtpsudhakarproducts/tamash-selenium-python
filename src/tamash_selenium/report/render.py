"""Renders the collected per-test steps into one self-contained HTML file. Ported from
``tamash-playwright-python``'s ``report/render.py`` (Playwright-agnostic — only the title and the
dropped ``used_vision`` field differ)."""

from __future__ import annotations

import html as html_lib
from typing import Any, List

_CSS = """
:root {
  --bg: #f5f6f8; --surface: #ffffff; --border: #e1e4ea; --text: #1a2233; --text-muted: #6b7385;
  --accent: #3d5a80; --pass: #2f9e6e; --pass-bg: #e7f6ef; --fail: #d64545; --fail-bg: #fbeaea;
  --healed: #c9820c; --healed-bg: #fbf1de; --skip: #8b93a3; --skip-bg: #eef0f3;
  --cat-action: #5b6b85; --cat-assert: #7c3aed; --cat-fixture: #0f766e;
  --step-indent: calc(8px + 0.6rem + 140px + 0.6rem + 56px + 0.6rem);
}
* { box-sizing: border-box; }
body { margin: 0; padding: 2.5rem 1.5rem 4rem; background: var(--bg); color: var(--text);
  font-family: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif; font-size: 14px; line-height: 1.5; }
main { max-width: 920px; margin: 0 auto; display: flex; flex-direction: column; gap: 0.75rem; }
header.summary { max-width: 920px; margin: 0 auto 2rem; }
h1 { font-size: 1.5rem; font-weight: 650; letter-spacing: -0.01em; margin: 0 0 1.1rem; }
.stat-row { display: flex; flex-wrap: wrap; gap: 0.6rem; }
.stat { background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 0.6rem 1rem; min-width: 88px; text-align: center; }
.stat-value { display: block; font-family: ui-monospace, Consolas, monospace; font-variant-numeric: tabular-nums;
  font-size: 1.25rem; font-weight: 600; }
.stat-label { display: block; font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase;
  letter-spacing: 0.05em; margin-top: 0.15rem; }
.stat.pass .stat-value { color: var(--pass); } .stat.fail .stat-value { color: var(--fail); }
.stat.healed .stat-value { color: var(--healed); }
.charts { display: grid; grid-template-columns: 1fr 1fr; gap: 0.75rem; max-width: 920px; margin: 0 auto 1.5rem; }
@media (max-width: 640px) { .charts { grid-template-columns: 1fr; } }
.chart { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 1rem 1.1rem 1.1rem; }
.chart h2 { margin: 0 0 0.7rem; font-size: 0.72rem; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.05em; color: var(--text-muted); }
.chart-row { display: flex; align-items: center; gap: 0.6rem; padding: 0.28rem 0; }
.chart-label { flex-shrink: 0; width: 40%; font-size: 0.78rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chart-track { flex: 1; height: 10px; background: var(--bg); border-radius: 5px; overflow: hidden; }
.chart-bar { height: 100%; border-radius: 5px; background: var(--accent); }
.chart-row.failed .chart-bar { background: var(--fail); }
.chart-value { flex-shrink: 0; min-width: 64px; text-align: right; font-family: ui-monospace, Consolas, monospace;
  font-variant-numeric: tabular-nums; font-size: 0.76rem; color: var(--text-muted); }
.chart-empty { font-size: 0.8rem; color: var(--text-muted); }
.test { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
.test-header { display: flex; align-items: center; gap: 0.75rem; padding: 0.85rem 1.1rem; cursor: pointer; user-select: none; }
.badge { flex-shrink: 0; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase;
  padding: 0.2rem 0.5rem; border-radius: 5px; }
.badge.passed { color: var(--pass); background: var(--pass-bg); }
.badge.failed { color: var(--fail); background: var(--fail-bg); }
.badge.skipped { color: var(--skip); background: var(--skip-bg); }
.test-title { flex: 1; font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.test-meta { flex-shrink: 0; font-family: ui-monospace, Consolas, monospace; font-variant-numeric: tabular-nums;
  color: var(--text-muted); font-size: 0.8rem; }
.healed-chip { flex-shrink: 0; font-size: 0.7rem; color: var(--healed); background: var(--healed-bg);
  padding: 0.15rem 0.45rem; border-radius: 5px; font-weight: 600; }
.chevron { flex-shrink: 0; color: var(--text-muted); transition: transform 0.15s ease; }
.test.open .chevron { transform: rotate(90deg); }
.steps { display: none; border-top: 1px solid var(--border); padding: 0.6rem 1.1rem 0.9rem; }
.test.open .steps { display: block; }
.step-group[hidden] { display: none; }
.step { display: flex; align-items: center; gap: 0.6rem; padding: 0.3rem 0; }
.step-category { flex-shrink: 0; width: 8px; height: 8px; border-radius: 50%; background: var(--cat-action); }
.step-group[data-category="assert"] .step-category { background: var(--cat-assert); }
.step-group[data-category="fixture"] .step-category { background: var(--cat-fixture); }
.step-bar-track { flex-shrink: 0; width: 140px; height: 8px; background: var(--bg); border-radius: 4px; overflow: hidden; }
.step-bar { height: 100%; border-radius: 4px; background: var(--text-muted); }
.step.healed .step-bar { background: var(--healed); } .step.failed .step-bar { background: var(--fail); }
.step-title { flex: 1; font-family: ui-monospace, Consolas, monospace; font-size: 0.82rem; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.step.healed .step-title { color: var(--healed); } .step.failed .step-title { color: var(--fail); }
.step-action { flex-shrink: 0; font-family: ui-monospace, Consolas, monospace; font-size: 0.66rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.03em; color: var(--text-muted); border: 1px solid var(--border);
  border-radius: 4px; padding: 0.08rem 0.4rem; min-width: 56px; text-align: center; }
.step.healed .step-action { color: var(--healed); border-color: var(--healed); }
.step.failed .step-action { color: var(--fail); border-color: var(--fail); }
.step-locator, .step-value, .step-note, .step-aria-snapshot { padding-left: var(--step-indent); }
.step-locator { font-family: ui-monospace, Consolas, monospace; font-size: 0.76rem; color: var(--text-muted);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin: -0.05rem 0 0.3rem; }
.step-value { font-family: ui-monospace, Consolas, monospace; font-size: 0.76rem; color: var(--accent);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; margin: -0.05rem 0 0.3rem; }
.step-value::before { content: "\\2192  "; color: var(--text-muted); }
.step-duration { flex-shrink: 0; font-family: ui-monospace, Consolas, monospace; font-variant-numeric: tabular-nums;
  font-size: 0.78rem; color: var(--text-muted); min-width: 48px; text-align: right; }
.step-note { margin: 0.15rem 0 0.35rem; font-size: 0.78rem; color: var(--text-muted); }
.step-note.healed-note { color: var(--healed); }
.step-aria-snapshot { margin: 0.2rem 0 0.4rem; font-size: 0.78rem; }
.step-aria-snapshot summary { color: var(--text-muted); cursor: pointer; }
.step-aria-snapshot pre { max-height: 280px; overflow: auto; margin: 0.3rem 0 0; padding: 0.5rem 0.6rem;
  border: 1px solid var(--border); border-radius: 6px; background: var(--surface); white-space: pre-wrap; word-break: break-word; }
.filter-chips { display: flex; gap: 0.4rem; margin-bottom: 0.6rem; }
.filter-chip { font-size: 0.68rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em;
  padding: 0.2rem 0.55rem; border-radius: 999px; border: 1px solid var(--border); color: var(--text-muted);
  background: var(--surface); cursor: pointer; user-select: none; }
.filter-chip.active { color: var(--surface); background: var(--accent); border-color: var(--accent); }
.empty { text-align: center; color: var(--text-muted); padding: 3rem 0; }
"""

_JS = """
document.querySelectorAll('.test-header').forEach(function (el) {
  el.addEventListener('click', function () { el.parentElement.classList.toggle('open'); });
});
document.querySelectorAll('.filter-chips').forEach(function (chips) {
  chips.addEventListener('click', function (event) {
    var chip = event.target.closest('.filter-chip');
    if (!chip) return;
    var category = chip.dataset.filter;
    chips.querySelectorAll('.filter-chip').forEach(function (c) { c.classList.toggle('active', c === chip); });
    chips.closest('.steps').querySelectorAll('.step-group').forEach(function (group) {
      group.hidden = !(category === 'all' || group.dataset.category === category);
    });
  });
});
"""


def _esc(value: Any) -> str:
    return html_lib.escape(str(value), quote=True)


def _effective_tokens(usage: Any) -> int:
    if not usage:
        return 0
    return usage.get("total_tokens") or ((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0))


def _format_tokens(usage: Any) -> str:
    total = _effective_tokens(usage)
    if not total:
        return ""
    parts = []
    if usage.get("input_tokens") is not None:
        parts.append(f"{usage['input_tokens']} in")
    if usage.get("output_tokens") is not None:
        parts.append(f"{usage['output_tokens']} out")
    breakdown = f" ({', '.join(parts)})" if parts else ""
    return f" &mdash; {_esc(f'{total} tokens')}{_esc(breakdown)}"


def _short(nodeid: str) -> str:
    return nodeid.split("::", 1)[-1]


def _bar_chart(rows: List[tuple], value_fmt: Any) -> str:
    if not rows:
        return '<p class="chart-empty">No data.</p>'
    max_value = max(v for _, v, _ in rows) or 1.0
    out = []
    for label, value, failed in rows:
        pct = max(2.0, (value / max_value) * 100)
        out.append(f'<div class="chart-row {"failed" if failed else ""}">'
                   f'<div class="chart-label">{_esc(label)}</div>'
                   f'<div class="chart-track"><div class="chart-bar" style="width:{pct:.0f}%"></div></div>'
                   f'<div class="chart-value">{_esc(value_fmt(value))}</div></div>')
    return "\n".join(out)


def _render_step(step: dict, max_duration_ms: float) -> str:
    css_class = "healed" if step.get("healed") else ("failed" if step.get("error") else "")
    category = step.get("category", "action")
    pct = 0.0 if max_duration_ms <= 0 else max(4.0, (step["duration_ms"] / max_duration_ms) * 100)
    note = ""
    if step.get("healed") and step.get("suggested_selector"):
        review = " &mdash; <strong>needs review</strong>" if step.get("needs_review") else ""
        recovery = " (via action recovery)" if step.get("used_action_recovery") else ""
        note = (f'<div class="step-note healed-note">healed via {_esc(step.get("provider") or "?")}{recovery} '
                f'&mdash; recovered as {_esc(step["suggested_selector"])}{_format_tokens(step.get("token_usage"))}{review}</div>')
        if step.get("needs_review") and step.get("review_note"):
            note += f'<div class="step-note">{_esc(step["review_note"])}</div>'
    elif step.get("error"):
        note = f'<div class="step-note">{_esc(step["error"])}{_format_tokens(step.get("token_usage"))}</div>'

    locator_line = f'<div class="step-locator">{_esc(step["locator"])}</div>' if step.get("locator") else ""
    value_line = f'<div class="step-value">{_esc(step["value"])}</div>' if step.get("value") is not None else ""
    aria_line = ""
    if step.get("aria_snapshot"):
        aria_line = ('<details class="step-aria-snapshot"><summary>DOM snapshot at failure</summary>'
                     f'<pre>{_esc(step["aria_snapshot"])}</pre></details>')

    return (f'<div class="step-group" data-category="{_esc(category)}">'
            f'<div class="step {css_class}">'
            f'<span class="step-category"></span>'
            f'<div class="step-bar-track"><div class="step-bar" style="width:{pct:.0f}%"></div></div>'
            f'<span class="step-action">{_esc(step["action"])}</span>'
            f'<div class="step-title">{_esc(step["element"])}</div>'
            f'<div class="step-duration">{step["duration_ms"]:.0f}ms</div>'
            f"</div>{locator_line}{value_line}{note}{aria_line}</div>")


def _phase_breakdown(phase_durations: dict) -> str:
    parts = [f"{p} {phase_durations[p] / 1000:.1f}s" for p in ("setup", "call", "teardown") if p in phase_durations]
    return " &middot; ".join(parts)


def _render_test(test: dict) -> str:
    steps = test.get("steps", [])
    max_duration = max((s["duration_ms"] for s in steps), default=0.0)
    healed_count = sum(1 for s in steps if s.get("healed"))
    categories = {s.get("category", "action") for s in steps}
    steps_html = "\n".join(_render_step(s, max_duration) for s in steps) or '<div class="step-note">No actions recorded.</div>'
    healed_chip = f'<span class="healed-chip">{healed_count} healed</span>' if healed_count else ""
    pb = _phase_breakdown(test.get("phase_durations", {}))
    phase_line = f'<span class="test-meta">{pb}</span>' if pb else ""

    chips = [("all", "All")] + [(c, c.capitalize()) for c in ("action", "assert", "fixture") if c in categories]
    filter_chips = ""
    if steps and len(chips) > 2:
        chips_html = "\n".join(
            f'<span class="filter-chip{" active" if k == "all" else ""}" data-filter="{k}">{lbl}</span>'
            for k, lbl in chips)
        filter_chips = f'<div class="filter-chips">{chips_html}</div>'

    return (f'<div class="test"><div class="test-header">'
            f'<span class="badge {_esc(test["status"])}">{_esc(test["status"])}</span>'
            f'<span class="test-title">{_esc(test["nodeid"])}</span>{healed_chip}'
            f'<span class="test-meta">{test["duration_ms"]:.0f}ms</span>{phase_line}'
            f'<span class="chevron">&#9656;</span></div>'
            f'<div class="steps">{filter_chips}{steps_html}</div></div>')


def render(tests: List[dict]) -> str:
    total = len(tests)
    passed = sum(1 for t in tests if t["status"] == "passed")
    failed = sum(1 for t in tests if t["status"] == "failed")
    skipped = sum(1 for t in tests if t["status"] == "skipped")
    total_duration_ms = sum(t["duration_ms"] for t in tests)
    healed_steps = sum(1 for t in tests for s in t.get("steps", []) if s.get("healed"))
    total_tokens = sum(_effective_tokens(s.get("token_usage")) for t in tests for s in t.get("steps", []))
    tokens_stat = (f'<div class="stat"><span class="stat-value">{total_tokens:,}</span>'
                   f'<span class="stat-label">tokens used</span></div>' if total_tokens else "")

    body = "\n".join(_render_test(t) for t in tests) or '<p class="empty">No tests recorded.</p>'
    duration_chart = _bar_chart(
        [(_short(t["nodeid"]), t["duration_ms"], t["status"] == "failed") for t in tests],
        lambda v: f"{v / 1000:.1f}s")
    token_rows = [(_short(t["nodeid"]), float(sum(_effective_tokens(s.get("token_usage")) for s in t.get("steps", []))), False)
                  for t in tests if sum(_effective_tokens(s.get("token_usage")) for s in t.get("steps", []))]
    tokens_chart = _bar_chart(token_rows, lambda v: f"{v:,.0f}") if token_rows else '<p class="chart-empty">No healing calls made.</p>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" /><title>tamash-selenium report</title>
<style>{_CSS}</style></head><body>
  <header class="summary">
    <h1>tamash-selenium report</h1>
    <div class="stat-row">
      <div class="stat"><span class="stat-value">{total}</span><span class="stat-label">tests</span></div>
      <div class="stat pass"><span class="stat-value">{passed}</span><span class="stat-label">passed</span></div>
      <div class="stat fail"><span class="stat-value">{failed}</span><span class="stat-label">failed</span></div>
      <div class="stat"><span class="stat-value">{skipped}</span><span class="stat-label">skipped</span></div>
      <div class="stat healed"><span class="stat-value">{healed_steps}</span><span class="stat-label">healed steps</span></div>
      {tokens_stat}
      <div class="stat"><span class="stat-value">{total_duration_ms / 1000:.1f}s</span><span class="stat-label">duration</span></div>
    </div>
  </header>
  <div class="charts">
    <div class="chart"><h2>Duration by test</h2>{duration_chart}</div>
    <div class="chart"><h2>Tokens by test</h2>{tokens_chart}</div>
  </div>
  <main>{body}</main>
  <script>{_JS}</script>
</body></html>
"""
