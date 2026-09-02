"""Small concurrency helpers.

* :func:`run_async` — run an ``async`` coroutine to completion from sync code, on a dedicated
  thread with its own event loop (used by the Copilot SDK provider). Selenium itself is sync, so
  unlike the Playwright port there is no running-loop-under-a-greenlet to work around; the
  dedicated thread is only for isolation and a hard timeout.
* :func:`first_result` — run several sync callables in parallel and return the first that yields a
  truthy value (the ``HEALER_PARALLEL`` scoped-vs-full snapshot race in ``core.py``).
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Awaitable, Callable, List, Optional, TypeVar

T = TypeVar("T")


def run_async(coro_factory: "Callable[[], Awaitable[T]]", timeout_s: float) -> Optional[T]:
    result: dict = {}

    def worker() -> None:
        try:
            result["value"] = asyncio.run(asyncio.wait_for(coro_factory(), timeout=timeout_s))
        except BaseException as error:  # noqa: BLE001
            result["error"] = error

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout_s + 5)
    if thread.is_alive():
        raise TimeoutError(f"Timed out after {timeout_s}s waiting for the async provider call")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def first_result(callables: "List[Callable[[], Any]]", timeout_s: Optional[float] = None) -> Any:
    """Run ``callables`` concurrently; return the first truthy result (others are left to finish
    in the background). Returns ``None`` if none produced a truthy value."""
    if not callables:
        return None
    if len(callables) == 1:
        return callables[0]()
    with ThreadPoolExecutor(max_workers=len(callables)) as pool:
        futures = [pool.submit(c) for c in callables]
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=timeout_s, return_when=FIRST_COMPLETED)
            if not done:
                break
            for future in done:
                try:
                    value = future.result()
                except Exception:  # noqa: BLE001
                    value = None
                if value:
                    return value
    return None
