"""Start the web dashboard detached, with a sanitized environment.

PowerShell's Start-Process refuses to launch because the Windows environment
block contains case-duplicate proxy keys (NO_PROXY and no_proxy). Python can
drop the lowercase duplicates and spawn the dashboard cleanly.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG = ROOT / "logs"

KEEP_UPPER = {"NO_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}


def main() -> None:
    argv = sys.argv[1:] or ["--port", "8099"]
    for key in list(os.environ):
        if key.upper() in KEEP_UPPER and key not in KEEP_UPPER:
            os.environ.pop(key, None)
    LOG.mkdir(exist_ok=True)
    out = open(LOG / "webui-out.log", "ab")
    err = open(LOG / "webui-err.log", "ab")
    creationflags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        [str(PYTHON), str(ROOT / "scripts" / "webui.py"), *argv],
        cwd=str(ROOT),
        stdout=out,
        stderr=err,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    print(f"dashboard pid={proc.pid} port={argv[-1] if argv else 8099}")


if __name__ == "__main__":
    main()
