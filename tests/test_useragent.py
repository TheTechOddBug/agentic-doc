"""Client identity (issues #48, #51): every ADE API request self-identifies
as ade-cli via a structured User-Agent — including which CLI command
triggered it (``command/<name>``) — so the platform can tell CLI traffic
from raw API calls and query per-command usage from request logs alone.
Format documented in docs/user-agent.md."""

import json
import platform
import sys
from importlib.metadata import version as installed_version

import httpx
import pytest

from ade_cli.gateway import Gateway, StaticBearer
from ade_cli.useragent import user_agent

from extract_fixtures import SCHEMA, completed_extract_job
from parse_fixtures import JOB_ID, completed_job

KEY = "sk-test-0123456789abcd"
AUTH_ENV = {"ADE_API_KEY": KEY}
DOC_BYTES = b"%PDF-1.4 fake invoice bytes"

# httpx's token comes from the module attribute, never importlib.metadata:
# the frozen app bundles no dependency dist-info (issue #97).
BASE = (
    f"ade-cli/{installed_version('ade-cli')}"
    f" ({platform.system()} {platform.machine()})"
    f" python/{sys.version_info.major}.{sys.version_info.minor}"
    f" httpx/{httpx.__version__}"
)
# The harness shields ambient surface markers and captured streams are
# never ttys, so wire headers carry the coarse term/non-tty bucket (#50).
PARSE = f"{BASE} command/parse term/non-tty"
EXTRACT = f"{BASE} command/extract term/non-tty"


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "invoice.pdf"
    path.write_bytes(DOC_BYTES)
    return path


@pytest.fixture
def schema_file(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(json.dumps(SCHEMA))
    return path


def test_identity_survives_missing_package_metadata(monkeypatch):
    # Issue #97: the 0.1.3 frozen binary crashed every API request because
    # importlib.metadata found no dist-info for a dependency. Identity must
    # degrade to a placeholder, never raise.
    from importlib.metadata import PackageNotFoundError

    from ade_cli import useragent

    def missing(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(useragent, "_installed_version", missing)
    useragent._base.cache_clear()
    try:
        assert user_agent(("command", "parse")) == (
            f"ade-cli/unknown ({platform.system()} {platform.machine()})"
            f" python/{sys.version_info.major}.{sys.version_info.minor}"
            f" httpx/{httpx.__version__} command/parse"
        )
    finally:
        useragent._base.cache_clear()


def test_builder_appends_further_key_value_tokens():
    # The append-only extension seam (host-app and any later tokens ride
    # after the command token the same way).
    assert user_agent(("host-app", "vscode"), ("command", "parse")) == (
        f"{BASE} host-app/vscode command/parse"
    )


def test_requests_carry_the_agent_host_and_terminal_tokens(cli, document):
    # #50: an agent host and terminal, both detected, both on the wire.
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())

    result = cli.invoke(
        "parse",
        "-d",
        str(document),
        env={**AUTH_ENV, "CLAUDECODE": "1", "TERM_PROGRAM": "iTerm.app"},
    )

    assert result.exit_code == 0
    expected = f"{BASE} command/parse host/claude-code term/iterm"
    assert [r.headers["user-agent"] for r in cli.transport.requests] == [
        expected, expected
    ]


def test_parse_submit_and_poll_carry_the_parse_command_token(cli, document):
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())

    result = cli.invoke("parse", "-d", str(document), env=AUTH_ENV)

    assert result.exit_code == 0
    submit, poll = cli.transport.requests
    assert submit.headers["user-agent"] == PARSE
    assert poll.headers["user-agent"] == PARSE


def test_extract_submit_and_poll_carry_the_extract_command_token(
    cli, document, schema_file
):
    # Seed a completed parse item, then extract from it — four wire calls,
    # each naming the command the user actually ran.
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())
    result = cli.invoke("parse", "-d", str(document), "--json", env=AUTH_ENV)
    assert result.exit_code == 0
    parse_id = json.loads(result.stdout)["job_item_id"]

    cli.transport.respond(202, {"job_id": "extract-0001"})
    cli.transport.respond(200, completed_extract_job(job_id="extract-0001"))
    result = cli.invoke(
        "extract", parse_id, "--schema", str(schema_file), env=AUTH_ENV
    )

    assert result.exit_code == 0
    assert [r.headers["user-agent"] for r in cli.transport.requests] == [
        PARSE, PARSE, EXTRACT, EXTRACT
    ]
    submit, poll = cli.transport.requests[2:]
    assert submit.method == "POST" and submit.url.path == "/v2/extract/jobs"
    assert poll.method == "GET"


def test_extracts_standalone_parse_carries_the_extract_command_token(
    cli, document, schema_file
):
    # `extract -d` with no reusable parse runs a standalone parse job first.
    # The token names the *invoking* command, not the underlying verb: all
    # four requests of this one invocation say command/extract.
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())
    cli.transport.respond(202, {"job_id": "extract-0001"})
    cli.transport.respond(200, completed_extract_job(job_id="extract-0001"))

    result = cli.invoke(
        "extract", "-d", str(document), "--schema", str(schema_file), env=AUTH_ENV
    )

    assert result.exit_code == 0
    parse_submit = cli.transport.requests[0]
    assert parse_submit.method == "POST" and parse_submit.url.path == "/v2/parse/jobs"
    assert [r.headers["user-agent"] for r in cli.transport.requests] == [
        EXTRACT, EXTRACT, EXTRACT, EXTRACT
    ]


def test_every_request_declares_the_cli_source(cli, document, schema_file):
    # #49: X-Source names the inference_history `source` the platform records
    # the request under — `cli`, on every wire call, parse and extract alike.
    cli.transport.respond(202, {"job_id": JOB_ID})
    cli.transport.respond(200, completed_job())
    result = cli.invoke("parse", "-d", str(document), "--json", env=AUTH_ENV)
    assert result.exit_code == 0
    parse_id = json.loads(result.stdout)["job_item_id"]

    cli.transport.respond(202, {"job_id": "extract-0001"})
    cli.transport.respond(200, completed_extract_job(job_id="extract-0001"))
    result = cli.invoke(
        "extract", parse_id, "--schema", str(schema_file), env=AUTH_ENV
    )

    assert result.exit_code == 0
    assert [r.headers["x-source"] for r in cli.transport.requests] == ["cli"] * 4


def test_gateway_cannot_be_built_without_a_command():
    # The structural guarantee (issue #51): a new API-bound command gets its
    # token by construction — omitting it is a TypeError at the only place
    # requests can come from, not a silently untagged request.
    with pytest.raises(TypeError):
        Gateway(  # ty: ignore[missing-argument]
            endpoint="https://api.example.test",
            auth=StaticBearer(KEY),
            transport=httpx.MockTransport(lambda request: httpx.Response(200)),
        )
