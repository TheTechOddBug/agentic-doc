# The target environment is resolved per invocation, never stored

Supersedes the *selection* half of [ADR-0001](0001-auth-login-selects-logout-per-env.md)
(its per-environment credential storage and per-environment `logout`
survive unchanged), and ADR-0002's "flagless login selects production"
consequence (the menu itself is unchanged).

## Context

The sticky active environment — `config.json`'s `environment`/`endpoint`,
selected by `login` — was global mutable state deciding where every
command went ([#87](https://github.com/landing-ai/ade-cli/issues/87)):

- Shared across terminals: a switch in one shell silently redirected
  parses in another; two terminals could not work two environments.
- "Where will this parse go?" was unanswerable from the command line
  being typed.
- It spawned a complexity family: issue #72 (bare login overwrote the
  eu key), ADR-0001's "flagless never means the sticky env" rule,
  the since-removed environment prompt, issue #86 (raw-endpoint switch
  semantics — dissolved by this ADR).
- `login --env X` meaning "switch — unless it means authenticate" needed
  an ADR to explain.

## Decision

**No stored selection. One resolution rule on every command:**
`--env` flag → `ADE_ENV` variable → `production`.

- `parse` and `extract` (the network verbs) take `--env`. `ADE_ENV`
  replaces stickiness with *shell-scoped* stickiness (the `AWS_PROFILE`
  pattern): `export ADE_ENV=eu` affects that terminal alone.
  `ADE_ENDPOINT` stays the ambient raw-URL escape hatch (endpoint only —
  credentials still file under the resolved environment); `login
  --endpoint` is gone with the stored endpoint.
- `login` sheds selection: flagless ensures the resolved target (so a
  shell exporting `ADE_ENV=eu` logs into eu — login and the
  verbs can never disagree), a stored credential is "already
  authenticated, nothing to do", and the ADR-0002 method menu is
  untouched. `status` reports the resolved target plus every other
  authenticated environment; flagless `logout` de-auths the resolved
  target.
- `config.json` slims to the `oauth.<environment>` provider block.
  Leftover pre-ADR-0003 `environment`/`endpoint` keys are ignored, not
  errors — there is nothing they could ambiguate against anymore.

**The environment joins job-item identity** —
`sha256(verb:environment:source[:content]:params)[:16]` — and is
recorded in `meta.json`. Same document, same params, two environments ⇒
two sibling items: one environment's result never serves another's
request (server-side job ids are per-environment, and so are the
documents' actual parses). Pre-release, existing stores simply re-key;
no migration.

**Extract over a parse item inherits the item's environment.** Forced by
the API shape: the extract references the parse job's server-side id,
which exists only in the environment that ran it. The item pins the
target — overriding ambient `ADE_ENV` — and an explicitly conflicting
`--env` is a loud `environment_mismatch` usage error naming both sides.
The ensure-parse path (`extract -d … --env X`) applies X to both jobs,
and the parse-reuse scan (`latest_parse`) filters by environment.

## Considered alternatives

- **Keep the sticky env, add per-command `--env` as an override** (the
  `kubectl --context` shape). Rejected: keeps the shared-file footgun and
  both mental models; `ADE_ENV` provides the ergonomics without the
  global state.
- **`--env` on every command including the local verbs.** Rejected:
  `find`/`view`/`crop`/`history` operate on the local store, where the
  stored item already names its environment; a flag would imply a filter
  that doesn't exist (record-level display can come later if wanted).
- **Environment outside item identity, checked at read time.** Rejected:
  the cache-hit path ("already parsed") would need env-aware guards in
  every reader; identity is where "same invocation" is defined, and which
  environment ran the job is part of the invocation.

## Consequences

- Two terminals can work two environments simultaneously; scripts pin
  `--env` without mutating anything global.
- The unauthenticated remediation still names `--env <target>` for
  non-default targets (`login_hint`), now meaning "authenticate exactly
  this" rather than "re-auth without switching".
- CONTEXT.md retires **active environment** for **target environment**
  (per-invocation).
- An eu and a production parse of one document are separate billed
  items by design — cross-environment reuse was never sound (different
  deployments, different model versions, different job ids).
