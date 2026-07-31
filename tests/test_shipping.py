"""Shipping the usage ledger (#53): opportunistic, bounded, offline-safe,
silent. The harness keeps uploads off (conftest shields
ADE_TELEMETRY_UPLOAD=0); each test here opts back in per call."""

import json

import httpx
import pytest

from ade_cli.shipping import (
    MAX_BATCH_RECORDS,
    MAX_LEDGER_BYTES,
    UPLOAD_PATH,
)
from ade_cli.telemetry import LEDGER_NAME

UPLOAD_ON = {"ADE_TELEMETRY_UPLOAD": None}
KEYED = {**UPLOAD_ON, "ADE_API_KEY": "k-test"}


def events(cli) -> list[dict]:
    path = cli.home / LEDGER_NAME
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def telemetry_posts(cli) -> list[httpx.Request]:
    return [r for r in cli.transport.requests if r.url.path == UPLOAD_PATH]


def seed(cli, n: int = 1) -> None:
    """Buffer n events without shipping (upload stays shielded off)."""
    for _ in range(n):
        cli.invoke("version")


# --- successful flush ---


def test_a_flush_ships_the_whole_unshipped_backlog_including_this_event(cli):
    seed(cli, 2)
    cli.transport.respond(200, {"accepted": 3})

    result = cli.invoke("version", env=KEYED)

    assert result.exit_code == 0
    (post,) = telemetry_posts(cli)
    assert post.url == "https://api.ade.landing.ai/v2/telemetry"
    body = json.loads(post.content)
    assert [r["properties"]["command"] for r in body] == ["version"] * 3
    assert all(events(cli)[i]["shipped"] for i in range(3))


def test_the_wire_record_carries_the_key_epoch_seconds_and_properties(cli):
    cli.transport.respond(200, {"accepted": 1})

    cli.invoke("version", env=KEYED)

    (post,) = telemetry_posts(cli)
    (record,) = json.loads(post.content)
    (event,) = events(cli)
    assert record["idempotent_key"] == event["idempotent_key"]
    assert record["ts"] == int(event["ts"])  # epoch seconds, original time
    assert record["properties"] == {
        key: event[key]
        for key in (
            "command",
            "flags",
            "outcome",
            "exit_code",
            "duration_ms",
            "host",
            "term",
            "env",
            "version",
        )
    }
    # The local shipped mark stays home.
    assert "shipped" not in record["properties"]


def test_the_flush_request_carries_identity_and_the_bearer(cli):
    cli.transport.respond(200, {"accepted": 1})

    cli.invoke("version", env=KEYED)

    (post,) = telemetry_posts(cli)
    assert post.headers["Authorization"] == "Bearer k-test"
    assert post.headers["X-Source"] == "cli"
    assert post.headers["User-Agent"].startswith("ade-cli/")
    assert "command/version" in post.headers["User-Agent"]


def test_shipped_rows_never_re_send(cli):
    cli.transport.respond(200, {"accepted": 1})
    cli.invoke("version", env=KEYED)
    cli.transport.respond(200, {"accepted": 1})

    cli.invoke("version", env=KEYED)

    first, second = telemetry_posts(cli)
    assert len(json.loads(first.content)) == 1
    (record,) = json.loads(second.content)
    assert record["properties"]["command"] == "version"
    assert record["idempotent_key"] != json.loads(first.content)[0]["idempotent_key"]


def test_a_stored_credential_ships_without_the_env_key(cli):
    cli.transport.respond(200, {"accepted": 0})  # login's verification probe
    cli.invoke("auth", "login", "--api-key", "k-stored")
    cli.transport.requests.clear()  # the flush below is the traffic under test
    cli.transport.respond(200, {"accepted": 2})

    cli.invoke("version", env=UPLOAD_ON)

    (post,) = telemetry_posts(cli)
    assert post.headers["Authorization"] == "Bearer k-stored"
    # Both the login's event and this one shipped.
    assert len(json.loads(post.content)) == 2


# --- partitioning by environment ---


