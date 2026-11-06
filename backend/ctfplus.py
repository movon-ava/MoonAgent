"""CTF+ (ctfplus) competition platform client.

Used by `geek2026.play.ctfplus.cn` style sites: a React SPA whose API lives on
the same origin under ``/api``, authenticated by the ``SessionStore`` cookie
(the value is what the browser stores after login; it is *not* a CTFd token).

    POST /api/challenge/getChallengeList      {page, page_size}
    POST /api/challenge/getChallengeDetailInfo {id: "<challenge_id>"}
    POST /api/challenge/submitFlag            {challenge_id, flag}
    GET  /api/file/<attachment_path>          attachment bytes
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend import targetenv
from backend.ctfd import SubmitResult
from backend.platforms.base import Policy, aclose, make_client, send
from backend.ret2shell import matches_categories

logger = logging.getLogger(__name__)

DIFFICULTY_LABELS = {0: "入门", 1: "简单", 2: "中等", 3: "困难", 4: "困难", 5: "困难"}
SYSTEM_TAGS = {"WEEK1", "WEEK2", "WEEK3", "WEEK4", "WEEK5", "无动态附件", "动态附件"}
URL_RE = re.compile(r"https?://[^\s\"'<>]+")


class CtfplusError(RuntimeError):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.message = message
        self.status = status


def difficulty_label(raw: Any) -> str:
    try:
        return DIFFICULTY_LABELS.get(int(raw), "")
    except (TypeError, ValueError):
        return ""


def connection_info(address: str, runtime_mode: str = "") -> str:
    """Render "nc1.ctfplus.cn 36331" (or a URL) as connection info text."""
    address = (address or "").strip()
    if not address:
        return ""
    parts = address.split()
    lines = [f"target: {address}"]
    if len(parts) == 2 and parts[1].isdigit():
        host, port = parts
        proto = "nc" if runtime_mode in ("docker", "") else runtime_mode
        lines.append(f"- {proto}: {host} {port}")
    else:
        lines.append(f"- url: {address}")
    return "\n".join(lines)


def rich_text(short_des: Any) -> str:
    """Flatten the editor.js-style JSON blob into readable text."""
    if not short_des:
        return ""
    if isinstance(short_des, str):
        try:
            short_des = json.loads(short_des)
        except Exception:  # noqa: BLE001 - plain text is fine too
            return short_des
    blocks = short_des.get("content") if isinstance(short_des, dict) else None
    if not isinstance(blocks, list):
        return str(short_des)

    out: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "text" and isinstance(node.get("text"), str) or isinstance(node.get("text"), str):
                out.append(node["text"])
            for value in node.values():
                if isinstance(value, (dict, list)):
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(blocks)
    text = "".join(out).strip()
    return text or json.dumps(short_des, ensure_ascii=False)[:2000]


@dataclass
class CtfplusClient:
    base_url: str = "https://geek2026.play.ctfplus.cn"
    token: str = ""
    max_envs: int = 0  # 0 = unknown, scheduler falls back to 1
    categories: tuple[str, ...] = ()
    difficulties: tuple[str, ...] = ()
    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _challenges: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _challenges_at: float = field(default=0.0, repr=False)
    _solved: dict[str, bool] = field(default_factory=dict, repr=False)
    _details: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_client(
                self.base_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Cookie": f"SessionStore={self.token}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/156.0",
                },
                read_timeout=180.0,
                trust_env=False,
            )
        return self._client

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        if not self.token:
            raise CtfplusError(
                "CTFPLUS_TOKEN is empty - open the site, log in, then copy the "
                "SessionStore cookie value into the dashboard config"
            )
        client = self._ensure_client()
        try:
            resp = await send(
                client,
                "POST",
                path,
                policy=Policy(name="CTF+", attempts=3, backoff=2.0, retry_cap=6.0),
                json=payload,
            )
        except httpx.HTTPError as exc:
            raise CtfplusError(f"CTF+ request failed: {exc}") from exc
        if resp.status_code == 401:
            raise CtfplusError(
                "CTF+ rejected the SessionStore cookie (HTTP 401) - log in again "
                "and refresh CTFPLUS_TOKEN",
                401,
            )
        if resp.status_code >= 400:
            raise CtfplusError(f"HTTP {resp.status_code}: {resp.text[:200]}", resp.status_code)
        try:
            body = resp.json()
        except ValueError as exc:
            raise CtfplusError(f"CTF+ returned non-JSON: {resp.text[:200]}") from exc
        code = body.get("code")
        if code not in (200, "200", None):
            raise CtfplusError(str(body.get("msg") or f"code {code}"))
        return body.get("data")

    # ------------------------------------------------------------ reading
    async def _challenge_list(self, force: bool = False) -> list[dict[str, Any]]:
        import time

        if not force and self._challenges and time.monotonic() - self._challenges_at < 60:
            return self._challenges
        out: list[dict[str, Any]] = []
        page = 1
        while page <= 40:
            data = await self._post(
                "/api/challenge/getChallengeList", {"page": page, "page_size": 100}
            )
            items = (data or {}).get("challenges") or []
            if not items:
                break
            out.extend(items)
            if len(items) < 100:
                break
            page += 1
        self._challenges = [self._stub(item) for item in out]
        self._challenges_at = time.monotonic()
        self._solved = {c["name"]: bool(c["solved"]) for c in self._challenges}
        return self._challenges

    def _category(self, item: dict[str, Any]) -> str:
        names = [str(t.get("tag_name") or "") for t in (item.get("tags") or [])]
        for name in names:
            low = name.lower()
            if any(key in low for key in ("web", "渗透")):
                return "web"
            if any(key in low for key in ("pwn", "二进制")):
                return "pwn"
            if any(key in low for key in ("reverse", "逆向", "re")):
                return "re"
            if any(key in low for key in ("crypto", "密码")):
                return "crypto"
            if any(key in low for key in ("misc", "杂项", "取证")):
                return "misc"
        return "misc"

    def _stub(self, item: dict[str, Any]) -> dict[str, Any]:
        name = str(item.get("challenge_name") or item.get("challenge_id"))
        return {
            "id": item.get("challenge_id"),
            "name": name,
            "category": self._category(item),
            "value": int(
                item.get("current_score")
                or item.get("score")
                or item.get("current_total_score")
                or 0
            ),
            "difficulty": difficulty_label(item.get("difficulty")),
            "solved": bool(item.get("is_solved")),
            "tags": [str(t.get("tag_name") or "") for t in (item.get("tags") or [])],
            "description": rich_text(item.get("short_des"))[:800],
            "has_container": str(item.get("runtimeMode") or "") not in ("", "none"),
        }

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        items = await self._challenge_list()
        return [
            c
            for c in items
            if (not self.difficulties or c["difficulty"] in self.difficulties)
            and matches_categories(c["category"], c.get("tags") or [], self.categories)
        ]

    async def fetch_all_challenges(self, enrich: bool = False) -> list[dict[str, Any]]:
        return await self.fetch_challenge_stubs()

    async def fetch_solved_names(self) -> set[str]:
        await self._challenge_list()
        return {name for name, solved in self._solved.items() if solved}

    async def _detail(self, challenge_id: Any, force: bool = False) -> dict[str, Any]:
        key = str(challenge_id)
        if not force and key in self._details:
            return self._details[key]
        data = await self._post(
            "/api/challenge/getChallengeDetailInfo", {"id": key}
        )
        challenge = (data or {}).get("challenge") or {}
        self._details[key] = challenge
        return challenge

    # ------------------------------------------------------------ writing
    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        flag = (flag or "").strip()
        if not flag:
            return SubmitResult("incorrect", "empty flag", "Empty flag - nothing to submit.")

        items = await self._challenge_list()
        entry = next((c for c in items if c["name"] == challenge_name), None)
        if entry is None:
            return SubmitResult(
                "unknown", "challenge missing", f'CTF+ challenge "{challenge_name}" not found'
            )
        if entry["solved"] or self._solved.get(challenge_name):
            # Practice mode: the platform refuses re-submissions, so the flag can
            # never be verified here. Report it as PRACTICE so the solver keeps
            # working and records its own flag instead of being confirmed for free.
            return SubmitResult(
                "practice",
                "already solved - unverifiable",
                f"PRACTICE - {challenge_name} is already solved on CTF+; the flag "
                "cannot be verified (the platform rejects re-submissions). Keep "
                "analysing, then report the flag you derived.",
            )

        client = self._ensure_client()
        try:
            resp = await client.post(
                "/api/challenge/submitFlag",
                json={"challenge_id": entry["id"], "flag": flag},
            )
            body = resp.json()
        except Exception as exc:  # noqa: BLE001 - surface as a verdict, never crash
            return SubmitResult("unknown", str(exc), f"submit_flag error: {exc}")

        code = body.get("code")
        message = str(body.get("msg") or body.get("message") or "")
        if code in (200, "200"):
            entry["solved"] = True
            self._solved[challenge_name] = True
            detail = f" ({message})" if message else ""
            return SubmitResult(
                "correct", message, f"CORRECT - {challenge_name} solved on CTF+{detail}"
            )
        if code == 402 or "已解决" in message or "already" in message.lower():
            self._solved[challenge_name] = True
            return SubmitResult(
                "already_solved",
                message,
                f"ALREADY SOLVED - {challenge_name} was already solved by this team ({message})",
            )
        return SubmitResult(
            "incorrect", message, f"INCORRECT - CTF+ rejected the flag ({message or code})"
        )

    async def start_instance(self, challenge_id: Any) -> dict[str, Any]:
        """Start the challenge's docker target; returns the API ``data`` block."""
        data = await self._post("/api/challenge/startChallenge", {"id": str(challenge_id)})
        data = data if isinstance(data, dict) else {}
        # Track what we started so every exit path can shut it down again.
        targetenv.register(
            f"ctfplus:{challenge_id}",
            ground_id="ctfplus",
            challenge_id=str(challenge_id),
            access_url=str(data.get("address") or ""),
        )
        return data

    async def stop_instance(self, challenge_id: Any) -> bool:
        ok = False
        try:
            await self._post("/api/challenge/stopChallenge", {"id": str(challenge_id)})
            ok = True
        except Exception as exc:  # noqa: BLE001 - stopping is best-effort
            logger.debug("CTF+ stopChallenge failed: %s", exc)
        if ok:
            # Keep the registry entry on failure so a later sweep can retry;
            # dropping it here loses the only id we know.
            targetenv.unregister(f"ctfplus:{challenge_id}")
        return ok

    async def _ensure_target(self, challenge_id: Any) -> str:
        """Return connection info for a docker target, (re)starting it if stale.

        The platform keeps returning the last ``address`` even after the
        instance is gone (or recycled for another player), so a cached address
        must never be trusted blindly - that produced ``实例未找到`` pages and
        solvers poking dead hosts.
        """
        import time as _time

        detail = await self._detail(challenge_id, force=True)
        address = str(detail.get("address") or "").strip()
        mode = str(detail.get("runtimeMode") or "")
        try:
            rest = int(detail.get("rest_time") or 0)
        except (TypeError, ValueError):
            rest = 0
        if address and rest and rest < int(_time.time()) + 30:
            address = ""  # instance lease already expired
        if address and not await self._target_alive(address):
            logger.info("CTF+: target %s for %s is dead, restarting", address, challenge_id)
            address = ""
        if not address:
            try:
                data = await self.start_instance(challenge_id)
            except CtfplusError as exc:
                logger.warning("CTF+ start target for %s failed: %s", challenge_id, exc)
                return ""
            address = str((data or {}).get("address") or "").strip()
            if not address:
                return ""
            detail["address"] = address
        return connection_info(address, mode)

    async def _target_alive(self, address: str) -> bool:
        """TCP-probe the target behind ``address`` (URL targets are assumed up)."""
        from backend import targets

        info = connection_info(address)
        if not targets.parse_targets(info):
            return True
        ok, _ = await asyncio.to_thread(targets.check, info, f"alive:{address}", 3.0)
        return bool(ok)

    async def ensure_env(self, challenge_name: str) -> str:
        entry = await self._entry(challenge_name)
        if entry is None:
            return ""
        return await self._ensure_target(entry["id"])

    async def stop_env(self, challenge_name: str) -> bool:
        entry = await self._entry(challenge_name)
        if entry is None:
            return False
        challenge_id = entry["id"]
        # The platform refuses to stop a container that is still building, and
        # that build window is exactly when our timeout fires. Retry briefly.
        for attempt in range(4):
            if await self.stop_instance(challenge_id):
                return True
            await asyncio.sleep(2.0 + attempt)
        logger.warning("CTF+ could not stop the target for %s", challenge_name)
        return False

    async def max_environments(self) -> int:
        """How many targets this account may hold at once.

        The competition decides this per account (the platform answers
        ``容器数量已达上限`` when it is full), so take it from configuration
        (``MAX_ENVIRONMENTS``) and fall back to a conservative 1.
        """
        try:
            return max(1, int(self.max_envs or 1))
        except (TypeError, ValueError):
            return 1

    async def stop_all_envs(self) -> int:
        """Stop every target this agent started (called on any exit path)."""
        stopped = 0
        for key, entry in list(targetenv.owned().items()):
            if str(entry.get("ground_id") or "") != "ctfplus":
                continue
            challenge_id = str(entry.get("challenge_id") or key.split(":", 1)[-1])
            ok = False
            for _attempt in range(3):
                try:
                    ok = await self.stop_instance(challenge_id)
                except Exception as exc:  # noqa: BLE001 - best effort
                    logger.debug("CTF+ stop_all_envs(%s) failed: %s", challenge_id, exc)
                    ok = False
                if ok:
                    break
                await asyncio.sleep(2.0)
            if ok:
                stopped += 1
            else:
                logger.warning("CTF+ could not stop target %s; keeping it in the registry", challenge_id)
        return stopped

    async def renew_env(self, challenge_name: str) -> bool:
        """Extend the docker target's lifetime (POST /challenge/delayChallenge)."""
        entry = await self._entry(challenge_name)
        if entry is None:
            return False
        try:
            await self._post("/challenge/delayChallenge", {"id": str(entry["id"])})
            logger.debug("CTF+: renewed target for %s", challenge_name)
            return True
        except Exception as exc:  # noqa: BLE001 - renewal is best effort
            logger.debug("CTF+: renew %s failed: %s", challenge_name, exc)
            return False

    async def _entry(self, name: str) -> dict[str, Any] | None:
        for item in await self._challenge_list():
            if item["name"] == name:
                return item
        return None

    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str:
        import yaml

        name = str(challenge.get("name") or challenge.get("id"))
        ch_dir = Path(output_dir) / re.sub(r"[^\w.\-]+", "_", name).strip("_")[:80]
        dist_dir = ch_dir / "distfiles"
        dist_dir.mkdir(parents=True, exist_ok=True)

        detail = await self._detail(challenge.get("id"))
        description = rich_text(detail.get("short_des") or challenge.get("description"))

        needs_target = str(detail.get("runtimeMode") or "").lower() not in ("", "none") or bool(
            detail.get("is_docker")
        )
        connection = ""
        if needs_target:
            try:
                connection = await self._ensure_target(challenge.get("id"))
            except Exception as exc:  # noqa: BLE001 - never block the pull
                logger.warning("CTF+ target for %s failed: %s", name, exc)

        client = self._ensure_client()
        for att in detail.get("attachments") or []:
            path = str(att.get("attachment_path") or "")
            fname = str(att.get("attachment_name") or Path(path).name or "attachment")
            if not path:
                continue
            dest = dist_dir / Path(fname).name
            if dest.exists() and dest.stat().st_size > 0:
                continue
            try:
                async with client.stream("GET", f"/api/file/{path}") as resp:
                    if resp.status_code != 200:
                        logger.warning("CTF+ attachment %s: HTTP %s", fname, resp.status_code)
                        continue
                    with open(dest, "wb") as handle:
                        async for chunk in resp.aiter_bytes():
                            handle.write(chunk)
            except Exception as exc:  # noqa: BLE001 - never block a pull
                logger.warning("CTF+ attachment %s failed: %s", fname, exc)

        for url in URL_RE.findall(description):
            fname = Path(url.split("?")[0].split("/")[-1]).name
            if "." not in fname:
                continue
            dest = dist_dir / fname
            if dest.exists() and dest.stat().st_size > 0:
                continue
            try:
                async with client.stream("GET", url) as resp:
                    if resp.status_code != 200:
                        continue
                    with open(dest, "wb") as handle:
                        async for chunk in resp.aiter_bytes():
                            handle.write(chunk)
            except Exception as exc:  # noqa: BLE001
                logger.warning("CTF+ url download %s failed: %s", url, exc)

        meta = {
            "name": name,
            "category": challenge.get("category") or "misc",
            "description": description.strip(),
            "value": int(detail.get("current_score") or detail.get("current_total_score") or challenge.get("value") or 0),
            "difficulty": challenge.get("difficulty") or difficulty_label(detail.get("difficulty")),
            "connection_info": connection
            or connection_info(str(detail.get("address") or ""), str(detail.get("runtimeMode") or "")),
            "tags": challenge.get("tags") or [],
            "solves": int(detail.get("sum_solves") or 0),
            "ctfplus_id": challenge.get("id"),
            "has_container": needs_target,
        }
        with open(ch_dir / "metadata.yml", "w", encoding="utf-8") as handle:
            yaml.safe_dump(meta, handle, allow_unicode=True, sort_keys=False)
        return str(ch_dir)

    async def close(self) -> None:
        await aclose(self._client)
        self._client = None
