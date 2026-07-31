# The usage ledger ships after every command, partitioned by environment, marked in place

## Context

The local usage ledger (#52) buffers one event per invocation; #53 ships
it to the platform's `POST /v2/telemetry` (the aide gateway logs one
Loki line per record and returns 200 only after all are logged — the
final contract in
[#53](https://github.com/landing-ai/ade-cli/issues/53)).
Three properties are non-negotiable: the flush must never change a
command's observable behavior, the ledger must stay bounded whether or
not uploads ever succeed, and events must not re-send unboundedly under
at-least-once delivery. Three designs were open: when to flush, where a
mixed-environment backlog ships, and how shipped rows are remembered
against a deliberately lock-free-until-now appender.

## Decision

- **Flush at the ledger seam, after every command.** The root group's
  `finally` records the invocation's event and then ships the whole
  unshipped backlog — the 40th invocation carries events 31–40,
  including itself. One seam, no per-command wiring, and the flush runs
  after output and exit code are already decided. Offline commands pay
  at most one short-timeout (5 s) connect attempt, and a transport-level
  failure abandons the remaining partitions.
- **Partitioned by environment, each to its own endpoint.** An event
  ships to the environment it targeted, authenticated with that
  environment's *stored* credential (keys do not cross environments;
  `ADE_API_KEY` covers only the invocation's own namespace). No
  credential → stays buffered; `custom` ships only while an
  `ADE_ENDPOINT` override addresses it; a flush never refreshes an OAuth
  token and never prompts.
- **Marked in place, not pruned.** Acknowledged rows gain `shipped:
  true` — the ledger keeps being the locally inspectable record — and
  rotation enforces the bound: oldest lines drop first past 256 KiB or
  30 days, shipped or not, upload or no upload. Dedup across the rare
  lost 200 rides the `idempotent_key` minted on every event at record
  time (pre-#53 rows derive a deterministic content hash at flush time).
- **The appender joins the ledger lock.** Marking and rotation rewrite
  the file (tmp + `os.replace`); an unlocked `O_APPEND` write racing
  that replace could land on the unlinked inode and vanish. Appends and
  rewrites now share `.telemetry.lock`, which is never held across the
  network, so the wait is bounded in milliseconds and "never in the way"
  holds. Corrupt lines are preserved byte-for-byte (never shipped, never
  age-expired — only the size cap takes them).

## Consequences

- No standing daemon, no spawned process, no new command surface: users
  who never run a command never upload, and heavy users ship
  continuously. Test harnesses shield the flush with the new
  upload-only opt-out (`ADE_TELEMETRY_UPLOAD=0`) — which is also the
  user-facing middle ground between full `ADE_TELEMETRY=0` and default-on.
- Events for an environment the user never authenticates against (and
  `unknown`) sit until rotation drops them — accepted: shipping them
  cross-environment would put usage rows in the wrong cluster's
  analytics and use a credential their traffic never used.
- The gateway endpoint must exist before events ship; until it does,
  every flush is a silent non-200 and rotation keeps the ledger bounded,
  so the CLI can release ahead of the platform deploy without harm.
