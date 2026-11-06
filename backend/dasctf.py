"""DASCTF platform client — AI Agent API (羊城杯 / DASCTF online matches).

Drop-in replacement for :class:`backend.ctfd.CTFdClient`: it exposes the same
duck-typed methods used by the poller, coordinator tools, swarms and the
``submit_flag`` solver tool, but talks to the DASCTF *agent* API instead of
CTFd.

Authentication is a per-stage access key (``ak_live_...``) from the player
console's "平台接入凭证" panel::

    SERVER HOST = https://pro.dasctf.com
    X-Agent-AccessKey: ak_live_...

Endpoints (see the "AI Agent API 文档" page of the competition console)::

    GET  {server}/slab-match/api/v1/agent/match/notice/match-info
    GET  {server}/slab-match/api/v1/agent/ctf/exercise-list
    GET  {server}/slab-match/api/v1/agent/ctf/exercise?exerciseId=...
    POST {server}/slab-match/api/v1/agent/ctf/build-exercise-env
    POST {server}/slab-match/api/v1/agent/ctf/recover-exercise-env
    POST {server}/slab-match/api/v1/agent/answer-panel/answer
    GET  {server}/slab-match/api/v1/agent/answer-panel/overview

Body-encoding quirk: production DASCTF (verified live 2026-11-03) only accepts a
**double encoded** JSON body — a JSON string whose content is the JSON object,
e.g. ``"{\\"exerciseId\\":12452}"``; sending the plain object returns
``40001 方法参数传递不正确``.  Replica builds (the "AI Agent CTF" training
platform, verified 2026-11-06) are the opposite: they want the plain object and
answer ``40400 exercise not found`` to the double-encoded form.  :meth:`_request`
therefore starts double-encoded, detects the mistake from the response and
remembers the working encoding in ``_plain_body``.

Flags: the competition rules say "flag 格式均为 DASCTF{} 或者 flag{}，提交时仅需
提交 {} 内内容" — the platform wants the inner content only, so
:func:`inner_flag` strips a known wrapper before submitting.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.ctfd import SubmitResult
from backend.platforms.base import Policy, aclose, double_json, make_client, send
from backend.ret2shell import matches_categories, slugify

logger = logging.getLogger(__name__)

API_PREFIX = "/slab-match/api/v1/agent"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

# One submission every few seconds is plenty; the stage allows 50 submissions
# per contestant in total (the server reports the remaining budget).
MIN_SUBMIT_INTERVAL_S = 3.0
DETAIL_PAUSE_S = 0.4

# How long to wait for a freshly started target environment to become usable.
ENV_WAIT_TIMEOUT_S = 180.0
ENV_POLL_INTERVAL_S = 5.0

FLAG_WRAPPER_RE = re.compile(r"^(?:DASCTF|dasctf|flag|FLAG|Flag)\{(.*)\}$", re.S)
URL_RE = re.compile(r"https?://[^\s\"'<>）)]+")

# DASCTF reports "EASY"/"MEDIUM"/"HARD" (and occasionally "VERY_EASY"); map
# those onto the labels the rest of the project already understands.
DASCTF_DIFFICULTIES: dict[str, str] = {
    "VERY_EASY": "入门",
    "EASY": "简单",
    "MEDIUM": "中等",
    "HARD": "困难",
    "VERY_HARD": "困难",
}


def inner_flag(flag: str) -> str:
    """Submit the content inside ``{}``; pass plain answers through untouched."""
    text = (flag or "").strip()
    match = FLAG_WRAPPER_RE.match(text)
    return match.group(1).strip() if match else text


def difficulty_label(raw: str | None) -> str:
    return DASCTF_DIFFICULTIES.get(str(raw or "").strip().upper(), "")


def _connection_info(endpoints: list[dict[str, Any]] | None) -> str:
    """Render the target connection info as plain text for the solver prompt."""
    lines: list[str] = []
    for ep in endpoints or []:
        if not isinstance(ep, dict):
            continue
        for address in ep.get("exposeIps") or []:
            lines.append(str(address))
        for mapping in ep.get("portMappings") or []:
            if isinstance(mapping, dict):
                kind = mapping.get("type") or "tcp"
                port = mapping.get("port") or ""
                proxy = mapping.get("proxy") or ""
                if proxy:
                    lines.append(f"{kind}/{port} via proxy port {proxy}")
        for user in ep.get("users") or []:
            if isinstance(user, dict) and user.get("username"):
                lines.append(f"user {user.get('username')}:{user.get('password') or ''}")
        if ep.get("isProxy"):
            for ip in ep.get("proxyIps") or []:
                lines.append(f"proxy ip {ip}")
        expire = ep.get("expireTime")
        if expire:
            lines.append(f"expires {time.strftime('%Y-%m-%d %H:%M', time.localtime(float(expire) / 1000))}")
    return "\n".join(dict.fromkeys(lines))


def _env_ready(detail: dict[str, Any]) -> bool:
    """True when the detail carries an endpoint that is up and not expired."""
    endpoints = detail.get("endpoints") or []
    if not endpoints or detail.get("isNeedCheck"):
        return False
    now_ms = time.time() * 1000.0
    for ep in endpoints:
        if not isinstance(ep, dict):
            return False
        expire = ep.get("expireTime")
        if expire and float(expire) < now_ms:
            return False
        if ep.get("serviceStatus") not in (None, "UP"):
            return False
        if ep.get("status") not in (None, "running"):
            return False
    return True


def _body(base: dict[str, Any], payload: dict[str, Any] | None, plain: bool | None) -> dict[str, Any]:
    """Request kwargs with the body encoded the way this server wants it."""
    out = dict(base)
    if payload is not None:
        out["content"] = json.dumps(payload) if plain else double_json(payload)
    return out


class DasctfError(RuntimeError):
    """A DASCTF response with ``code != "00000"``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"DASCTF {code} {message}")


