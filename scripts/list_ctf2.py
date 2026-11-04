"""List CTF² Agent Arena challenges (read-only, never submits).

Shows the agent identity/quotas plus every practice challenge with category,
points, difficulty and solved state.

Usage:
    uv run python scripts\\list_ctf2.py
    uv run python scripts\\list_ctf2.py --categories pwn --difficulty 困难
"""

from __future__ import annotations

import asyncio
import os

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

import typer
from rich.console import Console
from rich.table import Table

from backend.config import Settings
from backend.ctf2 import Ctf2Client
from backend.ret2shell import normalize_difficulties

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    categories: str = typer.Option("", help="web,misc,pwn,re,crypto (empty = no filter)"),
    difficulty: str = typer.Option("", help="入门,简单,中等,困难 (or easy/medium/hard)"),
    ground: str = typer.Option("", help="Practice ground id/slug (empty = all grounds)"),
    details: bool = typer.Option(
        False, "--details/--no-details", help="Fill missing scores via detail calls (slower)"
    ),
) -> None:
    asyncio.run(_run(categories, difficulty, ground, details))


async def _run(categories: str, difficulty: str, ground: str, details: bool) -> None:
    settings = Settings()
    if not settings.ctf2_token:
        console.print("[red]CTF2_AGENT_TOKEN is empty — paste it from the agent-arena connect page[/red]")
        raise SystemExit(1)

    client = Ctf2Client(
        base_url=settings.ctf2_url,
        token=settings.ctf2_token,
        categories=tuple(c.strip().lower() for c in categories.split(",") if c.strip()),
        difficulties=normalize_difficulties(difficulty) if difficulty.strip() else (),
        ground=ground or settings.ctf2_ground,
    )
    try:
        me = await client.whoami()
        agent = me.get("agent") or {}
        console.print(
            f"[bold]CTF² agent:[/bold] {agent.get('name') or agent.get('slug') or '?'} "
            f"({agent.get('id') or '?'})"
        )
        if me.get("quotas"):
            console.print(f"  quotas: {me['quotas']}")
        if me.get("competition_enabled"):
            console.print(f"  competitions enabled (active: {len(me.get('active_competitions') or [])})")

        grounds = await client.grounds()
        console.print(
            "[bold]Grounds:[/bold] "
            + ", ".join(f"{g.get('id')}:{g.get('name') or g.get('slug')}" for g in grounds)
        )
        challenges = await client.fetch_all_challenges(enrich=details)
        table = Table(title=f"CTF² challenges ({len(challenges)})")
        for col in ("name", "category", "points", "difficulty", "solved", "ground"):
            table.add_column(col)
        for ch in challenges:
            table.add_row(
                str(ch.get("name")),
                str(ch.get("category")),
                str(ch.get("value") or 0),
                str(ch.get("difficulty") or "-"),
                "yes" if ch.get("solved") else "", 
                str(ch.get("ground_name") or ch.get("ground_id")),
            )
        console.print(table)
        unsolved = sum(1 for c in challenges if not c.get("solved"))
        console.print(f"[bold]{len(challenges)} challenges, {len(challenges) - unsolved} solved, {unsolved} unsolved[/bold]")
    finally:
        await client.close()


if __name__ == "__main__":
    app()
