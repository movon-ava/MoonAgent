"""Close every CTF² target env we pulled locally (frees the agent's env quota).

    uv run python scripts/close_ctf2_envs.py

The agent may only hold a couple of targets at once; a stale env from an
earlier round makes every new ``environment/start`` fail with HTTP 409
``agent_environment_limit``. This walks ``challenges/*/metadata.yml`` for the
``ctf2_*`` ids we stored while pulling and DELETEs those environments.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from backend.config import Settings
from backend.ctf2 import Ctf2Client


async def main() -> None:
    settings = Settings()
    if not settings.ctf2_token:
        print("CTF2_AGENT_TOKEN is empty — nothing to do")
        return
    client = Ctf2Client(
        base_url=settings.ctf2_url,
        token=settings.ctf2_token,
        ground=settings.ctf2_ground,
    )
    try:
        root = Path(__file__).resolve().parent.parent / "challenges"
        done = 0
        for meta_path in sorted(root.glob("*/metadata.yml")):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = yaml.safe_load(f) or {}
            except Exception:
                continue
            ground_id = str(meta.get("ctf2_ground_id") or "")
            challenge_id = str(meta.get("ctf2_challenge_id") or "")
            if not ground_id or not challenge_id:
                continue
            ok = await client.stop_env_by_ids(ground_id, challenge_id)
            print(f"{'closed ' if ok else 'no env '} {meta.get('name')}")
            done += 1
        print(f"checked {done} pulled CTF² challenge(s)")

        me = await client.whoami()
        quotas = (me or {}).get("quotas") or {}
        print(
            "active_environments =",
            quotas.get("active_environments"),
            "/ max =",
            quotas.get("max_environments"),
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
