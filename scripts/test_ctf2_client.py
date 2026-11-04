"""Offline checks for the CTF² client (httpx MockTransport, no network)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.ctf2 import Ctf2Client  # noqa: E402

# Keep the submission-dedupe database away from the real one so repeated test
# runs do not see each other's flags.
import tempfile  # noqa: E402
import uuid  # noqa: E402

from backend import submissions  # noqa: E402

submissions.DB_PATH = Path(tempfile.gettempdir()) / f"ctf2-test-subs-{uuid.uuid4().hex}.sqlite"

BASE = "https://ctf2.test"

CALLS: list[tuple[str, str]] = []


def handler(request: httpx.Request) -> httpx.Response:
    CALLS.append((request.method, request.url.path))
    path = request.url.path
    if path == "/api/open/v1/user/practice/":
        return httpx.Response(200, json={"success": True, "data": {"items": [{"id": "g1", "name": "练习场"}], "total": 1}})
    if path == "/api/open/v1/user/practice/g1/challenges/":
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "items": [
                        {"id": "c1", "name": "easy-web", "category": "WEB", "difficulty": "EASY", "points": 100, "is_solved": False},
                        {"id": "c2", "name": "hard-pwn", "category": "PWN", "difficulty": "HARD", "points": 500, "is_solved": True},
                        {"id": "c3", "name": "misc-note", "category": "MISC", "difficulty": "MEDIUM", "points": 200, "is_solved": False},
                    ]
                },
            },
        )
    if path == "/api/open/v1/user/practice/g1/challenges/c1/":
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "id": "c1",
                    "name": "easy-web",
                    "category": "WEB",
                    "difficulty": "EASY",
                    "points": 100,
                    "description": "visit the service",
                    "has_container": True,
                    "files": [{"id": "f1", "name": "attach.zip"}],
                },
            },
        )
    if path == "/api/open/v1/user/practice/g1/challenges/c1/files/f1/download/":
        return httpx.Response(200, json={"success": True, "data": {"url": f"{BASE}/blob/attach.zip"}})
    if path == "/blob/attach.zip":
        return httpx.Response(200, content=b"PK\x03\x04fake-zip")
    if path == "/api/open/v1/user/practice/g1/challenges/c1/environment/":
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "access_ready": True,
                    "access_url": "nc 1.2.3.4 31337",
                    "access_urls": [{"type": "nc", "url": "1.2.3.4:31337", "nc_ssl": False}],
                    "remaining_seconds": 3600,
                },
            },
        )
    if path == "/api/open/v1/user/practice/g1/challenges/c1/submit/":
        body = json.loads(request.content.decode())
        assert body["confirmation"] is True
        if body["flag"] == "flag{right}":
            return httpx.Response(200, json={"success": True, "data": {"accepted": True, "is_solved": True, "earned_points": 100, "attempts_left": 4}})
        return httpx.Response(200, json={"success": True, "data": {"accepted": False, "is_solved": False, "attempts_left": 3, "message": "wrong"}})
    return httpx.Response(404, json={"success": False, "data": {"message": "not found"}})


def make_client(**kwargs) -> Ctf2Client:
    kwargs.setdefault("request_interval", 0.0)
    client = Ctf2Client(base_url=BASE, token="tok_test", **kwargs)
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=BASE,
        headers={"Authorization": "Bearer tok_test"},
    )
    return client


async def main() -> None:
    # 1) listing + category filter + solved flag
    c = make_client(categories=("web", "misc"))
    chals = await c.fetch_all_challenges(enrich=False)
    names = [ch["name"] for ch in chals]
    assert names == ["easy-web", "misc-note"], names
    assert chals[0]["ground_id"] == "g1" and chals[0]["value"] == 100
    solved = await c.fetch_solved_names()
    assert solved == set(), solved
    print("listing ok:", names)

    # 2) difficulty filter
    c2 = make_client(difficulties=("简单",))
    chals2 = await c2.fetch_all_challenges(enrich=False)
    assert [ch["name"] for ch in chals2] == ["easy-web"]
    print("difficulty filter ok: 1 easy challenge")

    # 3) pull: attachment + env connection info + metadata
    tmp = Path("logs/_ctf2_test_challenges")
    c3 = make_client()
    await c3.fetch_all_challenges(enrich=False)
    d = await c3.pull_challenge(c3._by_name["easy-web"], str(tmp))
    chdir = Path(d)
    assert (chdir / "distfiles" / "attach.zip").read_bytes() == b"PK\x03\x04fake-zip"
    meta = (chdir / "metadata.yml").read_text(encoding="utf-8")
    assert "ctf2_challenge_id: c1" in meta and "1.2.3.4:31337" in meta, meta
    print("pull ok:", chdir.name, "| connection_info present")

    # 4) submit correct / incorrect
    res = await c3.submit_flag("easy-web", "flag{right}")
    assert res.status == "correct", res
    res2 = await c3.submit_flag("easy-web", "flag{right}")
    assert res2.status == "already_solved", res2
    c4 = make_client()
    await c4.fetch_all_challenges(enrich=False)
    bad = await c4.submit_flag("easy-web", "flag{wrong}")
    assert bad.status == "unknown" and "3 attempts left" in bad.display, bad
    print("submit ok:", res.status, "/", res2.status, "/", bad.display)

    # 5) missing token fails loudly
    try:
        await Ctf2Client(base_url=BASE, token="").fetch_all_challenges()
    except Exception as exc:  # noqa: BLE001
        assert "token" in str(exc).lower()
        print("token guard ok")
    else:
        raise AssertionError("expected Ctf2Error for missing token")

    print("ALL CTF2 CLIENT CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
