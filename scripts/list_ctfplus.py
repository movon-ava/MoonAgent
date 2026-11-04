"""List CTF+ challenges (read-only).

    uv run python scripts\\list_ctfplus.py
    uv run python scripts\\list_ctfplus.py --categories web,pwn --difficulty 简单
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import typer
from rich.console import Console
from rich.table import Table

from backend.config import Settings
from backend.ctfplus import CtfplusClient
from backend.ret2shell import normalize_difficulties

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    categories: str = typer.Option("", "--categories", "-c", help="web,misc,pwn,re,crypto (empty = all)"),
    difficulty: str = typer.Option("", "--difficulty", "-d", help="入门,简单,中等,困难 (empty = all)"),
) -> None:
    settings = Settings()
    cats = tuple(p.strip().lower() for p in categories.split(",") if p.strip())
    try:
        diffs = normalize_difficulties(difficulty) if difficulty else ()
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2) from exc

    client = CtfplusClient(
        base_url=settings.ctfplus_url,
        token=settings.ctfplus_token,
        categories=cats,
        difficulties=diffs,
    )

    async def run() -> None:
        try:
            items = await client.fetch_all_challenges()
            console.print(f"[bold]CTF+[/bold] {settings.ctfplus_url}")
            console.print(
                f"challenges: {len(items)} | solved: {sum(1 for c in items if c['solved'])}"
            )
            table = Table(show_header=True, header_style="bold")
            for column in ("name", "direction", "points", "difficulty", "solved", "id"):
                table.add_column(column)
            for ch in sorted(items, key=lambda c: (c["solved"], -(c["value"] or 0))):
                table.add_row(
                    ch["name"][:40],
                    ch["category"],
                    str(ch["value"]),
                    ch["difficulty"] or "-",
                    "✓" if ch["solved"] else "",
                    str(ch["id"]),
                )
            console.print(table)
        finally:
            await client.close()

    asyncio.run(run())


if __name__ == "__main__":
    app()
