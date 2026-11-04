"""Print WSRX tunnel state for Ret2Shell container challenges.

    uv run python scripts/check_wsrx.py

Tunnels are created on demand when a web/pwn Ret2Shell challenge is pulled:
``wsrx connect wss://<platform>/api/traffic/<traffic>?port=<port>`` is started
with ``--host 0.0.0.0`` so the sandbox can reach it through
``host.docker.internal:<local>``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import wsrx


def main() -> None:
    try:
        exe = wsrx.binary()
        print("wsrx binary:", exe)
    except Exception as exc:  # noqa: BLE001
        print("wsrx binary: MISSING -", exc)
    tunnels = wsrx.list_tunnels()
    if not tunnels:
        print("no open tunnels (logs/wsrx-tunnels.json)")
        return
    for local, entry in tunnels.items():
        print(f"127.0.0.1:{local} -> {entry.get('url')} (pid {entry.get('pid')})")
    print(json.dumps(tunnels, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
