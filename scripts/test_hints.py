"""Quick check for the operator-hint queue."""

from __future__ import annotations

import asyncio
import sys

from backend import hints


async def main() -> int:
    q = hints._ensure_queue()
    q.put_nowait("试试 note_control 的 ioctl 参数")
    q.put_nowait("flag 可能在 dmesg 里")
    assert hints.hints_pending() == 2, hints.hints_pending()
    got = await hints.pop_hints()
    assert got == ["试试 note_control 的 ioctl 参数", "flag 可能在 dmesg 里"], got
    assert hints.hints_pending() == 0
    assert await hints.pop_hints() == []
    print("ALL HINT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
