"""The arrow-key selector widget, driven through its scripted-reader seam.

CLI-level tests (test_auth*.py) cover the wiring — when the selector
engages versus the typed fallback; these cover the widget's key handling
and screen contract directly.
"""

from __future__ import annotations

import io

import typer
import pytest

from ade_cli import term

OPTIONS = ["one", "two", "three"]


def run(keys: list[str], *, default: int = 0) -> tuple[int, str]:
    out = io.StringIO()
    remaining = iter(keys)
    index = term.select(
        list(OPTIONS), default=default, getchar=lambda: next(remaining), out=out
    )
    return index, out.getvalue()


def test_enter_alone_returns_the_default():
    index, out = run(["\r"])

    assert index == 0
    assert "> one" in out  # the pointer sits on the default from the start


def test_down_then_enter_moves_the_pointer():
    index, out = run(["\x1b[B", "\r"])

    assert index == 1
    assert "> two" in out


def test_up_wraps_to_the_last_option():
    index, _ = run(["\x1b[A", "\r"])

    assert index == 2


def test_windows_console_arrows_are_the_two_read_form():
    index, _ = run(["\xe0", "P", "\r"])  # prefix byte, then P = down

    assert index == 1


def test_a_digit_jumps_the_pointer_but_enter_confirms():
    # "1⏎" habits must not leak the Enter into the next (hidden key) prompt.
    index, out = run(["3", "\r"])

    assert index == 2
    assert "> three" in out


def test_unknown_keys_are_ignored():
    index, _ = run(["z", "\x1b[C", "\r"])  # a letter and a right-arrow

    assert index == 0


def test_escape_aborts_like_a_typed_prompt():
    with pytest.raises(typer.Abort):
        run(["\x1b"])


def test_ctrl_c_from_the_reader_aborts():
    def interrupt() -> str:
        raise KeyboardInterrupt

    with pytest.raises(typer.Abort):
        term.select(list(OPTIONS), getchar=interrupt, out=io.StringIO())


def test_raw_mode_failure_erases_the_menu_and_says_unsupported():
    def broken() -> str:
        raise OSError("stdin has no raw mode")

    out = io.StringIO()
    with pytest.raises(term.Unsupported):
        term.select(list(OPTIONS), getchar=broken, out=out)

    # The drawn menu was wiped so the caller's typed fallback renders clean.
    assert "\x1b[0J" in out.getvalue()
    assert out.getvalue().index("> one") < out.getvalue().index("\x1b[0J")


def test_cursor_is_hidden_during_and_restored_after():
    _, out = run(["\r"])

    assert out.startswith("\x1b[?25l")
    assert out.endswith("\x1b[?25h")


def test_misuse_is_a_loud_value_error_before_any_drawing():
    out = io.StringIO()

    with pytest.raises(ValueError):
        term.select([], out=out)
    with pytest.raises(ValueError):
        term.select(["a", "b"], default=2, out=out)

    assert out.getvalue() == ""  # rejected before touching the screen
