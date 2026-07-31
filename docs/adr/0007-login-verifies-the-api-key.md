# ADR-0007: `auth login` verifies the API key before storing it

Date: 2026-07-29 · Status: accepted

## Context

Field report (#117): `ade auth login` accepted any string as an API key
— the first signal that a key was mistyped came as an `HTTP 401` on the
user's first `parse`/`extract`, minutes or days later and far from the
gesture that caused it. Worse, the 401 the verb relayed quoted the
platform's own error body, and the platform emits *different* 401
bodies depending on which check rejected the key (`Invalid API Key
Format` from a shape check, `Invalid API Key, please check…` from the
lookup) — the same user mistake produced inconsistent error text, and
the CLI printed it as raw JSON because the auth layer's `{"error": …}`
envelope wasn't one of the shapes `gateway._error_fields` parsed.

There is no dedicated auth-check route in the v2 contract. Every job
route bills or mutates. The one authenticated route that is free and
side-effect-free is the usage-ledger upload, `POST /v2/telemetry`
(ADR-0006) — an empty batch records nothing but still passes the same
auth gate every API request passes.

## Decision

- **Verify, then store.** An API-key login (flag, prompt, or pipe)
  POSTs an empty batch to the resolved target's `/v2/telemetry` with
  the candidate key as Bearer before anything is written
  (`auth.py::_verify_api_key`, `gateway.verify_credential`). The
  request self-identifies with a `probe/auth` User-Agent token — the
  UA grammar's documented extension seam (`docs/user-agent.md`), so it
  is greppable in platform request logs and safely ignored by parsers
  that don't know it. 200 stores
  the key and reports `verified`. A 401 is the platform's authoritative
  "invalid key": the login fails, stores nothing. Any other outcome
  (5xx, unreachable network) says nothing about the key, so the login
  reports the platform problem — status, code, and message — advises
  trying again later, and stores nothing. OAuth logins already verify
  themselves (the token exchange is the check) and are untouched.
- **One canonical invalid-credential line.** Neither the login nor the
  verbs quote the platform's 401 body in the human line. Login says the
  target rejected this key, check it and retry; a verb's 401
  (`guarantee._exit_http_error`) says the target rejected the
  credential and names the exact `ade auth login [--env …]` to run.
  The server's own text stays available in the `--json` payload's
  `message` (and `_error_fields` now parses the `{"error": …}`
  envelope, so that field is the server's sentence, never raw JSON).
  `ReloginRequired` keeps its own line — it already names the OAuth
  cause and remediation.

## Consequences

- Login now requires the network: an offline `ade auth login` fails
  (verification-unreachable, nothing stored) where it used to "succeed"
  by storing an uncheckable key. Deliberate: a stored-but-unverified
  key is exactly the deferred failure #117 reports. `ADE_API_KEY`
  remains the escape hatch for pre-provisioned environments — it is
  used per request, never stored, and is not a login.
- The probe is one request with a 10s ceiling
  (`gateway.VERIFY_TIMEOUT_SECONDS`), not the job routes' 300s.
- The empty batch is a contract assumption: `/v2/telemetry` must keep
  returning 200 for `[]` and 401 for a bad key. If the platform ever
  ships a dedicated auth-check route, `verify_credential` is the one
  seam to repoint.
- Server-side message inconsistency is reported upstream but no longer
  user-visible through the CLI; fixing the platform's 401 bodies is
  out of scope here.
