"""Poll-phase progress on stderr (#33), driven through the CLI seam.

The server sends a best-effort 0-1 ``progress`` field on every poll; the
CLI renders it to stderr only — one live-rewriting line on a tty, plain
milestone/coarse-step lines when piped, and nothing at all under
``--json``. stdout stays byte-identical in every mode.

Every line names its phase (#69): the phase verb ("parsing",
"extracting") stands in for the raw server status ("processing"), and
milestones are phase-qualified ("parse submitted", "extract completed")
— a fresh ``extract -d`` runs two jobs back-to-back, and bare status
words rendered both phases identically.
"""

import json

from extract_fixtures import SCHEMA, completed_extract_job
from parse_fixtures import JOB_ID, completed_job, job_payload

KEY = "sk-test-0123456789abcd"
AUTH_ENV = {"ADE_API_KEY": KEY}


def script_parse(cli, fractions, job_id=JOB_ID):
    """Submit + one processing poll per fraction + completion."""
    cli.transport.respond(202, {"job_id": job_id})
    for fraction in fractions:
        cli.transport.respond(
            200, job_payload("processing", job_id=job_id, progress=fraction)
        )
    cli.transport.respond(200, completed_job(job_id=job_id))


def document(tmp_path, name="doc.pdf", data=b"%PDF progress bytes"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_piped_stderr_gets_plain_lines_at_milestones_and_coarse_steps(cli, tmp_path):
    doc = document(tmp_path)
    script_parse(cli, [0.0, 0.04, 0.42, 0.48, 0.9])

    result = cli.invoke("parse", "-d", str(doc), env=AUTH_ENV)

    assert result.exit_code == 0
    # Milestones plus one line per 10%-decade of progress (4% opens the
    # 0-9 decade; 48% dedups into 42%'s), and progress 0.0 — the gateway's
    # nothing-to-report floor (e.g. a 1-page doc mid-parse) — reads as the
    # bare phase verb, never a fake "0%".
    assert [line.split(" · ")[0] for line in result.stderr.splitlines()] == [
        "parse submitted",
        "parsing",
        "parsing 4%",
        "parsing 42%",
        "parsing 90%",
        "parse completed",
    ]
    assert "\r" not in result.stderr  # no rewriting when piped
    assert "submitted" not in result.stdout  # progress never leaks to stdout


def test_tty_stderr_renders_one_live_rewriting_line(cli, tmp_path):
    cli.stderr_tty = True
    doc = document(tmp_path)
    script_parse(cli, [0.1, 0.4])

    result = cli.invoke("parse", "-d", str(doc), env=AUTH_ENV)

    assert result.exit_code == 0
    # One line, rewritten in place: every frame returns to column 0, and a
    # single newline terminates the line once the guarantee resolves.
    body, newline, tail = result.stderr.partition("\n")
    assert newline and tail == ""
    frames = [frame for frame in body.split("\r") if frame]
    assert frames[0].startswith("parse submitted")
    assert any(frame.startswith("parsing 40%") for frame in frames)
    assert frames[-1].startswith("parse completed")
    # Elapsed rides on the line, fed by the injected clock.
    assert " · 0s" in frames[0]


def test_tty_line_animates_dots_while_waiting_between_polls(cli, tmp_path):
    cli.stderr_tty = True
    doc = document(tmp_path)
    script_parse(cli, [0.0, 0.4])  # backoff sleeps: 1.0s then 1.5s

    result = cli.invoke("parse", "-d", str(doc), env=AUTH_ENV)

    assert result.exit_code == 0
    frames = [f for f in result.stderr.partition("\n")[0].split("\r") if f]
    # While waiting out a backoff the line keeps redrawing with cycling
    # dots — a static line at the 10s cap reads as hung.
    assert any(f.startswith("parsing. ·") for f in frames)
    assert any(f.startswith("parsing.. ·") for f in frames)
    assert any(f.startswith("parsing 40%. ·") for f in frames)  # pct animates too
    # A fresh observation restarts the cycle bare (no dots).
    assert any(f.startswith("parsing 40% ·") for f in frames)
    # Tick chunking never changes how long is actually slept...
    assert sum(cli.clock.sleeps) == 2.5
    # ...and the animation really ran through the clock: every backoff wait
    # was tick-sized chunks, never one opaque sleep. (Piped mode's
    # single-sleep pattern is pinned separately by
    # test_poll_backs_off_through_the_injected_clock.)
    assert all(s <= 0.5 for s in cli.clock.sleeps)


def test_stdout_is_byte_identical_between_piped_and_tty_modes(cli, tmp_path):
    doc = document(tmp_path)
    script_parse(cli, [0.5])
    piped = cli.invoke("parse", "-d", str(doc), env=AUTH_ENV)

    cli.stderr_tty = True
    script_parse(cli, [0.5])
    tty = cli.invoke("parse", "-d", str(doc), "--force", env=AUTH_ENV)

    assert piped.exit_code == tty.exit_code == 0
    assert piped.stdout == tty.stdout  # rendering mode never touches stdout
    assert piped.stderr != tty.stderr


def test_json_mode_is_fully_silent_on_stderr(cli, tmp_path):
    cli.stderr_tty = True  # even on a tty: --json decided silence
    doc = document(tmp_path)
    script_parse(cli, [0.3, 0.7])

    result = cli.invoke("parse", "-d", str(doc), "--json", env=AUTH_ENV)

    assert result.exit_code == 0
    assert result.stderr == ""
    json.loads(result.stdout)  # stdout is still the one stable object


def test_pending_exit_terminates_the_live_line_before_stdout(cli, tmp_path):
    cli.stderr_tty = True
    doc = document(tmp_path)
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, job_payload("processing", progress=0.2))

    result = cli.invoke("parse", "-d", str(doc), "--wait", "1", env=AUTH_ENV)

    assert result.exit_code == 3  # pending is a normal outcome
    assert result.stderr.endswith("\n")  # the live line was closed


