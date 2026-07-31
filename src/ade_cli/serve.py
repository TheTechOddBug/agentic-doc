"""``view --serve`` — the http door onto the same viewer artifacts.

``file://`` keys browser zoom by the full URL (fragment included), so no
zoom survives a sidebar hop and the template ships a CSS-zoom
approximation (view_template.html's FILE_MODE branch). Served from a
loopback origin instead, the browser owns zoom per-origin: one menu zoom
covers every sibling viewer, persists across hops, reloads and restarts,
and the zoom indicator stays truthful. The artifacts are byte-identical
either way — every reference in them (history.js, pages-N.js chunks) is
relative — so this is a second door, not a second build; the same
view.html stays double-clickable and shareable as a file.

Lifecycle mirrors the sidebar's background builder (view._spawn_builder):
``view --serve`` probes the recorded port for a live server over THIS
store (``GET /__ade__/health`` names the store root); a hit is reused, a
miss spawns a detached ``view --serve-daemon`` re-exec and waits for
health. The daemon owns port selection (bind may race) and records the
outcome in ``server.json`` at the store root — the port must STICK across
runs, because Chrome keys per-origin state (zoom, localStorage) by
scheme+host+port and a wandering port would silently reset every zoom.

Loopback only, by construction: the store is private and the server never
binds anything but 127.0.0.1. Directory listings are refused — every
artifact is addressed by exact path.
"""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from .ports import Ports

STATE_FILE = "server.json"
HEALTH_PATH = "/__ade__/health"
SHUTDOWN_PATH = "/__ade__/shutdown"
# An open viewer polls history.js every 3s, so "idle" means no page is
# open anywhere: the daemon then retires itself instead of lingering
# forever. The next --serve respawns it on the recorded port.
IDLE_SHUTDOWN_S = 30 * 60
IDLE_CHECK_S = 15.0
# Default origin, shared by every store on the machine until one is
# already serving a different store (then the next free port upward is
# claimed and recorded, so each store keeps a stable origin of its own).
DEFAULT_PORT = 8642
PORT_SCAN = 10  # candidates tried above the default before giving up
SPAWN_WAIT_S = 5.0


class ServeError(Exception):
    """The server could not be reached or started; the caller degrades to
    the file:// door and says so."""


def state_path(home: Path) -> Path:
    return home / STATE_FILE

def _read_state(home: Path) -> dict:
    try:
        state = json.loads(state_path(home).read_text())
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(home: Path, port: int, pid: int) -> None:
    state_path(home).write_text(json.dumps({"port": port, "pid": pid}) + "\n")


def url_for(port: int, item_id: str) -> str:
    return f"http://127.0.0.1:{port}/jobs/{item_id}/view.html"


def probe(ports: Ports, port: int, home: Path) -> bool:
    """True iff OUR server for THIS store answers on the port. The health
    body names the store root, so a server left over from another
    ``ADE_HOME`` (or an unrelated local service) is never mistaken for
    ours. Goes through ``ports.transport`` like every other request the
    CLI makes — the offline suite scripts it."""
    try:
        with httpx.Client(transport=ports.transport, timeout=1.0) as client:
            response = client.get(f"http://127.0.0.1:{port}{HEALTH_PATH}")
        body = response.json()
        return (
            response.status_code == 200
            and body.get("ade") is True
            and Path(str(body.get("home", ""))).resolve() == home.resolve()
        )
    except Exception:
        return False


def ensure_server(home: Path, ports: Ports, spawn) -> int:
    """The port of a live server over ``home`` — reused when one already
    answers, else started via ``spawn(port)`` (a detached ``--serve-daemon``
    re-exec; injected so tests never fork). The daemon may settle on a
    different port than the candidate (bind races, another store on the
    default), so readiness is confirmed by re-reading server.json and
    probing what it records."""
    recorded = _read_state(home).get("port")
    if isinstance(recorded, int) and probe(ports, recorded, home):
        return recorded

    candidate = recorded if isinstance(recorded, int) else DEFAULT_PORT
    try:
        spawn(candidate)
    except OSError as error:
        # A failed re-exec (missing interpreter, fork limits) degrades to
        # the file:// door like every other serve failure — the artifact
        # on disk is complete either way.
        raise ServeError(f"could not start the viewer server: {error}") from error
    deadline = ports.clock.monotonic() + SPAWN_WAIT_S
    while ports.clock.monotonic() < deadline:
        port = _read_state(home).get("port")
        if isinstance(port, int) and probe(ports, port, home):
            return port
        ports.clock.sleep(0.1)
    raise ServeError(
        "the viewer server did not come up within "
        f"{SPAWN_WAIT_S:.0f}s (see {state_path(home)})"
    )


def _bind(
    home: Path, candidate: int, activity: dict | None = None
) -> ThreadingHTTPServer:
    """Bind the candidate port, else scan a few above the default — a
    neighbor store may hold ours — else let the OS assign. Whatever wins
    is recorded by the caller and becomes this store's stable origin."""
    handler = _handler_for(home, activity)
    tried = [candidate, *range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN), 0]
    seen: set[int] = set()
    for port in tried:
        if port in seen:
            continue
        seen.add(port)
        try:
            return ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            continue
    raise ServeError("no loopback port available")  # port 0 failing = no sockets


