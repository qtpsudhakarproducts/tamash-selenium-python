"""Shared HTTP POST for the raw-HTTP providers (OpenAI / Gemini / Ollama), plus the diagnostic
classifiers behind every provider's ``diagnose()``.

``post_json`` mirrors the Java ``Http.java`` retry policy: one quick retry on a 5xx or on a 429
that names a short ``Retry-After`` / ``retryDelay``; a bare 429 (per-minute quota) fails fast
rather than stalling the heal.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request
from typing import Callable, Optional

from .types import ProviderDiagnosis

_MAX_RETRY_WAIT_S = 8.0
_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+)s"')


def post_json(label: str, url: str, headers: dict, body: dict, timeout_ms: float) -> Optional[dict]:
    timeout_s = max((timeout_ms or 15000) / 1000, 1.0)
    data = json.dumps(body).encode("utf-8")
    full_headers = {"content-type": "application/json", **headers}
    retried = False
    while True:
        request = urllib.request.Request(url, data=data, method="POST", headers=full_headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            status = error.code
            try:
                text = error.read().decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                text = ""
            if not retried:
                wait_s = None
                if 500 <= status <= 504:
                    wait_s = 1.0
                elif status == 429:
                    wait_s = _retry_after_s(error, text)
                if wait_s is not None and wait_s <= _MAX_RETRY_WAIT_S:
                    retried = True
                    time.sleep(wait_s)
                    continue
            print(f"[self-healer] {label} request failed: {status} {_first_line(text)}")
            return None
        except (TimeoutError, urllib.error.URLError) as error:
            if not retried and isinstance(error, TimeoutError):
                retried = True
                continue
            print(f"[self-healer] {label} provider error: {error}")
            return None
        except Exception as error:  # noqa: BLE001
            print(f"[self-healer] {label} provider error: {error}")
            return None


def _retry_after_s(error: urllib.error.HTTPError, body_text: str) -> Optional[float]:
    header = error.headers.get("retry-after") if error.headers else None
    if header:
        try:
            return float(header.strip())
        except ValueError:
            pass
    m = _RETRY_DELAY_RE.search(body_text or "")
    return float(m.group(1)) if m else None


def _first_line(text: Optional[str]) -> str:
    if not text:
        return ""
    line = text.split("\n", 1)[0]
    return line[:300]


# --------------------------------------------------------------------------------------------------
# Diagnostics (doctor only)
# --------------------------------------------------------------------------------------------------

_MAX_DETAIL = 300
_WS_RE = re.compile(r"\s+")
_TIMEOUT_RE = re.compile(r"\baborted\b|timed?\s?out|timeout", re.IGNORECASE)
_MODEL_RE = re.compile(r"model", re.IGNORECASE)
_MODEL_REASON_RE = re.compile(r"not\s?found|does not exist|not available|unavailable|unknown|unsupported|invalid|no such", re.IGNORECASE)
_NETWORK_RE = re.compile(r"ENOTFOUND|EAI_AGAIN|ECONNREFUSED|ECONNRESET|ETIMEDOUT|fetch failed|network|getaddrinfo|socket hang up", re.IGNORECASE)
_AUTH_RE = re.compile(r"unauthor|authenticat|forbidden|\bapi[-_ ]?key\b|credit balance|quota|billing|permission|invalid[_ ]?x?[-_ ]?api|login", re.IGNORECASE)


def _truncate(s: str) -> str:
    trimmed = _WS_RE.sub(" ", s.strip())
    return f"{trimmed[:_MAX_DETAIL - 1]}…" if len(trimmed) > _MAX_DETAIL else trimmed


def classify_thrown_error(error: BaseException) -> ProviderDiagnosis:
    message = str(error) or "unknown error"
    detail = _truncate(message)
    if isinstance(error, (FileNotFoundError, ModuleNotFoundError, ImportError)):
        return {"category": "not-installed", "detail": detail}
    if isinstance(error, TimeoutError) or _TIMEOUT_RE.search(message):
        return {"category": "timeout", "detail": detail}
    status = getattr(error, "status_code", None) or getattr(error, "status", None) or getattr(error, "code", None)
    status = status if isinstance(status, int) else None
    if status in (401, 403, 429):
        return {"category": "not-authenticated", "detail": detail}
    if status == 404 or (_MODEL_RE.search(message) and _MODEL_REASON_RE.search(message)):
        return {"category": "bad-model", "detail": detail}
    if status is not None and status >= 500:
        return {"category": "network", "detail": detail}
    if _NETWORK_RE.search(message):
        return {"category": "network", "detail": detail}
    if _AUTH_RE.search(message):
        return {"category": "not-authenticated", "detail": detail}
    return {"category": "unknown", "detail": detail}


def classify_http_status(status: int, body_text: str) -> ProviderDiagnosis:
    body = _truncate(body_text)
    detail = f"HTTP {status}: {body}" if body else f"HTTP {status}"
    if status in (401, 403, 429):
        return {"category": "not-authenticated", "detail": detail}
    if status == 404 or _MODEL_RE.search(body_text):
        return {"category": "bad-model", "detail": detail}
    if status >= 500:
        return {"category": "network", "detail": detail}
    return {"category": "unknown", "detail": detail}


def probe_http_endpoint(url: str, headers: dict, body: dict, timeout_s: float,
                        extract_content: Callable[[Optional[dict]], Optional[str]]) -> ProviderDiagnosis:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"content-type": "application/json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            text = error.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = ""
        return classify_http_status(error.code, text)
    except Exception as error:  # noqa: BLE001
        return classify_thrown_error(error)
    content = extract_content(payload)
    if not content:
        return {"category": "bad-response", "detail": "endpoint replied 2xx but with no message content"}
    return {"category": "ok", "detail": "endpoint responded within the timeout"}
