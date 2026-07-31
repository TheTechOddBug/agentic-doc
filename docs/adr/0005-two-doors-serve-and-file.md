# Viewer artifacts have two doors: file:// (default) and a served loopback origin (`view --serve`)

## Context

Browser zoom over `file://` is keyed per URL — in Chrome, per full URL
*including the fragment* (verified against `Preferences` →
`per_host_zoom_levels`). Consequences that shaped the viewer
([#61](https://github.com/landing-ai/ade-cli/issues/61),
[#108](https://github.com/landing-ai/ade-cli/pull/108)):

- No zoom of any kind survives a sidebar hop on its own — every viewer
  is its own document with its own zoom key.
- The template grew a CSS-zoom approximation: ⌘/Ctrl +/-/0 intercepted
  into `zoom:` on `<body>` riding the hash (`#z=`); menu zoom carried as
  a `dpr=` baseline in row hrefs; a post-load settle window absorbing
  Chrome's asynchronous re-application of stale per-URL zoom levels.
- The approximation is inherently leaky: the browser's zoom indicator
  reads 100% on a page visually at 125%, and a menu zoom stacked on a
  carried CSS zoom multiplies.

Over an `http://127.0.0.1` origin none of this exists: zoom is
per-origin, so one native zoom covers every sibling viewer, survives
hops, reloads and restarts, and the indicator stays truthful.

## Decision

Serve the **same artifacts** through two doors, choosing neither as the
only one:

- **file:// stays the default and the artifact contract.** `view.html`
  is self-contained, double-clickable and shareable with no process
  running; the CSS-zoom approximation applies there and only there
  (the template gates it on `location.protocol === "file:"`).
- **`view --serve` opens the loopback door.** A detached static file
  server (`serve.py`) rooted at `$ADE_HOME`, spawned like the sidebar's
  background builder, reused when already up (`/__ade__/health` names
  the store root so a server for another store is never mistaken for
  ours). Serve failures degrade to the file:// door with a note — the
  artifact on disk is always complete.
- **The port sticks.** Chrome keys per-origin state (zoom,
  localStorage) by scheme+host+port; the daemon records its port in
  `server.json` at the store root and later runs reuse it. A wandering
  port would silently reset every tester's zoom. The record survives
  shutdown for the same reason.
- **The daemon retires itself.** Any open viewer polls history.js every
  3 seconds, so "no requests for 30 minutes" means nobody is watching:
  the idle watchdog then ends the process — no orphaned servers to
  explain to testers. `view --stop-server` stops it immediately: the
  loopback shutdown endpoint first, falling back to SIGTERM on the
  recorded pid only when the endpoint isn't honored (a daemon from an
  older build surviving an upgrade) — and only after the health probe
  has just proven that pid belongs to our live daemon for this store,
  so a stale or recycled pid is never signaled.
- **Loopback only, allowlist only.** The server never binds beyond
  127.0.0.1 — but loopback is reachable by every local process, so it
  also serves nothing but what the viewer needs: `jobs/**` and
  `history.js`. Store-root secrets (`credentials.json`, `config.json`,
  telemetry) 404 even by exact path, request paths are dot-collapsed
  before the allowlist check, and directory listings are refused.

## Consequences

- Everything relative in the artifacts (history.js, `pages-N.js`
  chunks) resolves identically through both doors — no second build,
  no serve-flavored HTML.
- Served pages never stamp `z=`/`dpr=` and never intercept zoom keys;
  arriving there with a file://-minted `#z=`/`#dpr=` strips it and lets
  the origin zoom stand.
- The zoom-carry machinery (hash `z=`, `dpr=` baseline, settle window)
  is file://-only compatibility code; if the served door ever becomes
  the default, it shrinks to the shared-file story.
- A `server.json` with a dead pid is harmless: health probing decides
  liveness, never the pid.
