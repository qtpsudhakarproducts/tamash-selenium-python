"""Plain ANSI styling + a box-drawing table, no dependency. Colour is disabled outside a real
terminal (piped output, ``NO_COLOR``, ``TERM=dumb``). Ported from ``tamash-playwright-python``.
"""

from __future__ import annotations

import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

USE_COLOR = (
    bool(getattr(sys.stdout, "isatty", lambda: False)())
    and not os.environ.get("NO_COLOR")
    and os.environ.get("TERM") != "dumb"
)
_ESC = "\x1b"


def _paint(code: str, text: str) -> str:
    return f"{_ESC}[{code}m{text}{_ESC}[0m" if USE_COLOR else text


def bold(s: str) -> str:
    return _paint("1", s)


def dim(s: str) -> str:
    return _paint("2", s)


def green(s: str) -> str:
    return _paint("32", s)


def yellow(s: str) -> str:
    return _paint("33", s)


def red(s: str) -> str:
    return _paint("31", s)


def cyan(s: str) -> str:
    return _paint("36", s)


def section(title: str) -> None:
    print(f"\n{bold(title)}")


_ANSI_PATTERN = re.compile(rf"{_ESC}\[[0-9;]*m")


def visible_length(s: str) -> int:
    return len(_ANSI_PATTERN.sub("", s))


def _pad_cell(s: str, width: int) -> str:
    return s + " " * max(0, width - visible_length(s))


def truncate_end(s: str, max_len: int) -> str:
    return f"{s[: max_len - 1]}…" if len(s) > max_len else s


def truncate_start(s: str, max_len: int) -> str:
    return f"…{s[len(s) - max_len + 1:]}" if len(s) > max_len else s


def render_table(headers: list, rows: list, indent: str = "  ") -> None:
    widths = [
        max(visible_length(h), *(visible_length(r[i]) if i < len(r) else 0 for r in rows)) if rows else visible_length(h)
        for i, h in enumerate(headers)
    ]

    def rule(left: str, mid: str, right: str) -> str:
        return indent + left + mid.join("─" * (w + 2) for w in widths) + right

    def row_line(cells: list) -> str:
        return f"{indent}│ " + " │ ".join(_pad_cell(c, widths[i]) for i, c in enumerate(cells)) + " │"

    print(rule("┌", "┬", "┐"))
    print(row_line([bold(h) for h in headers]))
    print(rule("├", "┼", "┤"))
    for row in rows:
        print(row_line(row))
    print(rule("└", "┴", "┘"))


def is_interactive() -> bool:
    return (
        bool(getattr(sys.stdout, "isatty", lambda: False)())
        and bool(getattr(sys.stdin, "isatty", lambda: False)())
        and not os.environ.get("CI")
    )


_YES_RE = re.compile(r"^y(es)?$", re.IGNORECASE)


def confirm(question: str) -> bool:
    try:
        answer = input(question)
    except EOFError:
        return False
    return bool(_YES_RE.match(answer.strip()))
