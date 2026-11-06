"""Force-close every platform target this agent started.

    uv run python scripts/close_envs.py

The competition platforms only let one account hold a couple of containers at
once, so a crashed or force-killed run can leave a target running and block the
next one. The dashboard calls this right after ``停止`` (which kills the process
tree, so the CLI's own ``finally`` never runs); you can also run it by hand.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import Settings  # noqa: E402
from backend.platform import make_platform, platform_kind  # noqa: E402


async def main() -> None:
    settings = Settings()
    kind = platform_kind(settings)
    platform = make_platform(settings)
    print(f"platform: {kind}")
    try:
        stop_all = getattr(platform, "stop_all_envs", None)
        if stop_all is None:
            print("this platform has no stop_all_envs() - nothing to close")
            return
        try:
            stopped = await asyncio.wait_for(stop_all(), timeout=180)
        except TimeoutError:
            print("timed out while closing targets")
            return
        print(f"closed {stopped} target(s) (entries are dropped even when the platform already lost the target)")
    finally:
        try:
            await platform.close()
        except Exception:  # noqa: BLE001
            print("warning: platform.close() failed (ignored)")


if __name__ == "__main__":
    asyncio.run(main())
