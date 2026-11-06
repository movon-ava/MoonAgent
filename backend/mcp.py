"""Optional MCP (Model Context Protocol) tools for solvers.

CTF tooling increasingly ships as MCP servers (IDA/Burp/fetch wrappers…). We do
not want to re-implement each one: this module turns a small JSON config into
pydantic-ai MCP toolsets that solvers can call like any other tool.

``config/mcp.json``::

    {
      "servers": [
        {"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]},
        {"name": "burp", "command": "python", "args": ["burp_mcp.py"],
         "env": {"BURP_URL": "http://127.0.0.1:8080"}, "cwd": "C:/tools"}
      ]
    }

Every server is spawned as a stdio child process for the lifetime of a solve.
Malformed entries are skipped with a warning so a broken MCP config can never
stop a round.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "mcp.json"

logger = logging.getLogger(__name__)


def load_config(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or CONFIG
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("mcp: cannot read %s: %s", path, exc)
        return []
    servers = data.get("servers") if isinstance(data, dict) else data
    if not isinstance(servers, list):
        logger.warning("mcp: %s must contain a 'servers' list", path)
        return []
    out: list[dict[str, Any]] = []
    for item in servers:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command") or "").strip()
        if not command:
            logger.warning("mcp: skipping a server without a command")
            continue
        out.append(
            {
                "name": str(item.get("name") or command).strip(),
                "command": command,
                "args": [str(a) for a in (item.get("args") or [])],
                "env": {str(k): str(v) for k, v in (item.get("env") or {}).items()},
                "cwd": str(item.get("cwd") or "") or None,
            }
        )
    return out


def toolsets(path: Path | None = None) -> list[Any]:
    """Build pydantic-ai MCP toolsets; empty list when nothing is configured."""
    specs = load_config(path)
    if not specs:
        return []
    try:
        from pydantic_ai.mcp import MCPServerStdio
    except Exception as exc:  # noqa: BLE001 - MCP support is optional
        logger.warning("mcp: pydantic-ai has no MCP support here (%s)", exc)
        return []

    built: list[Any] = []
    for spec in specs:
        try:
            built.append(
                MCPServerStdio(
                    spec["command"],
                    args=spec["args"],
                    env=spec["env"] or None,
                    cwd=spec["cwd"],
                    tool_prefix=f"{spec['name']}_",
                )
            )
            logger.info("mcp: registered server %s (%s)", spec["name"], spec["command"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("mcp: cannot register %s: %s", spec["name"], exc)
    return built
