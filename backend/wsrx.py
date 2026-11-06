"""WSRX tunnel support for Ret2Shell targets.

Ret2Shell does not publish container ports directly. The web UI hands the player
a ``traffic`` token plus container ports, and the browser opens a
[WSRX](https://github.com/XDSEC/WebSocketReflectorX) tunnel to

    wss://<platform-host>/api/traffic/<traffic>?port=<port>

which maps that remote service onto a loopback port on this machine.

We spawn ``wsrx.exe connect <url> --host 0.0.0.0 --port <local>`` ourselves, so
the sandbox can reach the challenge through ``host.docker.internal:<local>``
(the ``--host 0.0.0.0`` bit is required: Docker Desktop containers cannot reach
a 127.0.0.1-only listener).

Open tunnels are tracked in ``logs/wsrx-tunnels.json`` so a later run can close
what an earlier one left behind.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "logs" / "wsrx-tunnels.json"
LOG_DIR = ROOT / "logs"

DEFAULT_API = "http://127.0.0.1:3307"  # desktop daemon (optional, diagnostics)
CANDIDATES = (
    ROOT / "tools" / "wsrx" / "target" / "release" / ("wsrx.exe" if os.name == "nt" else "wsrx"),
    ROOT / "tools" / "wsrx" / "target" / "release" / "wsrx.exe",
    Path("G:/ctf/WebSocketReflectorX/wsrx.exe"),
    Path("/usr/local/bin/wsrx"),
    Path.home() / ".cargo" / "bin" / "wsrx",
)
LOCAL_PORT_RANGE = range(41000, 41900)
START_TIMEOUT_S = 15.0


class WsrxError(RuntimeError):
    """Raised when the WSRX binary is missing or a tunnel cannot be created."""


# --------------------------------------------------------------------------
# binary + registry helpers


def binary() -> Path:
    env = os.environ.get("WSRX_BIN", "").strip()
    if env:
        path = Path(env)
        if path.exists():
            return path
        raise WsrxError(f"WSRX_BIN points to a missing file: {path}")
    for candidate in CANDIDATES:
        if candidate.exists():
            return candidate
    hint = "tools/wsrx/target/release/wsrx.exe" if os.name == "nt" else "tools/wsrx/target/release/wsrx"
    raise WsrxError(f"wsrx binary not found - put it at {hint} or set WSRX_BIN")


def _read_registry() -> dict[str, dict]:
    try:
        data = json.loads(REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_registry(entries: dict[str, dict]) -> None:
    try:
        REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        REGISTRY.write_text(json.dumps(entries, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("wsrx registry write failed: %s", exc)


def traffic_url(host_url: str, traffic: str, port: int | str) -> str:
    """``wss://<platform>/api/traffic/<traffic>?port=<port>`` (what the web UI copies)."""
    parts = urlsplit(host_url if "://" in host_url else f"https://{host_url}")
    scheme = "ws" if parts.scheme == "http" else "wss"
    host = parts.netloc or parts.path
    return f"{scheme}://{host}/api/traffic/{traffic}?port={port}"


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


def _wait_listening(port: int, timeout: float = START_TIMEOUT_S) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.3)
    return False


# --------------------------------------------------------------------------
# tunnel lifecycle


def open_tunnel(host_url: str, traffic: str, port: int | str) -> int:
    """Start a WSRX tunnel and return the local TCP port it listens on."""
    url = traffic_url(host_url, traffic, port)
    entries = _read_registry()
    for local, entry in entries.items():
        if entry.get("url") == url and _wait_listening(int(local), timeout=1.0):
            return int(local)

    exe = binary()
    local_port = 0
    for candidate in LOCAL_PORT_RANGE:
        if _port_free(candidate):
            local_port = candidate
            break
    if not local_port:
        raise WsrxError("no free local port for the WSRX tunnel")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"wsrx-{local_port}.log"
    if os.name == "nt":
        spawn: dict = {"creationflags": 0x00000008 | 0x08000000}  # DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        spawn = {"start_new_session": True}  # own session, so the tunnel outlives the solver
    with open(log_path, "ab") as handle:  # noqa: SIM115 - child owns the handle
        try:
            proc = subprocess.Popen(
                [str(exe), "connect", url, "--host", "0.0.0.0", "--port", str(local_port)],
                stdout=handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                close_fds=True,
                **spawn,
            )
        except OSError as exc:
            raise WsrxError(f"failed to start wsrx: {exc}") from exc

    if not _wait_listening(local_port):
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            logger.debug("suppressed exception in open_tunnel", exc_info=True)
        raise WsrxError(
            f"wsrx did not start listening on {local_port} (see {log_path.name})"
        )

    entries[str(local_port)] = {
        "url": url,
        "pid": proc.pid,
        "created": time.time(),
        "traffic": str(traffic),
        "port": str(port),
    }
    _write_registry(entries)
    logger.info("WSRX tunnel %s -> 0.0.0.0:%s (pid %s)", url, local_port, proc.pid)
    return local_port


def close_tunnel(local: int | str) -> None:
    entries = _read_registry()
    entry = entries.pop(str(local), None)
    if not entry:
        return
    _write_registry(entries)
    pid = int(entry.get("pid") or 0)
    if pid:
        from backend import procs

        procs.kill_tree(pid, timeout=3.0)


def close_all(keep: set[str] | None = None) -> int:
    """Kill every tunnel we started (optionally keeping a set of local ports)."""
    keep = {str(k) for k in (keep or set())}
    entries = _read_registry()
    closed = 0
    for local in list(entries):
        if local in keep:
            continue
        close_tunnel(local)
        closed += 1
    return closed


def list_tunnels() -> dict[str, dict]:
    return _read_registry()


# --------------------------------------------------------------------------
# optional desktop daemon helpers (diagnostics only)


def _client(api: str, timeout: float = 5.0):
    import httpx

    return httpx.Client(base_url=api.rstrip("/"), timeout=timeout, trust_env=False)


def daemon_alive(api: str = DEFAULT_API) -> bool:
    try:
        with _client(api, timeout=2.0) as c:
            return c.get("/version").status_code == 200
    except Exception:  # noqa: BLE001
        return False


def version(api: str = DEFAULT_API) -> str:
    with _client(api) as c:
        r = c.get("/version")
        if r.status_code != 200:
            raise WsrxError(f"wsrx /version -> HTTP {r.status_code}")
        data = r.json()
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return str(data.get("version") or "")
        return ""
