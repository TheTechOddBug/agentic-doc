# `login` selects, `logout` de-auths — both per environment

> **Partially superseded by [ADR-0003](0003-per-invocation-environment.md):**
> the *selection* half (sticky active environment, `login` as the switch,
> flagless-targets-production-not-the-sticky-env) is gone — the target is
> resolved per invocation. The per-environment credential storage and
> per-environment `logout` decided here survive.

## Context

Credentials are already stored per environment in `credentials.json`, but
`config.json` keeps a single **sticky active environment** that every
non-`login` command reads. Flagless `auth login` re-targeted that sticky
env, so `login --env eu --api-key X` followed by a bare
`login --api-key Y` silently overwrote the eu key instead of touching
production ([#72](https://github.com/landing-ai/ade-cli/issues/72)).

## Decision

Environments coexist; **selection** and **credential presence** are
orthogonal concerns.

- **`login` is the only command that changes the active environment**, and
  it always selects what it logged into.
- **Flagless `login` targets production** (the stable default), never the
  sticky current env. It un-pins back to production, displacing a
  configured raw `--endpoint`.
- **The credential flag decides what `login` does.** With `--api-key`/browser
  it *authenticates* (writes the credential, then selects). Without one it
  *ensures*: reuse the target env's stored credential if present (a pure
  switch, no browser/prompt), else acquire via browser OAuth, then select.
  This makes `login` a guarantee command — "ensure logged in on X" —
  consistent with `parse`/`extract`.
- **`logout` is per environment and never changes selection.** Flagless
  `logout` de-auths the active env (revoking only its refresh token);
  `logout --env X` targets X; `logout --all` clears everything.
- **Force re-auth** of an already-authed env is `logout --env X` then
  `login --env X`.
- **`status`** reports the active env plus the other authenticated
  environments, so switching is discoverable.

## Considered alternatives

- **A dedicated `auth use <env>` switch command**, keeping `login` always
  re-authenticate. Rejected: `login --env X` reusing a stored credential is
  more intuitive and adds no verb.
- **Keep flagless `logout` clearing all environments** (prior behavior).
  Rejected once environments coexist — dropping every session on a bare
  `logout` is too blunt; retained as `logout --all`.

## Consequences

- Unauthenticated remediation messages must name `--env <active>` when the
  active env isn't production, since a bare `login` now switches to
  production rather than re-authing the current env.
- Multiple credentials **per** environment keyed by account name (issue #72's
  "account name") are explicitly deferred to a later change; the model here
  stays one credential per environment.
