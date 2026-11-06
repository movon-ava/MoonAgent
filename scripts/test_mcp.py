"""Checks for the MCP bridge config loader."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import mcp


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="ctf-mcp-"))
    cfg = tmp / "mcp.json"

    assert mcp.load_config(cfg) == [], "missing file must yield no servers"
    print("missing ok")

    cfg.write_text("{not json", encoding="utf-8")
    assert mcp.load_config(cfg) == []
    print("bad json ok")

    cfg.write_text(
        json.dumps(
            {
                "servers": [
                    {"name": "fetch", "command": "uvx", "args": ["mcp-server-fetch"]},
                    {"command": "python", "env": {"A": 1}},
                    {"name": "broken"},
                    "junk",
                ]
            }
        ),
        encoding="utf-8",
    )
    specs = mcp.load_config(cfg)
    assert [s["name"] for s in specs] == ["fetch", "python"], specs
    assert specs[1]["env"] == {"A": "1"}, specs[1]
    print("parse ok")

    built = mcp.toolsets(cfg)
    assert len(built) == 2, built
    assert mcp.toolsets(tmp / "nope.json") == []
    print("toolsets ok")

    print("ALL MCP CHECKS PASSED")


if __name__ == "__main__":
    main()
