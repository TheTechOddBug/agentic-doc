"""Surface detection (#50): pure over a faked environment, two
independent dimensions, coarse buckets instead of errors."""

from __future__ import annotations

import pytest

from ade_cli.surface import Surface, detect, tokens


# --- agent hosts: every known marker classifies, first match wins ---


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"CLAUDECODE": "1"}, "claude-code"),
        ({"CLAUDE_CODE_ENTRYPOINT": "cli"}, "claude-code"),
        ({"CODEX_SANDBOX": "seatbelt"}, "codex"),
        ({"CODEX_THREAD_ID": "thread-123"}, "codex"),
        ({"GEMINI_CLI": "1"}, "gemini-cli"),
        ({"CURSOR_AGENT": "1"}, "cursor"),
        ({"CURSOR_TRACE_ID": "abc123"}, "cursor"),
    ],
)
def test_each_known_agent_host_marker_classifies(env, expected):
    assert detect(env, stdout_is_tty=True).host == expected


def test_no_agent_marker_means_no_host_dimension():
    assert detect({}, stdout_is_tty=True).host is None


def test_a_disabled_marker_does_not_classify():
    # CLAUDECODE=0 is "explicitly not Claude Code", not a detection.
    assert detect({"CLAUDECODE": "0"}, stdout_is_tty=True).host is None


# --- terminals: TERM_PROGRAM values and marker-variable fallbacks ---


@pytest.mark.parametrize(
    ("program", "expected"),
    [
        ("iTerm.app", "iterm"),
        ("Apple_Terminal", "apple-terminal"),
        ("vscode", "vscode"),
        ("WarpTerminal", "warp"),
        ("WezTerm", "wezterm"),
        ("ghostty", "ghostty"),
        ("Hyper", "hyper"),
        ("tmux", "tmux"),
    ],
)
def test_each_known_term_program_classifies(program, expected):
    assert detect({"TERM_PROGRAM": program}, stdout_is_tty=True).term == expected


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"ITERM_SESSION_ID": "w0t0p0"}, "iterm"),
        ({"WEZTERM_EXECUTABLE": "/usr/bin/wezterm"}, "wezterm"),
        ({"GHOSTTY_RESOURCES_DIR": "/opt/ghostty"}, "ghostty"),
        ({"KITTY_WINDOW_ID": "1"}, "kitty"),
        ({"ALACRITTY_WINDOW_ID": "1"}, "alacritty"),
        ({"WT_SESSION": "guid"}, "windows-terminal"),
        ({"KONSOLE_VERSION": "23.08"}, "konsole"),
        ({"GNOME_TERMINAL_SCREEN": "/org/gnome/x"}, "gnome-terminal"),
        ({"VTE_VERSION": "7400"}, "vte"),
    ],
)
def test_terminals_without_term_program_classify_via_their_marker(env, expected):
    assert detect(env, stdout_is_tty=True).term == expected


def test_tmux_masks_the_outer_terminal():
    env = {"TMUX": "/tmp/tmux-501/default,123,0", "TERM_PROGRAM": "iTerm.app"}
    assert detect(env, stdout_is_tty=True).term == "tmux"


@pytest.mark.parametrize(
    "env",
    [
        {"CI": "true"},
        {"CI": "1"},
        {"GITHUB_ACTIONS": "true"},
        {"GITLAB_CI": "true"},
        {"CIRCLECI": "true"},
        {"BUILDKITE": "true"},
        {"JENKINS_URL": "https://ci.example.com"},
        {"TEAMCITY_VERSION": "2025.1"},
    ],
)
def test_ci_environments_classify_as_ci(env):
    assert detect(env, stdout_is_tty=False).term == "ci"


def test_ci_wins_over_a_term_program_leaked_into_the_runner():
    env = {"CI": "true", "TERM_PROGRAM": "vscode"}
    assert detect(env, stdout_is_tty=False).term == "ci"


def test_ci_false_is_not_ci():
    assert detect({"CI": "false"}, stdout_is_tty=False).term == "non-tty"


# --- coarse buckets: unknown never errors, always classifies ---


def test_unknown_term_program_with_a_tty_degrades_to_terminal():
    # Arbitrary environment text must not become a token.
    surface = detect({"TERM_PROGRAM": "SomeFutureTerm 2.0"}, stdout_is_tty=True)
    assert surface.term == "terminal"


def test_empty_environment_with_a_tty_is_the_coarse_terminal_bucket():
    assert detect({}, stdout_is_tty=True) == Surface(host=None, term="terminal")


def test_empty_environment_without_a_tty_is_non_tty():
    assert detect({}, stdout_is_tty=False) == Surface(host=None, term="non-tty")


# --- the two dimensions are independent and both reported ---


def test_claude_code_inside_iterm_reports_both_dimensions():
    env = {"CLAUDECODE": "1", "TERM_PROGRAM": "iTerm.app"}
    surface = detect(env, stdout_is_tty=True)
    assert surface == Surface(host="claude-code", term="iterm")
    assert tokens(surface) == ["host/claude-code", "term/iterm"]


def test_tokens_omit_host_outside_any_agent():
    assert tokens(detect({}, stdout_is_tty=False)) == ["term/non-tty"]