def test_partitions_ship_to_their_own_environment_with_its_own_credential(cli):
    cli.transport.respond(200, {"accepted": 0})  # login verification probes
    cli.invoke("auth", "login", "--api-key", "k-prod")
    cli.transport.respond(200, {"accepted": 0})
    cli.invoke("auth", "login", "--api-key", "k-dev", "--env", "dev")
    cli.transport.requests.clear()  # the flushes below are the traffic under test
    cli.transport.respond(200, {"accepted": 1})
    cli.transport.respond(200, {"accepted": 2})

    result = cli.invoke("version", env={**UPLOAD_ON, "ADE_ENV": "dev"})

    assert result.exit_code == 0
    prod, dev = telemetry_posts(cli)
    assert prod.url.host == "api.ade.landing.ai"
    assert prod.headers["Authorization"] == "Bearer k-prod"
    # The production partition: the first login's own event.
    (prod_record,) = json.loads(prod.content)
    assert prod_record["properties"]["env"] == "production"
    assert dev.url.host == "api.ade.dev.landing.ai"
    assert dev.headers["Authorization"] == "Bearer k-dev"
    # The dev partition: the dev login's event plus this invocation's.
    dev_records = json.loads(dev.content)
    assert [r["properties"]["env"] for r in dev_records] == ["dev", "dev"]
    assert dev_records[-1]["properties"]["command"] == "version"


def test_a_partition_without_a_credential_stays_buffered(cli):
    cli.invoke("version", env={"ADE_ENV": "dev"})  # buffered, no dev credential
    cli.transport.respond(200, {"accepted": 2})

    cli.invoke("version", env=KEYED)  # production ships; dev cannot

    (post,) = telemetry_posts(cli)  # exactly one POST: production's
    assert {r["properties"]["env"] for r in json.loads(post.content)} == {"production"}
    dev_event, *_ = events(cli)
    assert dev_event["env"] == "dev" and "shipped" not in dev_event


def test_the_env_api_key_never_crosses_to_another_environments_partition(cli):
    cli.invoke("version", env={"ADE_ENV": "dev"})  # buffered dev event

    cli.invoke("version", env=KEYED)  # invocation namespace: production

    # ADE_API_KEY authenticated the production partition only — the dev
    # partition made no request rather than borrowing the key.
    (post,) = telemetry_posts(cli)
    assert post.url.host == "api.ade.landing.ai"


def test_custom_endpoint_events_ship_while_the_override_addresses_them(cli):
    custom = {"ADE_ENDPOINT": "https://ade.example.test"}
    cli.invoke("version", env=custom)  # recorded env: custom
    cli.transport.respond(200, {"accepted": 2})

    cli.invoke("version", env={**KEYED, **custom})

    (post,) = telemetry_posts(cli)
    assert post.url == "https://ade.example.test/v2/telemetry"
    assert {r["properties"]["env"] for r in json.loads(post.content)} == {"custom"}


def test_custom_events_wait_when_no_override_is_live(cli):
    cli.invoke("version", env={"ADE_ENDPOINT": "https://ade.example.test"})
    cli.transport.respond(200, {"accepted": 1})

    cli.invoke("version", env=KEYED)

    (post,) = telemetry_posts(cli)  # production's own event only
    assert {r["properties"]["env"] for r in json.loads(post.content)} == {"production"}


# --- offline retention and silent failure ---


def test_offline_keeps_the_command_intact_and_the_events_buffered(cli):
    baseline = cli.invoke("version", env={"ADE_TELEMETRY": "0"})

    def offline(request):
        raise httpx.ConnectError("no network")

    cli.transport.respond_with(offline)
    result = cli.invoke("version", env=KEYED)

    assert result.exit_code == baseline.exit_code == 0
    assert result.stdout == baseline.stdout
    assert result.stderr == baseline.stderr
    (event,) = events(cli)
    assert "shipped" not in event


def test_a_transport_failure_abandons_the_remaining_partitions(cli):
    cli.transport.respond(200, {"accepted": 0})  # login verification probes
    cli.invoke("auth", "login", "--api-key", "k-prod")
    cli.transport.respond(200, {"accepted": 0})
    cli.invoke("auth", "login", "--api-key", "k-dev", "--env", "dev")
    cli.transport.requests.clear()  # the flush below is the traffic under test

    def offline(request):
        raise httpx.ConnectError("no network")

    cli.transport.respond_with(offline)
    result = cli.invoke("version", env=UPLOAD_ON)

    assert result.exit_code == 0
    assert len(telemetry_posts(cli)) == 1  # dev was never attempted


def test_a_server_error_is_silent_and_retains_the_events(cli):
    cli.transport.respond(500, {"error": "boom"})

    result = cli.invoke("version", env=KEYED)

    assert result.exit_code == 0
    (event,) = events(cli)
    assert "shipped" not in event


