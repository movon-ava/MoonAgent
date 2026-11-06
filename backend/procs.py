"""Cross-platform process helpers.

The dashboard has to stop a solver together with everything it spawned (the
``uv`` wrapper, a Python CLI, and every sandboxed ``docker exec`` child), and it
has to find leftovers from a previous run. Both jobs used to be written twice
in inline PowerShell / ``taskkill`` calls that only worked on Windows. They now
live here with a POSIX branch, so a Linux deployment keeps the same behaviour.

Nothing in this module is CTF specific; it only knows about pids and names.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

WINDOWS = os.name == "nt"


def _no_window() -> dict:
    """Spawn flags that keep helper processes invisible on Windows."""
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if WINDOWS else {}


def kill_tree(pid: int, *, timeout: float = 10.0) -> bool:
    """Kill ``pid`` and its descendants. Returns True when the call was issued.

    Windows uses ``taskkill /T`` (walks the process tree, skips the console
    grace period); POSIX sends SIGTERM to the process group and falls back to
    SIGKILL once ``timeout`` has elapsed.
    """
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if WINDOWS:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                check=False,
                **_no_window(),
            )
            return True
        except OSError as exc:
            logger.debug("taskkill %s failed: %s", pid, exc)
            return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as exc:
        logger.debug("killpg(%s) failed: %s", pid, exc)
        return False
    except OSError as exc:  # not a group leader (spawned without setsid)
        logger.debug("killpg(%s) unavailable (%s), killing the pid only", pid, exc)
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return False
    # Give the tree a moment to exit, then make sure it is really gone.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(0.1)
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            return False
    return True


def list_processes(
    names: tuple[str, ...], *, min_age_s: float = 0.0
) -> list[tuple[int, str, str]]:
    """Return ``[(pid, name, cmdline)]`` for processes whose image name matches.

    Matches case-insensitively on the executable basename, so callers can pass
    ``("python.exe", "uv.exe")`` on Windows and ``("python", "uv")`` elsewhere.
    ``min_age_s`` keeps only processes that have been running for at least that
    many seconds, which is how a restart tells "a leftover from a previous
    session" apart from "the run the user started a minute ago".
    """
    wanted = {n.lower() for n in names}
    if WINDOWS:
        script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name } | "
            "ForEach-Object { \"{0}`t{1}`t{2}`t{3}\" -f $_.ProcessId, $_.Name, "
            "[int]((Get-Date) - $_.CreationDate).TotalSeconds, $_.CommandLine }"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
                **_no_window(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.debug("process listing failed: %s", exc)
            return []
        rows: list[tuple[int, str, str]] = []
        for line in (proc.stdout or "").splitlines():
            parts = line.split("\t")
            if len(parts) < 3:
                continue
            raw_pid, name, raw_age = parts[0].strip(), parts[1].strip(), parts[2].strip()
            cmdline = "\t".join(parts[3:]).strip()
            if name.lower() not in wanted:
                continue
            try:
                age = float(raw_age)
            except ValueError:
                age = 0.0
            if age < min_age_s:
                continue
            try:
                rows.append((int(raw_pid), name, cmdline))
            except ValueError:
                continue
        return rows

    try:
        proc = subprocess.run(
            ["ps", "-eo", "pid=,etimes=,comm=,args="],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("ps failed: %s", exc)
        return []
    rows = []
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 3)
        if len(parts) < 3:
            continue
        raw_pid, raw_age, comm = parts[0], parts[1], parts[2]
        cmdline = parts[3] if len(parts) > 3 else ""
        if Path(comm).name.lower() not in wanted:
            continue
        try:
            pid = int(raw_pid)
            age = float(raw_age)
        except ValueError:
            continue
        if age < min_age_s:
            continue
        rows.append((pid, comm, cmdline))
    return rows


def current_python() -> str:
    """Absolute path of the interpreter running this process."""
    return str(Path(sys.executable).resolve())
