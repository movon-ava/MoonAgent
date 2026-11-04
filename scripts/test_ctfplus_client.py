"""Offline checks for the CTF+ (ctfplus) client (httpx MockTransport)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx
import yaml

from backend.ctfplus import CtfplusClient, connection_info, rich_text

BASE = "https://ctfplus.test"
CALLS: list[tuple[str, str]] = []

LIST = {
    "code": 200,
    "msg": "OK",
    "data": {
        "challenges": [
            {
                "challenge_id": 1,
                "challenge_name": "easy-web",
                "runtimeMode": "none",
                "score": 100,
                "difficulty": 1,
                "is_solved": False,
                "tags": [{"tag_name": "Web"}, {"tag_name": "WEEK1"}],
                "short_des": json.dumps(
                    {"content": [{"type": "paragraph", "data": {"text": "find the flag at /api"}}]}
                ),
            },
            {
                "challenge_id": 2,
                "challenge_name": "hard-pwn",
                "runtimeMode": "docker",
                "score": 500,
                "difficulty": 3,
                "is_solved": True,
                "tags": [{"tag_name": "Pwn"}, {"tag_name": "WEEK2"}],
                "short_des": "{}",
            },
            {
                "challenge_id": 3,
                "challenge_name": "crypto-note",
                "runtimeMode": "none",
                "score": 200,
                "difficulty": 0,
                "is_solved": False,
                "tags": [{"tag_name": "Crypto"}],
                "short_des": "{}",
            },
        ]
    },
}

DETAIL = {
    "code": 200,
    "msg": "OK",
    "data": {
        "challenge": {
            "challenge_id": 1,
            "challenge_name": "easy-web",
            "current_score": 100,
            "difficulty": 1,
            "short_des": json.dumps(
                {"content": [{"type": "paragraph", "data": {"text": "find the flag at /api"}}]}
            ),
            "attachments": [{"attachment_id": 0, "attachment_name": "a.zip", "attachment_path": "p1"}],
            "address": "http://easy.example:8080",
            "sum_solves": 7,
        }
    },
}


def handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path))
    path = request.url.path
    if path == "/api/challenge/getChallengeList":
        return httpx.Response(200, json=LIST)
    if path == "/api/challenge/getChallengeDetailInfo":
        body = json.loads(request.content or b"{}")
        assert isinstance(body.get("id"), str), "detail id must be a string"
        return httpx.Response(200, json=DETAIL)
    if path == "/api/challenge/submitFlag":
        return httpx.Response(200, json={"code": 200, "msg": "提交成功"})
    if path == "/api/file/p1":
        return httpx.Response(200, content=b"PK\x03\x04demo", headers={"Content-Type": "application/zip"})
    return httpx.Response(404, json={"code": 404})


def make_client(**kwargs) -> CtfplusClient:
    client = CtfplusClient(base_url=BASE, token="tok", **kwargs)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=BASE, headers={"Cookie": "SessionStore=tok"}
    )
    return client


async def main() -> None:
    assert rich_text(LIST["data"]["challenges"][0]["short_des"]) == "find the flag at /api"

    client = make_client()
    items = await client.fetch_all_challenges()
    assert [c["name"] for c in items] == ["easy-web", "hard-pwn", "crypto-note"], items
    easy, hard, note = items
    assert easy["category"] == "web" and easy["difficulty"] == "简单" and easy["value"] == 100
    assert hard["category"] == "pwn" and hard["solved"] is True and hard["has_container"] is True
    assert note["category"] == "crypto" and note["difficulty"] == "入门"

    solved = await client.fetch_solved_names()
    assert solved == {"hard-pwn"}, solved

    with tempfile.TemporaryDirectory() as tmp:
        out = await client.pull_challenge(easy, tmp)
        meta = yaml.safe_load((Path(out) / "metadata.yml").read_text(encoding="utf-8"))
        assert meta["name"] == "easy-web" and meta["category"] == "web"
        assert meta["connection_info"].startswith("target: http://easy.example:8080"), meta["connection_info"]
        assert meta["ctfplus_id"] == 1 and meta["value"] == 100
        files = list((Path(out) / "distfiles").glob("*"))
        assert files and files[0].read_bytes().startswith(b"PK"), files

    msg = await client.submit_flag("crypto-note", "flag{demo}")
    assert msg.status == "correct", msg
    assert "CORRECT" in msg.display, msg.display
    msg2 = await client.submit_flag("hard-pwn", "x")
    # Already-solved challenge -> practice verdict (unverifiable, not a failure).
    assert msg2.status == "practice", msg2
    assert "PRACTICE" in msg2.display, msg2.display

    await client.close()

    # Direction filter must apply to CTF+ too (it silently didn't before).
    filtered = make_client(categories=("web",))
    web_only = await filtered.fetch_all_challenges()
    assert [c["name"] for c in web_only] == ["easy-web"], web_only
    await filtered.close()

    info = connection_info("nc1.ctfplus.cn 36331", "docker")
    assert "target: nc1.ctfplus.cn 36331" in info and "- nc: nc1.ctfplus.cn 36331" in info, info
    assert connection_info("", "docker") == ""

    print("ALL CTFPLUS CLIENT CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
