"""Diagnostic: list the Ret2Shell game, challenges, solved state and attachments.

Reads credentials from F:\\ctf_agent\\.env (RET2SHELL_TOKEN / RET2SHELL_GAME).
Run with:  uv run python scripts/list_ret2shell.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import Settings  # noqa: E402
from backend.ret2shell import Ret2ShellClient, normalize_difficulties  # noqa: E402

console = Console()


async def main() -> int:
    settings = Settings()
    if not settings.ret2shell_token:
        print("RET2SHELL_TOKEN missing in .env")
        return 1

    client = Ret2ShellClient(
        base_url=settings.ret2shell_url,
        token=settings.ret2shell_token,
        game=settings.ret2shell_game,
        categories=tuple(c.strip() for c in settings.challenge_categories.split(",") if c.strip()),
        difficulties=normalize_difficulties(settings.challenge_difficulty),
    )
    everything = Ret2ShellClient(
        base_url=settings.ret2shell_url,
        token=settings.ret2shell_token,
        game=settings.ret2shell_game,
        categories=(),
    )
    try:
        all_challenges = await everything.fetch_all_challenges()
        challenges = await client.fetch_all_challenges()
        solved = await client.fetch_solved_names()
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}")
        return 1

    console.print(
        f"[bold]Categories:[/bold] {settings.challenge_categories or 'all'} -> "
        f"{len(challenges)}/{len(all_challenges)} challenges kept"
    )
    if settings.challenge_difficulty:
        console.print(f"[bold]Difficulties:[/bold] {settings.challenge_difficulty}")

    table = Table(title=f"{len(challenges)} challenges, {len(solved)} solved")
    table.add_column("#", justify="right")
    table.add_column("Name")
    table.add_column("Category")
    table.add_column("Difficulty")
    table.add_column("Score", justify="right")
    table.add_column("State")
    for i, ch in enumerate(challenges, 1):
        table.add_row(
            str(i),
            str(ch.get("name")),
            str(ch.get("category") or "-"),
            str(ch.get("difficulty") or "-"),
            str(ch.get("value") or 0),
            "[green]solved[/green]" if ch.get("name") in solved else "unsolved",
        )
    console.print(table)

    # attachments of the first few unsolved challenges
    unsolved = [c for c in challenges if c.get("name") not in solved]
    for ch in unsolved[:3]:
        try:
            files = await client.list_files(int(ch["id"]))
        except Exception as e:  # noqa: BLE001
            console.print(f"  [red]{ch['name']}: file list failed: {e}[/red]")
            continue
        console.print(f"  [cyan]{ch['name']}[/cyan]: {len(files)} attachment(s)")
        for f in files:
            console.print(f"      {f['folder']}/{f['file']}")

    await client.close()
    await everything.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
