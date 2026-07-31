---
name: verify
description: Verify ade changes end-to-end — seed a store offline, run the CLI, drive generated artifacts in a browser.
---

# Verifying ade

Build/run: `uv sync`, then `uv run ade …`. Tests are offline (fake
transport); verification means driving the real CLI against a real store.

## Seeding a parsed doc without the network

`parse` needs the API, so seed the store directly — write what `parse`
would have written (see `parse.py::write_artifacts` for the exact set):
`parse.json` (raw ParseResponse), `parse.md`, `elements.json`
(`{"job_id", "elements": elements.project(response)}`), `meta.json`
(`state: "parsed"`, `job_id` matching parse.json's `metadata.job_id` —
the generation gate in `refs.live_parse` rejects mismatches).

A ready-made seeder that also draws a matching invoice PNG (so boxes
visibly align) was used for the `view` verification — pattern: build
markdown piecewise so every element's `range` is exact, reuse
`tests/parse_fixtures.py` shapes.

Point the CLI at the seeded store with `ADE_HOME=<dir>`.

## Driving view.html

The in-app browser refuses `file://` — serve the doc dir instead:
`python3 -m http.server 8742 --bind 127.0.0.1` in
`$ADE_HOME/docs/<doc-id>/`, then browse `http://127.0.0.1:8742/view.html`.
Deep links: append `#element=<id>`. Selection state is inspectable via
JS: `document.querySelectorAll('.sel')` (both panes share `data-id`).
Rebuilds are fingerprint-gated — `--json` reports `built: true|false`;
touching the source or changing `--dpi` forces a rebuild.
