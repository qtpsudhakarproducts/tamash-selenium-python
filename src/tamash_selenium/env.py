"""Config lookup: real OS environment variable -> ``[tool.tamash-selenium]`` in the nearest
``pyproject.toml`` -> a value from a ``.env`` file in the working directory.

Unlike the Java port (which can't mutate its own process environment and keeps ``.env`` values
in a side lookup), Python can — :func:`load_dotenv` populates :data:`os.environ` directly, so the
rest of the package just reads ``os.environ``. This module adds the ``pyproject.toml`` table as a
third, lowest-precedence source and centralises the small amount of typed parsing the healer needs.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:  # python-dotenv is a hard dependency, but stay import-safe if a slim install skipped it.
    from dotenv import load_dotenv as _load_dotenv
except Exception:  # pragma: no cover - defensive
    def _load_dotenv(*_args, **_kwargs) -> bool:  # type: ignore[misc]
        return False

_pyproject_cache: Optional[dict] = None
_dotenv_loaded = False


def load_env(cwd: Optional[Path] = None) -> None:
    """Load ``<cwd>/.env`` into :data:`os.environ` (idempotent; existing vars win)."""
    global _dotenv_loaded
    if _dotenv_loaded:
        return
    _dotenv_loaded = True
    base = Path(cwd) if cwd is not None else Path.cwd()
    _load_dotenv(base / ".env")


def _pyproject_table(cwd: Optional[Path] = None) -> dict:
    global _pyproject_cache
    if _pyproject_cache is not None:
        return _pyproject_cache
    _pyproject_cache = {}
    try:
        import tomllib  # Python 3.11+
    except ModuleNotFoundError:  # pragma: no cover
        try:
            import tomli as tomllib  # type: ignore
        except ModuleNotFoundError:
            return _pyproject_cache
    start = Path(cwd) if cwd is not None else Path.cwd()
    for directory in [start, *start.parents]:
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            try:
                data = tomllib.loads(candidate.read_text(encoding="utf-8"))
                table = data.get("tool", {}).get("tamash-selenium", {})
                if isinstance(table, dict):
                    _pyproject_cache = {str(k).upper().replace("-", "_"): v for k, v in table.items()}
            except Exception:
                pass
            break
    return _pyproject_cache


def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """OS env var -> ``[tool.tamash-selenium]`` -> ``default``. (``.env`` already merged into
    ``os.environ`` by :func:`load_env`.)"""
    from_env = os.environ.get(key)
    if from_env is not None:
        return from_env
    table = _pyproject_table()
    if key in table and table[key] is not None:
        return str(table[key])
    return default


def get_bool(key: str, default: bool = False) -> bool:
    value = get(key)
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def get_float(key: str, default: float) -> float:
    value = get(key)
    if value is None:
        return default
    try:
        parsed = float(str(value).strip())
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def reset_cache() -> None:
    """Test / doctor hook — re-read ``pyproject.toml`` and allow ``.env`` to reload."""
    global _pyproject_cache, _dotenv_loaded
    _pyproject_cache = None
    _dotenv_loaded = False
