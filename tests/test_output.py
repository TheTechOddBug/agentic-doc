"""The output convention: ~-abbreviation for store paths (#34, #36) and
the ``--id-only`` piping mode (F6)."""

import json
from pathlib import Path

import pytest

from ade_cli.output import tilde

from parse_fixtures import completed_job, rich_parse_response

KEY = "sk-test-0123456789abcd"
AUTH_ENV = {"ADE_API_KEY": KEY}


def test_tilde_abbreviates_only_the_home_prefix():
    home = Path.home()
    assert tilde(home / "x" / "y.pdf") == "~/x/y.pdf"
    assert tilde(home) == "~"
    assert tilde("/etc/hosts") == "/etc/hosts"
    # A sibling dir sharing the prefix string is not home.
    assert tilde(str(home) + "backup/f") == str(home) + "backup/f"


def test_tilde_passes_urls_through_verbatim():
    # history list feeds recorded sources through tilde, and sources can be
    # URLs; Path() would collapse the "//", so they must round-trip as the
    # exact string.
    url = "https://example.com/statements/q2.pdf"
    assert tilde(url) == url


# --- --id-only: ids flow between verbs without jq (F6) ---------------------


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"%PDF-1.4 fake invoice bytes")
    return path


def parse_with(cli, document, *args):
    cli.transport.respond(202, {"job_id": "job-0001"})
    cli.transport.respond(200, completed_job(rich_parse_response()))
    return cli.invoke("parse", "-d", str(document), *args, env=AUTH_ENV)


def test_parse_id_only_prints_exactly_the_job_item_id(cli, document):
    """JOB=$(ade parse -d f.pdf --id-only) — one token, nothing to strip."""
    result = parse_with(cli, document, "--id-only")

    assert result.exit_code == 0, result.output
    captured = result.stdout.strip()
    assert "\n" not in captured
    assert (cli.home / "jobs" / captured).is_dir()


def test_id_only_output_is_the_id_the_json_payload_carries(cli, document):
    """The two modes are spellings of one result, not two answers."""
    piped = parse_with(cli, document, "--id-only").stdout.strip()
    # A second run of the same invocation is the free cached path — same id.
    payload = json.loads(cli.invoke(
        "parse", "-d", str(document), "--json", env=AUTH_ENV
    ).stdout)

    assert piped == payload["job_item_id"]


def test_find_id_only_prints_element_ids_one_per_line(cli, document):
    """The bridge crop's filters made unnecessary — still the right answer
    for anything else that takes element ids."""
    job = parse_with(cli, document, "--id-only").stdout.strip()

    result = cli.invoke("find", job, "--type", "table_cell", "--id-only")

    assert result.exit_code == 0, result.output
    assert result.stdout.split() == [
        "table_cell-0", "table_cell-1", "table_cell-2", "table_cell-3",
    ]


def test_id_only_keeps_errors_off_stdout(cli):
    """A captured id must never turn out to be a sentence: the remediation
    goes to stderr and stdout stays empty."""
    result = cli.invoke("find", "nosuchjob", "--id-only")

    assert result.exit_code != 0
    assert result.stdout.strip() == ""
    assert "nosuchjob" in result.stderr


def test_id_only_wins_over_json(cli, document):
    """One output mode at a time; --id-only is the narrower request."""
    result = parse_with(cli, document, "--id-only", "--json")

    captured = result.stdout.strip()
    assert "{" not in captured  # the payload did not come along
    assert (cli.home / "jobs" / captured).is_dir()


def test_id_only_does_not_leak_into_the_next_in_process_run(cli, document):
    """The mode is per invocation — a host embedding the CLI must not see
    the second command inherit the first one's output mode."""
    parse_with(cli, document, "--id-only")

    payload = json.loads(cli.invoke("history", "list", "--json").stdout)

    assert isinstance(payload, list) and payload
