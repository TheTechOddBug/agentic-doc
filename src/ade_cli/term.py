"""Arrow-key selection for interactive prompts, rendered on stderr.

One deliberately small widget — no prompt_toolkit-sized dependency for a
two-entry menu. ``↑``/``↓`` move the pointer (including the Windows console
key forms), a digit jumps to that option, Enter confirms, Esc/Ctrl-C/Ctrl-D
abort. Raw keys come from ``typer.getchar`` (raw terminal mode on POSIX,
``msvcrt`` on Windows — typer vendors click, so this is click's getchar);
callers gate on real terminal-ness — piped stdin gets their typed fallback
— and inject a scripted reader in tests. Rendering is plain SGR: an ASCII
pointer plus bold, and the pointer alone under ``NO_COLOR``.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, TextIO

import typer

_UP = ("\x1b[A", "\x1bOA")  # CSI and SS3 (application keypad mode) forms
_DOWN = ("\x1b[B", "\x1bOB")
_WINDOWS_PREFIX = ("\x00", "\xe0")  # the next key names the arrow: H up, P down
_ENTER = ("\r", "\n")
_ABORT = ("\x1b", "\x03", "\x04")  # Esc; Ctrl-C/D when the reader returns them
_POINTER = "> "


class Unsupported(Exception):
    """Raw keys are unavailable after all; the caller falls back to typed
    input (the menu this widget drew has already been erased)."""


def select(
    options: list[str],
    *,
    default: int = 0,
    getchar: Callable[[], str] | None = None,
    out: TextIO | None = None,
) -> int:
    """Render ``options`` as a pointer menu and return the chosen index.

    The pointer starts on ``default``, so bare Enter means "continue with
    the default". Digits jump the pointer without confirming (a "1⏎" habit
    must not leak the Enter into the next prompt). Raises ``typer.Abort``
    on Esc/Ctrl-C/Ctrl-D — what a typed prompt does — and ``Unsupported``
    when raw reading fails on a stream that claimed to be a terminal.
    """
    if not options:
        raise ValueError("select() needs at least one option")
    if not 0 <= default < len(options):
        raise ValueError(f"default {default} is out of range for {len(options)} options")
    read = getchar or typer.getchar
    out = out if out is not None else sys.stderr
    index = default
    out.write("\x1b[?25l")  # hide the cursor while the pointer is the cursor
    try:
        _draw(out, options, index, first=True)
        while True:
            key = _read_key(read, out, len(options))
            if key in _ABORT:
                raise typer.Abort()
            if key in _UP:
                index = (index - 1) % len(options)
            elif key in _DOWN:
                index = (index + 1) % len(options)
            elif key in _ENTER:
                return index
            elif key.isdigit() and 1 <= int(key) <= len(options):
                index = int(key) - 1
            else:
                continue  # unknown key: no redraw needed
            _draw(out, options, index)
    finally:
        out.write("\x1b[?25h")
        out.flush()


def _read_key(read: Callable[[], str], out: TextIO, lines: int) -> str:
    """One logical key: normalizes the two-read Windows arrow forms, maps
    reader exceptions to abort, and turns a raw-mode failure into
    ``Unsupported`` after erasing the menu so the fallback renders clean."""
    try:
        key = read()
        if key in _WINDOWS_PREFIX:
            second = read()
            return {"H": "\x1b[A", "P": "\x1b[B"}.get(second, "")
        return key
    except (KeyboardInterrupt, EOFError):
        raise typer.Abort() from None
    except OSError:
        _erase(out, lines)
        raise Unsupported() from None


def _draw(out: TextIO, options: list[str], index: int, *, first: bool = False) -> None:
    if not first:
        out.write(f"\x1b[{len(options)}A")  # back up to the first option line
    for i, label in enumerate(options):
        line = f"{_POINTER if i == index else '  '}{label}"
        if i == index:
            line = _bold(line)
        out.write(f"\r\x1b[2K{line}\n")
    out.flush()


def _erase(out: TextIO, lines: int) -> None:
    out.write(f"\r\x1b[{lines}A\x1b[0J")
    out.flush()


def _bold(text: str) -> str:
    if os.environ.get("NO_COLOR"):
        return text
    return f"\x1b[1m{text}\x1b[0m"
