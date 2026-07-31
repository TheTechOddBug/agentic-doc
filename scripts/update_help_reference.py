#!/usr/bin/env python
"""Regenerate docs/reference/help.json — the committed snapshot of the
agent-facing command surface.

`help` is generated from the live command tree, so the CLI itself can
never drift; this snapshot exists so that every surface change (a
command or flag added, removed, or re-described; an exit state; the
store layout) also shows up as a reviewable diff in the PR that made it
— and reminds the author to check SKILL.md's narrative against it.
test_help.py fails when the snapshot is stale; this script is the fix:

    uv run python scripts/update_help_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from ade_cli.main import app

REFERENCE_PATH = Path(__file__).parents[1] / "docs" / "reference" / "help.json"


def live_reference() -> dict:
    result = CliRunner().invoke(app, ["help", "--json"])
    assert result.exit_code == 0, result.output
    reference = json.loads(result.stdout)
    # The release version churns on every bump; the surface is the contract.
    reference.pop("version", None)
    return reference


if __name__ == "__main__":
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(json.dumps(live_reference(), indent=2) + "\n")
    print(f"wrote {REFERENCE_PATH}")
