"""List every DASCTF exercise with score, difficulty, solved state and endpoints.

Read-only: it only calls the list/detail endpoints, it never submits flags.

Usage:
    uv run python scripts\\list_dasctf.py
    uv run python scripts\\list_dasctf.py --categories web,crypto --difficulty 困难
"""

from __future__ import annotations

import os

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

import typer
from rich.console import Console
from rich.table import Table

from backend.config import Settings
from backend.dasctf import DasctfClient, _connection_info
from backend.ret2shell import normalize_difficulties

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    categories: str = typer.Option("", help="web,misc,pwn,re,crypto (empty = no filter)"),
    difficulty: str = typer.Option("", help="入门,简单,中等,困难 (or easy/medium/hard)"),
    details: bool = typer.Option(True, "--details/--no-details", help="Fetch each exercise detail"),
) -> None:
    import asyncio

    asyncio.run(_run(categories, difficulty, details))


async def _run(categories: str, difficulty: str, details: bool) -> None:
    settings = Settings()
    if not settings.dasctf_access_key:
        console.print("[red]DASCTF_ACCESS_KEY is empty — set it in .env[/red]")
        raise SystemExit(1)

    client = DasctfClient(
        base_url=settings.dasctf_url,
        access_key=settings.dasctf_access_key,
        categories=tuple(c.strip().lower() for c in categories.split(",") if c.strip()),
        difficulties=normalize_difficulties(difficulty),
    )
    try:
        challenges = await client.fetch_all_challenges()
        table = Table(title=f"DASCTF exercises ({settings.dasctf_url})")
        table.add_column("name", style="bold")
        table.add_column("category")
        table.add_column("score", justify="right")
        table.add_column("difficulty")
        table.add_column("solved")
        table.add_column("id", justify="right")
        if details:
            table.add_column("attachment")
            table.add_column("endpoints")

        for ch in challenges:
            row = [
                ch["name"],
                ch["category"],
                str(ch.get("value") or "-"),
                ch.get("difficulty") or "-",
                "yes" if ch.get("has_solved") else "no",
                str(ch["id"]),
            ]
            if details:
                try:
                    detail = await client._detail(int(ch["id"]))
                except Exception:  # noqa: BLE001 - listing must not fail
                    detail = {}
                attachment = detail.get("attachment") or {}
                names = []
                if attachment.get("name"):
                    names.append(str(attachment["name"]))
                for item in attachment.get("files") or []:
                    if isinstance(item, dict) and item.get("name"):
                        names.append(str(item["name"]))
                row.append(", ".join(names) or "-")
                row.append(_connection_info(detail.get("endpoints")) or "-")
            table.add_row(*row)
        console.print(table)
        solved = sum(1 for ch in challenges if ch.get("has_solved"))
        console.print(f"{len(challenges)} exercises, {solved} solved, {len(challenges) - solved} unsolved")
    finally:
        await client.close()


if __name__ == "__main__":
    app()
