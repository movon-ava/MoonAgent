"""Offline tests for the DASCTF client (httpx MockTransport, no network)."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx

import backend.dasctf as dasctf_mod
from backend.dasctf import DasctfClient, inner_flag

OK = 0


def check(cond: bool, label: str) -> None:
    global OK
    if not cond:
        print(f"FAIL: {label}")
        sys.exit(1)
    OK += 1
    print(f"ok: {label}")


def _envelope(data=None, code="00000", message="") -> httpx.Response:
    return httpx.Response(200, json={"code": code, "message": message, "data": data or {}})


DETAIL = {
    "id": 101,
    "name": "WEB",
    "description": 'Banner\n附件下载地址：https://files.example/pack.zip',
    "hasSolved": False,
    "score": "300.0",
    "difficulty": "HARD",
    "attachment": {
        "name": "pack.zip",
        "url": "https://files.example/att-101.zip",
        "extension": "zip",
    },
    "endpoints": [],
    "isNeedInit": True,
    "isNeedCheck": False,
    "endpointType": "monopoly",
    "relationType": "resource",
}

ENV_UP = [
    {
        "exposeIps": ["1.2.3.4:20957"],
        "ports": ["nc/4000"],
        "portMappings": [{"type": "nc", "port": "4000", "proxy": "20957"}],
        "proxyIps": ["1.2.3.4"],
        "isProxy": True,
        "expireTime": int(time.time() * 1000) + 3_600_000,  # keep the fixture live
    }
]

calls: list[tuple[str, str, bytes]] = []


async def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    body = request.content or b""
    calls.append((request.method, path, body))

    if path.endswith("/ctf/exercise-list"):
        return _envelope(
            [
                {"id": 1, "name": "WEB", "order": 1, "corpus": [{"id": 101, "name": "WEB", "order": 1, "isOpen": True, "hasSolved": False}]},
                {"id": 2, "name": "MISC", "order": 2, "corpus": [{"id": 102, "name": "MISC", "order": 1, "isOpen": True, "hasSolved": True}]},
            ]
        )

    if path.endswith("/ctf/exercise"):
        eid = int(request.url.params["exerciseId"])
        detail = dict(DETAIL)
        detail["id"] = eid
        if eid == 101 and any(c[1].endswith("/build-exercise-env") for c in calls):
            detail["endpoints"] = ENV_UP
            detail["isNeedInit"] = False
        return _envelope(detail)

    if path.endswith("/ctf/build-exercise-env"):
        # POST bodies must be a JSON string containing JSON.
        decoded = json.loads(body.decode())
        check(isinstance(decoded, str), "build-exercise-env body is a JSON string")
        check(json.loads(decoded)["exerciseId"] in (101, 102), "build-exercise-env body decodes")
        return _envelope({})

    if path.endswith("/ctf/recover-exercise-env"):
        decoded = json.loads(json.loads(body.decode()))
        check(decoded["exerciseId"] in (101, 102), "recover-exercise-env body decodes")
        return _envelope({})

    if path.endswith("/answer-panel/answer"):
        decoded = json.loads(json.loads(body.decode()))
        check(decoded["exerciseId"] == 101, "answer body carries exerciseId")
        if decoded["flag"] == "right":
            return _envelope({"isCorrect": True})
        return _envelope(code="40001", message="提交flag错误，请重新提交（当前还有49次提交机会）")

    if request.url.host == "files.example":
        return httpx.Response(200, content=b"ZIPDATA")

    return httpx.Response(404, text=f"no route {path}")


async def main() -> None:
    dasctf_mod.ENV_POLL_INTERVAL_S = 0.01
    with tempfile.TemporaryDirectory() as tmp:
        client = DasctfClient(base_url="https://pro.dasctf.com", access_key="ak_test")
        client._client = httpx.AsyncClient(
            transport=httpx.MockTransport(handler),
            base_url="https://pro.dasctf.com",
            headers={"X-Agent-AccessKey": "ak_test"},
        )

        challenges = await client.fetch_all_challenges()
        check([c["name"] for c in challenges] == ["WEB", "MISC"], "exercise list parsed")
        check([c["id"] for c in challenges] == [101, 102], "exercise ids parsed")
        check(challenges[1]["has_solved"] is True, "hasSolved mapped")

        solved = await client.fetch_solved_names()
        check(solved == {"MISC"}, "solved names")

        wrong = await client.submit_flag("WEB", "DASCTF{wrong}")
        check(wrong.status == "incorrect", "wrong flag -> incorrect")
        check("提交机会" in wrong.message, "wrong flag message preserved")

        too_long = await client.submit_flag("WEB", "DASCTF{" + "a" * 300 + "}")
        check(too_long.status == "incorrect", "over-long flag rejected locally")
        check("256" in too_long.display, "over-long flag explains the 256-char limit")
        check(
            len([c for c in calls if c[1].endswith("/answer-panel/answer")]) == 1,
            "over-long flag never hits the API (saves quota)",
        )

        right = await client.submit_flag("WEB", "DASCTF{right}")
        check(right.status == "correct", "right flag -> correct (inner content sent)")
        answer_bodies = [c[2] for c in calls if c[1].endswith("/answer-panel/answer")]
        check(
            json.loads(json.loads(answer_bodies[-1].decode()))["flag"] == "right",
            "wrapper stripped before submit",
        )

        path = await client.pull_challenge({"id": 101, "name": "WEB", "category": "WEB", "value": 300}, tmp)
        dist = Path(path) / "distfiles"
        check((dist / "pack.zip").read_bytes() == b"ZIPDATA", "attachment downloaded")
        meta_text = (Path(path) / "metadata.yml").read_text(encoding="utf-8")
        check("value: 300" in meta_text, "metadata written")
        check("nc/4000 via proxy port 20957" in meta_text, "connection_info rendered from endpoints")

        recover_calls = [c for c in calls if c[1].endswith("/recover-exercise-env")]
        check(len(recover_calls) == 1, "environment recovered after the correct submission")

        builds_before = len([c for c in calls if c[1].endswith("/build-exercise-env")])
        conn = await client.ensure_env("WEB")
        check("1.2.3.4:20957" in conn and "nc/4000" in conn, "ensure_env reuses a live environment")
        check(
            len([c for c in calls if c[1].endswith("/build-exercise-env")]) == builds_before,
            "ensure_env did not rebuild a live environment",
        )

        await client.close()

    check(inner_flag("DASCTF{abc}") == "abc", "inner_flag strips DASCTF")
    check(inner_flag("flag{xyz}") == "xyz", "inner_flag strips flag")
    check(inner_flag("plain answer") == "plain answer", "inner_flag keeps plain text")

    print(f"\nALL DASCTF CLIENT CHECKS PASSED ({OK} checks)")


if __name__ == "__main__":
    asyncio.run(main())
