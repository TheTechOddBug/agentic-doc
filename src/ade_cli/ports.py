"""Injected ports: the HTTP transport, the clock, terminal-ness, the
browser opener, and the raw-key reader.

Production builds real ones; tests inject fakes through the CLI seam
(``ctx.obj``). No command in this slice performs HTTP, but every command
runs against these ports so the whole build shares one harness.
"""

from __future__ import annotations

import sys
import time
import webbrowser
from dataclasses import dataclass, field
from typing import Callable, Protocol

import httpx


class Clock(Protocol):
    def now(self) -> float:
        """Wall-clock time (timestamps for humans/bookkeeping)."""
        ...

    def monotonic(self) -> float:
        """Monotonic time (budgets and deadlines; immune to clock jumps)."""
        ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


def open_browser(url: str) -> bool:
    """True only when a browser was plausibly launched; False sends the
    caller to the ``--api-key`` remediation (headless boxes, SSH)."""
    try:
        return webbrowser.open(url)
    except Exception:
        return False


@dataclass
class Ports:
    transport: httpx.BaseTransport = field(default_factory=httpx.HTTPTransport)
    clock: Clock = field(default_factory=SystemClock)
    browser: Callable[[str], bool] = open_browser
    # Raw single-key reader for arrow-key menus. None means typer.getchar
    # (the vendored click getchar — real raw-mode reads); tests inject a
    # scripted reader.
    getchar: Callable[[], str] | None = None
    # Terminal-ness of the real streams, injectable because a test runner's
    # captured streams are never ttys. None means detect.
    stdout_tty: bool | None = None
    stderr_tty: bool | None = None
    stdin_tty: bool | None = None

    def stdout_is_tty(self) -> bool:
        if self.stdout_tty is not None:
            return self.stdout_tty
        return sys.stdout.isatty()

    def stderr_is_tty(self) -> bool:
        if self.stderr_tty is not None:
            return self.stderr_tty
        return sys.stderr.isatty()

    def stdin_is_tty(self) -> bool:
        if self.stdin_tty is not None:
            return self.stdin_tty
        return sys.stdin.isatty()