def _request_path(raw: str) -> str:
    """The decoded, dot-collapsed path of a request line — normalized
    BEFORE the allowlist check, so ``/jobs/%2e%2e/credentials.json``
    cannot smuggle past a prefix test."""
    import posixpath
    from urllib.parse import unquote

    return posixpath.normpath(unquote(raw.split("?", 1)[0].split("#", 1)[0]))


def _allowed(path: str) -> bool:
    """The viewer needs exactly two things from the store: the artifacts
    under jobs/ and the sidebar's history.js. Everything else at the
    store root (credentials.json, config.json, telemetry) is secret to
    the CLI and must be unreachable even by exact path — loopback is
    reachable by every local process."""
    return path == "/history.js" or path == "/jobs" or path.startswith("/jobs/")


def _handler_for(home: Path, activity: dict | None = None):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(home), **kwargs)

        def handle_one_request(self):
            if activity is not None:
                import time

                activity["last"] = time.monotonic()
            super().handle_one_request()

        def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler's casing)
            path = _request_path(self.path)
            if path == HEALTH_PATH:
                body = json.dumps({"ade": True, "home": str(home)}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if not _allowed(path):
                self.send_error(404)
                return
            super().do_GET()

        def do_HEAD(self):  # noqa: N802 (BaseHTTPRequestHandler's casing)
            if not _allowed(_request_path(self.path)):
                self.send_error(404)
                return
            super().do_HEAD()

        def do_POST(self):  # noqa: N802 (BaseHTTPRequestHandler's casing)
            # The off-switch (`view --stop-server`): answer first, then
            # shut down from another thread — shutdown() blocks until the
            # serve loop drains, and this handler IS the serve loop.
            if self.path.split("?", 1)[0] == SHUTDOWN_PATH:
                import threading

                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.send_error(404)

        def end_headers(self):
            # Artifacts rebuild in place (fingerprint-gated) and history.js
            # rewrites on every run: heuristic http caching would show a
            # stale viewer after a rebuild. no-cache forces revalidation —
            # an unchanged file still answers 304 (Last-Modified), so hops
            # stay fast while rebuilds land immediately.
            self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        def list_directory(self, path):
            self.send_error(403, "directory listing disabled")
            return None

        def log_message(self, format, *args):  # noqa: A002 (stdlib signature)
            pass  # detached daemon; stdout/stderr are DEVNULL anyway

    return Handler


def stop_server(home: Path, ports: Ports) -> int | None:
    """Ask a running server for this store to retire. The shutdown
    endpoint first (pid-free); a server that answers health but REFUSES
    the verb (an older build still running across an upgrade — a clean
    non-200) gets SIGTERM on the recorded pid instead. Only that exact
    case falls back: a POST that *errors* (timeout, reset) is ambiguous
    — the pid in server.json is trusted only as far as the daemon wrote
    it, and signaling on a hand-edited or stale file could hit an
    unrelated process — so it raises for the caller to report instead.
    Returns the stopped port, or None when nothing of ours answers."""
    state = _read_state(home)
    port = state.get("port")
    if not isinstance(port, int) or not probe(ports, port, home):
        return None
    try:
        with httpx.Client(transport=ports.transport, timeout=1.0) as client:
            response = client.post(f"http://127.0.0.1:{port}{SHUTDOWN_PATH}")
    except Exception as error:
        raise ServeError(
            f"the server on port {port} answered health but the shutdown "
            f"request failed ({type(error).__name__}); stop it manually: "
            f"kill {state.get('pid', '<pid from server.json>')}"
        ) from error
    if response.status_code == 200:
        return port
    pid = state.get("pid")
    if isinstance(pid, int) and pid > 0:
        import os
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
            return port
        except OSError:
            pass
    raise ServeError(
        f"the server on port {port} is ours but predates the shutdown "
        f"endpoint and its recorded pid could not be signaled; stop it "
        f"manually: kill {state.get('pid', '<pid from server.json>')}"
    )


def _watch_idle(server, activity: dict, timeout: float, check_s: float) -> None:
    """Retire the server after ``timeout`` seconds without a request. An
    open viewer's 3s history.js poll counts, so this only fires once no
    page is watching."""
    import time

    while True:
        time.sleep(check_s)
        if time.monotonic() - activity["last"] > timeout:
            server.shutdown()
            return


def run_daemon(home: Path, candidate: int) -> None:
    """The ``--serve-daemon`` body: bind, record the outcome, serve until
    stopped (the shutdown endpoint, or the idle watchdog). The parent
    watches server.json + health; server.json survives shutdown so the
    port stays sticky for the next spawn."""
    import os
    import threading
    import time

    activity = {"last": time.monotonic()}
    server = _bind(home, candidate, activity)
    _write_state(home, server.server_address[1], os.getpid())
    threading.Thread(
        target=_watch_idle,
        args=(server, activity, IDLE_SHUTDOWN_S, IDLE_CHECK_S),
        daemon=True,
    ).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
