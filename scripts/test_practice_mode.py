"""Practice-mode (include-solved) checks for CTF+."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from backend.config import Settings
from backend.ctfplus import CtfplusClient
from backend.tools.core import do_submit_flag

LIST = {
    "code": 200,
    "msg": "OK",
    "data": {
        "challenges": [
            {
                "challenge_id": 7,
                "challenge_name": "Quadratic Shadow",
                "runtimeMode": "none",
                "score": 223,
                "difficulty": 2,
                "is_solved": True,
                "tags": [{"tag_name": "Crypto"}],
                "short_des": "{}",
            }
        ]
    },
}


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/challenge/getChallengeList":
        return httpx.Response(200, json=LIST)
    raise AssertionError(f"unexpected call {request.url.path}")


async def main() -> None:
    settings = Settings()
    client = CtfplusClient(base_url="https://ctfplus.test", token="tok")
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://ctfplus.test",
        headers={"Cookie": "SessionStore=tok"},
    )

    result = await client.submit_flag("Quadratic Shadow", "SYC{whatever}")
    assert result.status == "practice", result
    assert result.display.startswith("PRACTICE"), result.display

    display, confirmed = await do_submit_flag(client, "Quadratic Shadow", "SYC{whatever}")
    assert not confirmed, "practice verdict must never confirm"
    assert display.startswith("PRACTICE"), display

    await client.close()
    print("PRACTICE MODE CHECKS PASSED")


asyncio.run(main())