def test_boolean_progress_falls_back_to_the_phase_verb(cli, tmp_path):
    # bool is an int in Python: a buggy gateway sending progress: true must
    # not render as 100% — non-numeric means the bare phase verb.
    doc = document(tmp_path)
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, job_payload("processing", progress=True))
    cli.transport.respond(200, completed_job())

    result = cli.invoke("parse", "-d", str(doc), env=AUTH_ENV)

    assert result.exit_code == 0
    assert "parsing" in result.stderr
    assert "100%" not in result.stderr


def test_extract_shares_the_progress_rendering(cli, tmp_path):
    doc = document(tmp_path)
    script_parse(cli, [])
    parsed = cli.invoke("parse", "-d", str(doc), "--json", env=AUTH_ENV)
    assert parsed.exit_code == 0
    parse_id = json.loads(parsed.stdout)["job_item_id"]

    cli.transport.respond(202, {"job_id": "extract-0001"})
    cli.transport.respond(
        200, job_payload("processing", job_id="extract-0001", progress=0.4)
    )
    cli.transport.respond(200, completed_extract_job())
    result = cli.invoke(
        "extract", parse_id, "--schema", json.dumps(SCHEMA), env=AUTH_ENV
    )

    assert result.exit_code == 0
    # The shared poll loop serves extract identically — under its own verb.
    assert "extracting 40% · " in result.stderr
    assert "extract completed · " in result.stderr


def test_extract_d_parse_first_names_each_phase(cli, tmp_path):
    # The issue #69 shape: `extract -d` on a never-parsed document runs two
    # jobs back-to-back (a standalone parse job, then the extract). Bare
    # status words rendered both as identical processing/completed lines;
    # every line now names its phase.
    doc = document(tmp_path)
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, job_payload("processing", progress=0.5))
    cli.transport.respond(200, completed_job())
    cli.transport.respond(202, {"job_id": "extract-0001"})
    cli.transport.respond(
        200, job_payload("processing", job_id="extract-0001", progress=0.5)
    )
    cli.transport.respond(200, completed_extract_job(job_id="extract-0001"))

    result = cli.invoke(
        "extract", "-d", str(doc), "--schema", json.dumps(SCHEMA), env=AUTH_ENV
    )

    assert result.exit_code == 0
    progress_lines = [
        line.split(" · ")[0] for line in result.stderr.splitlines() if " · " in line
    ]
    assert progress_lines == [
        "parse submitted",
        "parsing 50%",
        "parse completed",
        "extract submitted",
        "extracting 50%",
        "extract completed",
    ]


def test_pending_status_is_phase_qualified(cli, tmp_path):
    # "pending" keeps its own word — the job is queued, not being worked —
    # but says which phase's queue it sits in.
    doc = document(tmp_path)
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, job_payload("pending"))
    cli.transport.respond(200, completed_job())

    result = cli.invoke("parse", "-d", str(doc), env=AUTH_ENV)

    assert result.exit_code == 0
    assert "parse pending · " in result.stderr