def test_a_retained_event_re_ships_later_under_the_same_key(cli):
    cli.transport.respond(500, {"error": "boom"})
    cli.invoke("version", env=KEYED)
    cli.transport.respond(200, {"accepted": 2})

    cli.invoke("version", env=KEYED)

    first, second = telemetry_posts(cli)
    retried = json.loads(second.content)
    assert json.loads(first.content)[0]["idempotent_key"] in {
        r["idempotent_key"] for r in retried
    }


def test_an_unauthorized_response_is_silent_and_retains_the_events(cli):
    cli.transport.respond(401, {"detail": "expired"})

    result = cli.invoke("version", env=KEYED)

    assert result.exit_code == 0
    (event,) = events(cli)
    assert "shipped" not in event


# --- opt-out ---


def test_full_opt_out_means_no_ledger_and_no_request(cli):
    cli.invoke("version", env={**KEYED, "ADE_TELEMETRY": "0"})

    assert events(cli) == []
    assert telemetry_posts(cli) == []


def test_do_not_track_means_no_request(cli):
    cli.invoke("version", env={**KEYED, "DO_NOT_TRACK": "1"})

    assert events(cli) == []
    assert telemetry_posts(cli) == []


def test_upload_opt_out_keeps_the_ledger_recording_locally(cli):
    cli.invoke("version", env={"ADE_API_KEY": "k-test"})  # shield keeps upload off

    (event,) = events(cli)
    assert event["command"] == "version"
    assert telemetry_posts(cli) == []


def test_no_credential_anywhere_means_no_request(cli):
    cli.invoke("version", env=UPLOAD_ON)

    assert telemetry_posts(cli) == []
    (event,) = events(cli)
    assert "shipped" not in event


# --- legacy and corrupt rows ---


def test_a_pre_key_row_ships_under_a_deterministic_content_hash(cli):
    legacy = json.dumps(
        {
            "command": "parse",
            "duration_ms": 5,
            "env": "production",
            "exit_code": 0,
            "flags": [],
            "host": None,
            "outcome": "success",
            "term": "non-tty",
            "ts": 1_784_774_107.5,
            "version": "0.1.9",
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cli.home.mkdir(parents=True)
    (cli.home / LEDGER_NAME).write_text(legacy + "\n")
    cli.transport.respond(500, {"error": "boom"})
    cli.invoke("version", env=KEYED)
    cli.transport.respond(200, {"accepted": 3})

    cli.invoke("version", env=KEYED)

    first, second = telemetry_posts(cli)
    key = json.loads(first.content)[0]["idempotent_key"]
    assert len(key) == 32
    # The same row re-ships under the same derived key.
    assert key in {r["idempotent_key"] for r in json.loads(second.content)}


def test_a_corrupt_line_neither_ships_nor_breaks_the_flush(cli):
    cli.home.mkdir(parents=True)
    (cli.home / LEDGER_NAME).write_text("{not json\n")
    cli.transport.respond(200, {"accepted": 1})

    result = cli.invoke("version", env=KEYED)

    assert result.exit_code == 0
    (post,) = telemetry_posts(cli)
    (record,) = json.loads(post.content)
    assert record["properties"]["command"] == "version"
    # The corrupt line is preserved on disk, unshipped.
    assert (cli.home / LEDGER_NAME).read_text().splitlines()[0] == "{not json"


# --- bounds: batch cap and rotation ---


def test_a_flush_ships_at_most_the_batch_cap(cli, monkeypatch):
    monkeypatch.setattr("ade_cli.shipping.MAX_BATCH_RECORDS", 2)
    seed(cli, 3)
    cli.transport.respond(200, {"accepted": 2})

    cli.invoke("version", env=KEYED)

    (post,) = telemetry_posts(cli)
    assert len(json.loads(post.content)) == 2
    assert sum("shipped" not in e for e in events(cli)) == 2  # the rest wait


def test_rotation_drops_oldest_first_past_the_size_cap(cli, monkeypatch):
    monkeypatch.setattr("ade_cli.shipping.MAX_LEDGER_BYTES", 600)
    seed(cli, 4)

    remaining = events(cli)
    assert 0 < len(remaining) < 4  # oldest dropped, newest kept
    assert all(len(json.dumps(e)) < 600 for e in remaining)
    total = sum(len(line) + 1 for line in (cli.home / LEDGER_NAME).read_text().splitlines())
    assert total <= 600


def test_rotation_drops_records_past_the_age_cap(cli):
    stale = json.dumps(
        {"command": "parse", "ts": 1.0, "env": "production"},
        sort_keys=True,
        separators=(",", ":"),
    )
    cli.home.mkdir(parents=True)
    (cli.home / LEDGER_NAME).write_text(stale + "\n")

    cli.invoke("version")

    remaining = events(cli)
    assert [e["command"] for e in remaining] == ["version"]


def test_rotation_runs_even_with_uploads_opted_out(cli, monkeypatch):
    monkeypatch.setattr("ade_cli.shipping.MAX_LEDGER_BYTES", 600)
    for _ in range(4):
        cli.invoke("version")  # shield keeps uploads off throughout

    assert telemetry_posts(cli) == []
    assert len(events(cli)) < 4


# --- API-bound and store-served commands ship the same way ---


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(b"%PDF-1.4 fake invoice bytes")
    return path


@pytest.fixture
def schema_file(tmp_path):
    from extract_fixtures import SCHEMA

    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA))
    return path


