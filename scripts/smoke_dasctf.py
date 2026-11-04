"""Live smoke test for the DASCTF client (no flag submission — saves quota)."""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

from rich.console import Console
from rich.table import Table

from backend.config import Settings
from backend.dasctf import DasctfClient, inner_flag

console = Console()


async def main() -> None:
    settings = Settings()
    client = DasctfClient(
        base_url=settings.dasctf_url,
        access_key=settings.dasctf_access_key,
        categories=(),
        difficulties=(),
    )
    try:
        challenges = await client.fetch_all_challenges()
        table = Table(title=f"DASCTF exercises ({len(challenges)})")
        table.add_column("name")
        table.add_column("category")
        table.add_column("solved")
        table.add_column("exercise_id")
        for ch in challenges:
            table.add_row(
                ch["name"], ch["category"], str(ch.get("has_solved")), str(ch["id"])
            )
        console.print(table)

        detail = await client._detail(challenges[0]["id"])
        att = detail.get("attachment") or {}
        console.print(
            f"[bold]{detail.get('name')}[/bold] score={detail.get('score')} "
            f"difficulty={detail.get('difficulty')} isNeedInit={detail.get('isNeedInit')}"
        )
        console.print(f"attachment: {att.get('name')} ({att.get('extension')}) url={att.get('url')}")
        console.print(f"endpoints: {detail.get('endpoints')}")
        console.print(f"inner_flag demo: {inner_flag('DASCTF{abc_123}')!r}")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
