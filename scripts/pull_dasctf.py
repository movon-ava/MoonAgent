"""Pull DASCTF exercises into F:\\ctf_agent\\challenges and print their metadata.

Usage:
    uv run python scripts\\pull_dasctf.py                     # every open exercise
    uv run python scripts\\pull_dasctf.py --only PWN          # name substring
    uv run python scripts\\pull_dasctf.py --categories web,crypto
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")

import asyncio

import typer
from rich.console import Console

from backend.config import Settings
from backend.dasctf import DasctfClient
from backend.ret2shell import normalize_difficulties

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    only: list[str] = typer.Option([], "--only", help="Only pull names containing this text"),
    categories: str = typer.Option("", help="web,misc,pwn,re,crypto (empty = no filter)"),
    difficulty: str = typer.Option("", help="入门,简单,中等,困难 (or easy/medium/hard)"),
) -> None:
    asyncio.run(_run(only, categories, difficulty))


async def _run(only: list[str], categories: str, difficulty: str) -> None:
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
        if only:
            wanted = [c for c in challenges if any(o.lower() in c["name"].lower() for o in only)]
            if not wanted:
                console.print(f"[yellow]No exercise matches {only}[/yellow]")
                return
            challenges = wanted
        for ch in challenges:
            path = await client.pull_challenge(ch, "challenges")
            files = sorted(p.name for p in (Path(path) / "distfiles").glob("*"))
            console.print(f"[bold]{ch['name']}[/bold] -> {path} files={files}")
            console.print((Path(path) / "metadata.yml").read_text(encoding="utf-8"))
    finally:
        await client.close()


if __name__ == "__main__":
    app()
