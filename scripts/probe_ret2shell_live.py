"""Live probe: confirm the Ret2Shell host is reachable and errors map cleanly.

Uses a deliberately invalid token, so it must end with the 401 message.
Run with:  uv run python scripts/probe_ret2shell_live.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ret2shell import Ret2ShellClient  # noqa: E402


async def main() -> int:
    client = Ret2ShellClient(token="invalid-token-probe", game="")
    try:
        games = await client.fetch_all_challenges()
        print("unexpected success:", games[:1])
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"{type(e).__name__}: {e}")
        ok = "please login first" in str(e)
        print("host reachable & 401 mapped correctly" if ok else "UNEXPECTED ERROR")
        return 0 if ok else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