@dataclass
class DasctfClient:
    base_url: str = "https://pro.dasctf.com"
    access_key: str = ""
    # Directions to pull ("web", "misc", "pwn", "re", "crypto"); empty = all.
    categories: tuple[str, ...] = ()
    # Difficulty labels to pull ("入门", "简单", "中等", "困难"); empty = all.
    difficulties: tuple[str, ...] = ()

    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    # True once the server is known to want a plain JSON body instead of the
    # double-encoded one real DASCTF expects; None means "not probed yet".
    _plain_body: bool | None = field(default=None, repr=False)
    # Re-submit challenges the platform already marks solved (practice runs).
    resubmit_solved: bool = False
    _exercises: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _exercises_at: float = field(default=0.0, repr=False)
    _details: dict[int, dict[str, Any]] = field(default_factory=dict, repr=False)
    _submit_lock: asyncio.Lock | None = field(default=None, repr=False)
    _last_submit_at: float = field(default=0.0, repr=False)

    # ------------------------------------------------------------------ http

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = make_client(
                self.base_url,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json",
                    "X-Agent-AccessKey": self.access_key,
                },
                read_timeout=180.0,
                # Domestic host: don't route through the local HTTP proxy.
                trust_env=False,
            )
        return self._client

    async def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        allow_codes: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if not self.access_key:
            raise RuntimeError(
                "DASCTF_ACCESS_KEY 未配置 — 请在 .env 中填写平台接入凭证的 ACCESSKEY"
                "（玩家控制台 → 运行环境 → ACCESSKEY）"
            )
        if "://" in self.access_key:
            raise RuntimeError(
                "DASCTF_ACCESS_KEY 看起来是站点地址，不是密钥 — "
                "SERVER HOST 填站点地址，ACCESSKEY 填运行环境页里的 ak_live_… 值"
            )
        client = await self._ensure_client()
        kwargs: dict[str, Any] = {}
        if payload is not None:
            kwargs["headers"] = {"Content-Type": "application/json"}
        try:
            resp = await send(
                client,
                method,
                f"{API_PREFIX}{path}",
                policy=Policy(name="DASCTF", attempts=4, backoff=2.0, retry_cap=15.0),
                params=params,
                **_body(kwargs, payload, self._plain_body),
            )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"DASCTF {method} {path} failed: {exc}") from exc
        if resp.status_code >= 400:
            raise RuntimeError(f"DASCTF HTTP {resp.status_code} {method} {path}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as e:
            raise RuntimeError(f"DASCTF {method} {path} returned non-JSON: {resp.text[:200]}") from e
        code = str(data.get("code") or "")
        message = str(data.get("message") or "")
        encoding_wrong = (
            payload is not None
            and self._plain_body is not True
            and (
                (code == "40001" and "提交机会" not in message)
                or code == "40400"
            )
        )
        if encoding_wrong:
            # Real DASCTF wants a JSON string containing JSON; some replicas (the
            # AI-Agent CTF training build) want a plain object and answer 40400 /
            # a parameter error when handed the double-encoded form. Try plain
            # once, and remember the encoding as soon as the server understands it.
            retry = await send(
                client,
                method,
                f"{API_PREFIX}{path}",
                policy=Policy(name="DASCTF", attempts=4, backoff=2.0, retry_cap=15.0),
                params=params,
                **_body(kwargs, payload, True),
            )
            try:
                retry_data = retry.json()
            except ValueError:
                retry_data = {}
            retry_code = str(retry_data.get("code") or "")
            retry_message = str(retry_data.get("message") or "")
            understood = (
                retry_code == "00000"
                or "提交机会" in retry_message
                or "提交flag错误" in retry_message
            )
            if understood and (retry_code, retry_message) != (code, message):
                self._plain_body = True
                data = retry_data
                code = retry_code
        if code != "00000" and code not in allow_codes:
            raise DasctfError(code, str(data.get("message") or ""))
        return data

    # ------------------------------------------------------------ discovery

    async def _exercise_list(self, force: bool = False) -> list[dict[str, Any]]:
        now = time.monotonic()
        if not force and self._exercises and now - self._exercises_at < 20.0:
            raw = self._exercises
        else:
            data = await self._request("GET", "/ctf/exercise-list")
            categories = data.get("data") or []
            raw = []
            for cat in categories:
                if not isinstance(cat, dict):
                    continue
                cat_name = str(cat.get("name") or "")
                for item in cat.get("corpus") or []:
                    if not isinstance(item, dict) or item.get("isOpen") is False:
                        continue
                    eid = item.get("id")
                    if eid is None:
                        continue
                    raw.append(
                        {
                            "id": int(eid),
                            "name": item.get("name") or f"exercise-{eid}",
                            "category": cat_name,
                            "difficulty": "",
                            "value": 0,
                            "description": "",
                            "tags": [cat_name] if cat_name else [],
                            "solves": 0,
                            "connection_info": "",
                            "has_solved": bool(item.get("hasSolved")),
                        }
                    )
            self._exercises = raw
            self._exercises_at = now

        out = [dict(ch) for ch in raw]
        if self.categories:
            before = len(out)
            out = [c for c in out if matches_categories(c["category"], c["tags"], self.categories)]
            if before != len(out):
                logger.info(
                    "DASCTF category filter (%s): keeping %s/%s challenges",
                    ",".join(self.categories),
                    len(out),
                    before,
                )
        if self.difficulties:
            before = len(out)
            kept: list[dict[str, Any]] = []
            for idx, ch in enumerate(out):
                if idx:
                    await asyncio.sleep(DETAIL_PAUSE_S)
                try:
                    detail = await self._detail(ch["id"])
                except Exception as e:  # noqa: BLE001 - a detail hiccup must not hide the list
                    logger.debug("DASCTF detail for %s failed: %s", ch["name"], e)
                    continue
                ch["difficulty"] = difficulty_label(detail.get("difficulty"))
                if ch["difficulty"] in self.difficulties:
                    kept.append(ch)
            out = kept
            logger.info(
                "DASCTF difficulty filter (%s): keeping %s/%s challenges",
                ",".join(self.difficulties),
                len(out),
                before,
            )
        return out

    async def _detail(self, exercise_id: int, force: bool = False) -> dict[str, Any]:
        if not force and exercise_id in self._details:
            return self._details[exercise_id]
        data = await self._request("GET", "/ctf/exercise", params={"exerciseId": exercise_id})
        detail = data.get("data") or {}
        self._details[exercise_id] = detail
        return detail

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        return await self._exercise_list()

    async def fetch_all_challenges(self) -> list[dict[str, Any]]:
        challenges = await self._exercise_list()
        # The exercise list has no score/description — fill them from the
        # detail endpoint so round mode can filter by score and the solver
        # prompt starts with the real description.
        for index, ch in enumerate(challenges):
            if ch.get("value") and ch.get("description"):
                continue
            if index:
                # The API rate-limits bursts of detail calls (HTTP 429).
                await asyncio.sleep(DETAIL_PAUSE_S)
            try:
                detail = await self._detail(int(ch["id"]))
            except Exception as e:  # noqa: BLE001 - enrichment is best effort
                logger.debug("DASCTF: detail for %s failed: %s", ch["name"], e)
                continue
            ch["value"] = int(float(detail.get("score") or ch.get("value") or 0))
            ch["difficulty"] = difficulty_label(detail.get("difficulty"))
            ch["description"] = str(detail.get("description") or "")
            ch["connection_info"] = _connection_info(detail.get("endpoints"))
            ch["has_container"] = bool(detail.get("isNeedInit"))
            extra = [t for t in (ch["difficulty"],) if t]
            ch["tags"] = list(dict.fromkeys([*(ch.get("tags") or []), *extra]))
        return challenges

    async def _exercise_id(self, name: str) -> int:
        for ch in await self._exercise_list():
            if ch["name"] == name:
                return int(ch["id"])
        raise RuntimeError(f'DASCTF: challenge "{name}" not found')

    # -------------------------------------------------------------- solved

    async def fetch_solved_names(self) -> set[str]:
        return {ch["name"] for ch in await self._exercise_list() if ch.get("has_solved")}

    async def _is_solved(self, name: str) -> bool:
        try:
            return name in await self.fetch_solved_names()
        except Exception:  # noqa: BLE001
            return False

    def _mark_solved(self, name: str) -> None:
        for ch in self._exercises:
            if ch["name"] == name:
                ch["has_solved"] = True

    # -------------------------------------------------------------- submit

    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        flag = (flag or "").strip()
        if not flag:
            return SubmitResult("incorrect", "empty flag", "Empty flag — nothing to submit.")
        if len(inner_flag(flag)) > 256:
            return SubmitResult(
                "incorrect",
                "flag too long",
                f"没有提交：flag 超过平台 256 字符上限（{len(inner_flag(flag))} 字符），先核对格式。",
            )
        if await self._is_solved(challenge_name) and not self.resubmit_solved:
            return SubmitResult(
                "already_solved",
                "",
                f'ALREADY SOLVED — "{flag}". The platform already credits this challenge, '
                "so nothing was submitted (tick 含已解题 / --include-solved to re-submit).",
            )

        try:
            eid = await self._exercise_id(challenge_name)
        except RuntimeError as e:
            return SubmitResult("unknown", str(e), f"提交失败: {e}")

        if self._submit_lock is None:
            self._submit_lock = asyncio.Lock()

        async with self._submit_lock:
            gap = MIN_SUBMIT_INTERVAL_S - (time.monotonic() - self._last_submit_at)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last_submit_at = time.monotonic()
            try:
                data = await self._request(
                    "POST",
                    "/answer-panel/answer",
                    {"exerciseId": eid, "flag": inner_flag(flag)},
                    allow_codes=("40001", "40409"),
                )
            except DasctfError as e:
                return SubmitResult("incorrect", e.message, f"提交失败: {e.message}")
            except RuntimeError as e:
                return SubmitResult("unknown", str(e), f"提交失败: {e}")

        code = str(data.get("code") or "")
        message = str(data.get("message") or "")
        payload = data.get("data") or {}
        if code == "00000" and payload.get("isCorrect") is True:
            self._mark_solved(challenge_name)
            self._details.pop(eid, None)
            # Free the remote environment now that the challenge is solved.
            await self.recover_exercise_env(eid)
            return SubmitResult("correct", message, f'CORRECT — "{inner_flag(flag)}" accepted. 解题成功!')
        if "提交机会" in message or "提交flag错误" in message:
            return SubmitResult("incorrect", message, f'INCORRECT — "{inner_flag(flag)}" rejected. {message}'.strip())
        if code == "40409":
            return SubmitResult("unknown", message, f"提示: {message}")
        return SubmitResult("unknown", message, f"提交结果未知: {message}")

    # ---------------------------------------------------------------- pull

    async def ensure_env(self, challenge_name: str) -> str:
        """Return the connection info for an exercise, starting its env if needed."""
        eid = await self._exercise_id(challenge_name)
        detail = await self._detail(eid, force=True)
        if _env_ready(detail):
            return _connection_info(detail.get("endpoints"))
        if not detail.get("isNeedInit"):
            # Attachment-only exercise: nothing to start, and asking the server
            # anyway only burns a request and logs a misleading 40400 warning.
            return _connection_info(detail.get("endpoints"))
        try:
            await self._request(
                "POST",
                "/ctf/build-exercise-env",
                {"exerciseId": eid},
                allow_codes=("40409",),
            )
        except (DasctfError, RuntimeError) as e:
            logger.warning("DASCTF: build-exercise-env for %s: %s", challenge_name, e)
            # Nothing to wait for: report the detail as-is so the caller can tell
            # the solver the target is unavailable instead of stalling.
            detail = await self._detail(eid, force=True)
            return _connection_info(detail.get("endpoints"))
        detail = await self._wait_for_env(eid)
        return _connection_info(detail.get("endpoints"))

    async def recover_exercise_env(self, exercise_id: int) -> bool:
        """Stop the remote environment of an exercise (best effort)."""
        try:
            await self._request(
                "POST",
                "/ctf/recover-exercise-env",
                {"exerciseId": int(exercise_id)},
                allow_codes=("40001", "40409", "40404"),
            )
            logger.info("DASCTF: recovered environment for exercise %s", exercise_id)
            return True
        except (DasctfError, RuntimeError) as e:
            logger.debug("DASCTF: recover-exercise-env %s failed: %s", exercise_id, e)
            return False

    async def _download(self, url: str, dest: Path) -> bool:
        client = await self._ensure_client()
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
        except Exception as e:  # noqa: BLE001 - attachments are best effort
            logger.warning("DASCTF: download failed for %s: %s", url, e)
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        logger.info("DASCTF: downloaded %s (%d bytes)", dest.name, len(resp.content))
        return True

    async def _wait_for_env(self, exercise_id: int, timeout_s: float = ENV_WAIT_TIMEOUT_S) -> dict[str, Any]:
        """Poll the detail until the target environment is up (or we time out)."""
        deadline = time.monotonic() + timeout_s
        detail = await self._detail(exercise_id, force=True)
        while time.monotonic() < deadline:
            endpoints = detail.get("endpoints") or []
            if endpoints and not detail.get("isNeedCheck"):
                return detail
            await asyncio.sleep(ENV_POLL_INTERVAL_S)
            detail = await self._detail(exercise_id, force=True)
            logger.info(
                "DASCTF: waiting for env of %s (isNeedCheck=%s)",
                exercise_id,
                detail.get("isNeedCheck"),
            )
        return detail

    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str:
        """Prepare ``challenges/<slug>``: attachments, target info, metadata."""
        import yaml

        name = challenge.get("name") or f"challenge-{challenge.get('id')}"
        ch_dir = Path(output_dir) / slugify(name)
        dist_dir = ch_dir / "distfiles"
        dist_dir.mkdir(parents=True, exist_ok=True)

        detail = await self._detail(int(challenge["id"]), force=True)

        # Start / wait for the target environment when the challenge needs one.
        # ``isNeedInit`` is the platform's own marker for container challenges;
        # ``relationType == "resource"`` is also set on plain attachment tasks,
        # so it must not be used on its own (it would call build-exercise-env for
        # every misc/crypto challenge).
        needs_env = bool(detail.get("isNeedInit")) and not _env_ready(detail)
        if needs_env:
            built = True
            try:
                await self._request("POST", "/ctf/build-exercise-env", {"exerciseId": int(challenge["id"])}, allow_codes=("40409",))
            except DasctfError as e:
                built = False
                logger.warning("DASCTF: build-exercise-env for %s: %s", name, e.message)
            except RuntimeError as e:
                built = False
                logger.warning("DASCTF: build-exercise-env for %s failed: %s", name, e)
            if built:
                detail = await self._wait_for_env(int(challenge["id"]))
            else:
                # The platform refused (or cannot) start an environment; waiting
                # for endpoints that will never appear would just burn the timeout.
                detail = await self._detail(int(challenge["id"]), force=True)

        # Attachments: the API returns either a single attachment object or {files: [...]}
        attachment = detail.get("attachment") or {}
        files: list[dict[str, Any]] = []
        if isinstance(attachment, dict):
            if attachment.get("url"):
                files.append(attachment)
            for item in attachment.get("files") or []:
                if isinstance(item, dict) and item.get("url"):
                    files.append(item)
        for item in files:
            fname = Path(str(item.get("name") or item["url"].split("/")[-1] or "attachment")).name
            dest = dist_dir / fname
            if dest.exists() and dest.stat().st_size > 0:
                continue
            await self._download(str(item["url"]), dest)

        # Some challenges put the download link straight into the description.
        description = str(detail.get("description") or "")
        for url in URL_RE.findall(description):
            if any(url == str(item.get("url")) for item in files):
                continue
            fname = Path(url.split("?")[0].split("/")[-1]).name
            if "." not in fname:
                continue
            dest = dist_dir / fname
            if dest.exists() and dest.stat().st_size > 0:
                continue
            await self._download(url, dest)

        category = challenge.get("category") or detail.get("category") or ""
        meta = {
            "name": name,
            "category": category or "misc",
            "description": description.strip(),
            "value": int(float(detail.get("score") or challenge.get("value") or 0)),
            "difficulty": difficulty_label(detail.get("difficulty")),
            "connection_info": _connection_info(detail.get("endpoints")),
            "has_container": bool(detail.get("isNeedInit")),
            "tags": [t for t in [category, difficulty_label(detail.get("difficulty"))] if t],
            "solves": int(challenge.get("solves") or 0),
            "exercise_id": int(challenge["id"]),
        }
        (ch_dir / "metadata.yml").write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return str(ch_dir)

    async def close(self) -> None:
        await aclose(self._client)
        self._client = None
