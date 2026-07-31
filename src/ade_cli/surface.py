"""Which surface hosts this invocation (#50): agent host × terminal.

No OS API names the terminal a process runs in; the signal is the
environment variables hosts and terminals set for their children, plus
tty-ness. Detection is therefore a pure function over ``(env, tty)`` —
injectable, unit-testable, and incapable of touching the real process
state. Two independent dimensions come back: the *agent host* (Claude
Code, Codex, …), absent for a plain shell, and the *terminal*, which
always resolves — to a coarse bucket (``terminal``, ``non-tty``) when
nothing more specific matches. Detection never raises and never blocks
a command; a stale marker table degrades to the coarse buckets.

Tokens ride two places: appended to the identity User-Agent as
``host/<x> term/<y>`` (the gateway appends ``tokens()`` after the
command token), and
recorded on every usage-ledger event (#52). The vocabulary is documented
in docs/telemetry.md; extend the tables and the doc together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Surface:
    host: str | None  # agent-host token; None outside any agent
    term: str  # terminal token; always set, coarse buckets included


# Agent hosts, first match wins. Markers are the variables each host sets
# for every child process (verified 2026-07; the set will drift — that is
# why unknown hosts simply come back None, never an error). Sources:
#   claude-code: https://code.claude.com/docs/en/env-vars
#   codex:       https://developers.openai.com/codex/config-advanced
#                https://github.com/openai/codex/issues/19937
#   gemini-cli / cursor (and cross-host survey):
#     https://glama.ai/mcp/servers/@cameroncooke/XcodeBuildMCP/blob/ddea433f736484c4d20d2d1d1457bfe06f512719/src/utils/environment.ts
_HOST_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude-code", ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")),
    ("codex", ("CODEX_SANDBOX", "CODEX_THREAD_ID")),
    ("gemini-cli", ("GEMINI_CLI",)),
    ("cursor", ("CURSOR_AGENT", "CURSOR_TRACE_ID")),
)

# TERM_PROGRAM values → tokens. Only values in this map are trusted;
# anything else is an unknown terminal and degrades to the coarse bucket
# rather than shipping arbitrary environment text into telemetry.
_TERM_PROGRAMS: Mapping[str, str] = {
    "iTerm.app": "iterm",
    "Apple_Terminal": "apple-terminal",
    "vscode": "vscode",
    "WarpTerminal": "warp",
    "WezTerm": "wezterm",
    "ghostty": "ghostty",
    "Hyper": "hyper",
    "tmux": "tmux",
}

# Terminal-specific variables, for terminals that predate TERM_PROGRAM or
# never set it. Ordered: first match wins.
_TERM_MARKERS: tuple[tuple[str, str], ...] = (
    ("ITERM_SESSION_ID", "iterm"),
    ("WEZTERM_EXECUTABLE", "wezterm"),
    ("GHOSTTY_RESOURCES_DIR", "ghostty"),
    ("KITTY_WINDOW_ID", "kitty"),
    ("ALACRITTY_WINDOW_ID", "alacritty"),
    ("WT_SESSION", "windows-terminal"),
    ("KONSOLE_VERSION", "konsole"),
    ("GNOME_TERMINAL_SCREEN", "gnome-terminal"),
    ("VTE_VERSION", "vte"),
)

# CI systems set their own flag plus (almost always) CI itself. Every
# marker maps to the same coarse "ci" token today, so order is cosmetic —
# but keep the generic CI last so per-system tokens, if ever added, can't
# be shadowed by it.
_CI_MARKERS: tuple[str, ...] = (
    "GITHUB_ACTIONS",
    "GITLAB_CI",
    "CIRCLECI",
    "BUILDKITE",
    "JENKINS_URL",
    "TEAMCITY_VERSION",
    "CI",
)


def _truthy(value: str | None) -> bool:
    """Set-and-not-disabled: CI conventions include CI=true and CI=1, and
    an explicit CI=false must not read as CI."""
    return value is not None and value != "" and value.lower() not in ("0", "false")


def detect(env: Mapping[str, str], *, stdout_is_tty: bool) -> Surface:
    """Classify the surface. Pure over its inputs; total — every
    environment maps to some Surface, unknown ones to the coarse buckets."""
    host = None
    for token, markers in _HOST_MARKERS:
        if any(_truthy(env.get(marker)) for marker in markers):
            host = token
            break

    return Surface(host=host, term=_detect_term(env, stdout_is_tty))


def _detect_term(env: Mapping[str, str], stdout_is_tty: bool) -> str:
    # CI first: a runner may leak a TERM_PROGRAM from its image, and "ci"
    # is the segmentation that matters there. tmux next: it masks the
    # outer terminal anyway, so name the thing actually attached.
    if any(_truthy(env.get(marker)) for marker in _CI_MARKERS):
        return "ci"
    if env.get("TMUX"):
        return "tmux"
    program = _TERM_PROGRAMS.get(env.get("TERM_PROGRAM", ""))
    if program is not None:
        return program
    for marker, token in _TERM_MARKERS:
        if env.get(marker):
            return token
    # Env said nothing. A tty means *some* interactive terminal ran us;
    # no tty means piped, scripted, or otherwise headless.
    return "terminal" if stdout_is_tty else "non-tty"


def marker_variables() -> frozenset[str]:
    """Every environment variable detection consults — the shield list a
    hermetic harness clears so the machine running the tests (an agent
    host, a CI runner) never leaks into detection results."""
    names = {"TMUX", "TERM_PROGRAM"}
    for _, markers in _HOST_MARKERS:
        names.update(markers)
    names.update(marker for marker, _ in _TERM_MARKERS)
    names.update(_CI_MARKERS)
    return frozenset(names)


def tokens(surface: Surface) -> list[str]:
    """The ``key/value`` tokens the identity User-Agent appends —
    e.g. ``["host/claude-code", "term/iterm"]``; host is omitted outside
    any agent."""
    out = []
    if surface.host is not None:
        out.append(f"host/{surface.host}")
    out.append(f"term/{surface.term}")
    return out