def test_a_parse_ships_its_own_event_after_the_job_completes(cli, document):
    from parse_fixtures import JOB_ID, completed_job

    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())
    cli.transport.respond(200, {"accepted": 1})

    result = cli.invoke("parse", "-d", str(document), env=KEYED)

    assert result.exit_code == 0
    # The flush is the last request — after the command's own API calls,
    # which it must never disturb.
    (post,) = telemetry_posts(cli)
    assert cli.transport.requests[-1] is post
    assert len(cli.transport.requests) == 3  # submit, poll, flush
    (record,) = json.loads(post.content)
    assert record["properties"]["command"] == "parse"
    assert record["properties"]["flags"] == ["-d"]
    assert record["properties"]["outcome"] == "success"
    assert record["properties"]["duration_ms"] >= 0
    assert "command/parse" in post.headers["User-Agent"]


def test_an_extract_ships_one_event_for_the_whole_invocation(
    cli, document, schema_file
):
    from extract_fixtures import completed_extract_job
    from parse_fixtures import JOB_ID, completed_job

    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())
    cli.transport.respond(202, {"job_id": "extract-0001"})
    cli.transport.respond(200, completed_extract_job(None, job_id="extract-0001"))
    cli.transport.respond(200, {"accepted": 1})

    result = cli.invoke(
        "extract", "-d", str(document), "--schema", str(schema_file), env=KEYED
    )

    assert result.exit_code == 0
    (post,) = telemetry_posts(cli)
    assert cli.transport.requests[-1] is post
    # One invocation, one event — the parse run inside `extract -d` does
    # not mint its own.
    (record,) = json.loads(post.content)
    assert record["properties"]["command"] == "extract"
    assert sorted(record["properties"]["flags"]) == ["--schema", "-d"]
    assert record["properties"]["outcome"] == "success"


def test_a_store_served_view_ships_even_its_failure(cli):
    cli.transport.respond(200, {"accepted": 1})

    result = cli.invoke("view", "deadbeef", env=KEYED)

    assert result.exit_code == 1  # nothing in the store to view
    # view made no API call of its own; the flush is the only request.
    (post,) = telemetry_posts(cli)
    assert [post] == cli.transport.requests
    (record,) = json.loads(post.content)
    assert record["properties"]["command"] == "view"
    assert record["properties"]["outcome"] == "failure"
    assert "command/view" in post.headers["User-Agent"]


# --- byte preservation on rewrite ---


def test_the_mark_rewrite_keeps_unshipped_lines_byte_for_byte(cli):
    corrupt = '{"corrupt json"  \t '
    cli.home.mkdir(parents=True)
    (cli.home / LEDGER_NAME).write_text(corrupt + "\n")
    cli.transport.respond(200, {"accepted": 1})

    cli.invoke("version", env=KEYED)  # ships its event → mark rewrite runs

    lines = (cli.home / LEDGER_NAME).read_bytes().splitlines()
    # The corrupt line kept its exact bytes — trailing whitespace included;
    # only the shipped row was re-encoded.
    assert lines[0] == corrupt.encode()
    assert json.loads(lines[1])["shipped"] is True


# --- schema ---


def test_every_event_carries_a_fresh_idempotent_key(cli):
    seed(cli, 2)

    first, second = events(cli)
    assert first["idempotent_key"] and second["idempotent_key"]
    assert first["idempotent_key"] != second["idempotent_key"]


def test_the_module_caps_are_sane():
    # A regression guard on accidental cap edits: a batch fits well under
    # the rotation cap (events are ~250 bytes).
    assert MAX_BATCH_RECORDS * 250 <= MAX_LEDGER_BYTES * 2
    assert MAX_LEDGER_BYTES >= 64 * 1024


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
