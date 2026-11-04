"""Offline test for the Ret2Shell client using an httpx MockTransport.

No network, no real token: it replays the JSON shapes observed from
https://ctf.xidian.edu.cn and checks list/solved/files/download/submit/poll.
Run with:  uv run python scripts/test_ret2shell_client.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.ret2shell import Ret2ShellClient  # noqa: E402

GAME = {"id": 37, "name": "MoeCTF 2026", "start_at": 0, "end_at": 9_999_999_999}
CHALLENGES = [
    {
        "id": 1,
        "name": "Ultra Potato Xplosion",
        "tag": [{"name": "misc", "primary": True}],
        "score": 100,
        "content": "Potato challenge. `nc 1.2.3.4 1337`",
        "release_at": None,
        "archive_at": None,
    },
    {
        "id": 2,
        "name": "Already Solved",
        "tag": [{"name": "web", "primary": True}],
        "score": 200,
        "content": "old",
        "release_at": None,
        "archive_at": None,
    },
]

submitted: list[str] = []
polls = {"n": 0}


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/api/game":
        return httpx.Response(200, json=[[GAME], 1])
    if path == "/api/game/37/challenge":
        return httpx.Response(200, json=[CHALLENGES, len(CHALLENGES)])
    if path == "/api/game/37/challenge/1/submit" and request.method == "GET":
        if request.url.params.get("id") == "99":
            polls["n"] += 1
            if polls["n"] < 2:  # first poll: checker still running
                return httpx.Response(200, json={"id": 99, "challenge_id": 1, "solved": None, "result": None})
            return httpx.Response(200, json={"id": 99, "challenge_id": 1, "solved": True, "result": "ok"})
        return httpx.Response(200, json={"solved": False, "solves": 3})
    if path == "/api/game/37/challenge/2/submit" and request.method == "GET":
        return httpx.Response(200, json={"solved": True, "solves": 9})
    if path == "/api/game/37/challenge/1/submit" and request.method == "POST":
        body = json.loads(request.content)
        submitted.append(body["content"])
        return httpx.Response(200, json={"id": 99, "challenge_id": 1, "solved": None, "result": None})
    if path == "/api/game/37/challenge/1/file":
        if request.url.params.get("file"):
            return httpx.Response(200, content=b"PK\x03\x04fakezip")
        return httpx.Response(200, json=[{"folder": "static", "file": "chall8.zip"}, {"folder": "checker", "file": "check.py"}])
    return httpx.Response(404, text=f"unexpected {request.method} {request.url}")


async def main() -> int:
    client = Ret2ShellClient(base_url="https://r2s.test", token="test-jwt", game="37")
    client._client = httpx.AsyncClient(
        base_url="https://r2s.test",
        headers={"Authorization": "Bearer test-jwt"},
        transport=httpx.MockTransport(handler),
    )

    chals = await client.fetch_all_challenges()
    assert [c["name"] for c in chals] == ["Ultra Potato Xplosion", "Already Solved"], chals
    assert chals[0]["category"] == "misc" and chals[0]["value"] == 100
    print("list ok:", chals[0]["name"], chals[0]["category"], chals[0]["value"])

    solved = await client.fetch_solved_names()
    assert solved == {"Already Solved"}, solved
    print("solved ok:", solved)

    res = await client.submit_flag("Ultra Potato Xplosion", "flag{mock_ok}")
    print("submit:", res.status, "|", res.message)
    assert res.status == "correct", res
    assert submitted == ["flag{mock_ok}"], submitted

    res2 = await client.submit_flag("Already Solved", "flag{x}")
    assert res2.status == "already_solved", res2
    print("already-solved ok")

    tmp = Path("F:/ctf_agent/logs/ret2shell-test")
    ch_dir = await client.pull_challenge(chals[0], str(tmp))
    meta = Path(ch_dir, "metadata.yml").read_text(encoding="utf-8")
    blob = Path(ch_dir, "distfiles", "chall8.zip").read_bytes()
    assert blob == b"PK\x03\x04fakezip", blob
    assert "Ultra Potato Xplosion" in meta and "connection_info" in meta
    print("pull ok:", ch_dir)
    print(meta.strip())

    await client.close()
    print("\nALL RET2SHELL CLIENT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
