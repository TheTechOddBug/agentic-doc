# A terminal `login` asks which method; API key is the default

> **Amended by [ADR-0003](0003-per-invocation-environment.md):** "flagless
> targets production" became "flagless targets the resolved target
> (`--env` → `ADE_ENV` → production)", and a stored credential now reports
> "already authenticated" rather than switching. The menu itself is
> unchanged.

## Context

Flagless `auth login` went straight to the browser OAuth flow whenever the
target had no stored credential; the API key path required knowing about
`--api-key` up front. Launch may ship API-key-only (browser sign-in becomes
user-ready later), and either way a first-run user shouldn't need a flag to
pick the method they were given.

## Decision

When `login` must **acquire** a credential (no credential flag, no stored
credential for the target — the ensure/acquire split of ADR-0001 is
unchanged) and stderr is a terminal, it asks:

```
How would you like to log in? (↑/↓ and Enter)
> 1) Paste an API key (hidden input)
  2) Sign in with your browser (OAuth)
```

- **API key is option 1 and the default** — the launch-primary method, and
  the one every target supports from day one. The pointer starts there, so
  bare Enter continues without typing anything.
- **Arrow keys on a real terminal, typed digits as the fallback.** Raw keys
  come from `typer.getchar` (the vendored click getchar; Windows console
  arrow forms included); digits jump the pointer without confirming, so a
  "1⏎" habit can't leak its Enter into the hidden key prompt; Esc/Ctrl-C
  abort with nothing stored. When stdin isn't a tty, `TERM=dumb`, or raw
  mode fails mid-flight (the widget erases itself first), the same list
  renders numbered behind a typed `Method [1]:` prompt — which is also the
  path piped-stdin automation and the CliRunner test harness exercise.
- **The browser option appears only where it can work**: the target's
  provider has a `client_id`, and a raw-endpoint target (`--endpoint` /
  `ADE_ENDPOINT`) also has an explicit `resource` (the token audience).
  Otherwise the menu collapses to the key prompt with a one-line note. An
  API-key-only rollout is therefore just "ship no client_id" — no flag, no
  new config. The chosen flow re-checks configuration authoritatively; the
  menu gate is UX only.
- **Neither branch asks about the target.** Flagless means production on
  the key path exactly as on the browser path — one stable-default rule
  (ADR-0001), with `--env`/`--endpoint` the only way to name another
  target. The environment prompt the pre-menu `--api-key -` flow carried
  was removed with the menu's arrival: it compensated for there being no
  interactive front door, and keeping it would have made the two
  interactive key entries (menu and `--api-key -`) disagree.
- **Non-interactive runs are unchanged**: no terminal ⇒ no prompt ⇒ the
  browser flow directly, whose headless failure already names `--api-key`.
  Flags (`--api-key`) skip the menu entirely, and a stored credential still
  short-circuits to a pure switch before any prompt.

## Considered alternatives

- **Keep browser-by-default and rely on `--api-key`.** Rejected: at an
  API-key-first launch the default path would dead-end for everyone, and
  discovering `--api-key` from an error is a worse first run than a menu.
- **A `--method oauth|api-key` flag instead of a prompt.** Rejected as the
  primary UX: the flag spelling already exists (`--api-key` vs flagless),
  so the flag would only rename it; a menu serves the user who doesn't
  know the options yet. Nothing precludes adding it later.
- **Gating the menu behind a config switch (launch = API key only).**
  Rejected: provider settings are data, not code — client_id presence
  already says whether browser login can work, so a second switch could
  only contradict it.

## Consequences

- Scripts that pipe stdin to a flagless `login` on a real terminal now hit
  the menu; non-TTY automation is unaffected. Explicit method selection for
  automation stays `--api-key` (API key) or nothing (browser).
- Pulling a baked client_id (or shipping without one) now degrades the
  terminal flow to API-key-only silently by design; the loud
  `oauth_not_configured` remediation still guards the non-interactive path.
- The old docstring claim "browser OAuth by default" survives only for
  non-interactive runs; docs and help text say "asks on a terminal".
