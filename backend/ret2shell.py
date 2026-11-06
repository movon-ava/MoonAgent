"""Ret2Shell platform client — 西电 CTF 终端 (ctf.xidian.edu.cn / MoeCTF).

Drop-in replacement for :class:`backend.ctfd.CTFdClient`: it exposes the same
duck-typed methods used by the poller, coordinator tools, swarms and the
``submit_flag`` solver tool, but talks to the Ret2Shell REST API instead of
CTFd.

API notes (reverse engineered from the open-source server,
https://github.com/ret2shell/ret2shell):

* Base URL ``https://ctf.xidian.edu.cn``, REST prefix ``/api``.
* Auth: ``Authorization: Bearer <session token>`` (HS256 JWT kept in the SPA's
  ``localStorage.account.token``; the server also requires the token to exist
  in its cache, so it must come from a live browser session).
* ``GET  /api/game``                                 games list
* ``GET  /api/game/{gid}/challenge``                 ``[challenges, count]``
* ``GET  /api/game/{gid}/challenge/{cid}``           one challenge (markdown)
* ``GET  /api/game/{gid}/challenge/{cid}/file``      ``[{folder, file}, ...]``
* ``GET  /api/game/{gid}/challenge/{cid}/file?folder=static&file=NAME``
* ``GET  /api/game/{gid}/challenge/{cid}/submit``    ``{solved, solves}`` or
  ``?id=<submission_id>`` for a single submission
* ``POST /api/game/{gid}/challenge/{cid}/submit``    ``{"content": flag}``

The checker runs asynchronously, so a freshly created submission has
``solved: null`` — we poll ``?id=`` for a few seconds until the verdict shows
up.  Submissions are rate limited to 10 per 5 minutes per user.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from backend.ctfd import SubmitResult
from backend.platforms.base import Policy, aclose, make_client, send

logger = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"

API_PREFIX = "/api"
# One attempt: ret2shell's 401/412/429 bodies carry the actionable advice, and
# the submit path has its own "10 per 5 minutes" throttle.
RET2SHELL_POLICY = Policy(name="Ret2Shell", attempts=1)

# The server allows 10 submissions per 5 minutes per user.  30 s between
# submissions would be the safest pace, but that cripples solvers that need one
# or two retries — 6 s keeps normal single submissions instant and relies on
# the 429 handler for the pathological cases.
MIN_SUBMIT_INTERVAL_S = 6.0
MAX_SUBMIT_SPACING_HINT = 30

# Challenge directions we care about (CTF classics).  The site's categories are
# free-form Chinese tags, so every direction maps to the keywords its category
# names actually use — e.g. "二进制漏洞审计" is pwn, "软件逆向工程" is re.
CATEGORY_ALIASES: dict[str, tuple[str, ...]] = {
    "web": ("web", "渗透"),
    "misc": ("misc", "杂项", "取证"),
    "pwn": ("pwn", "二进制", "漏洞"),
    "re": ("逆向", "reverse", "re"),
    "crypto": ("crypto", "密码"),
}


def _alias_matches(alias: str, text: str) -> bool:
    """Case-insensitive match; short ASCII aliases must be standalone words.

    Without the boundary check the alias "re" would match inside unrelated words
    such as "reverse" or "ret2shell" — harmless here, but let's be precise.
    """
    if alias.isascii() and len(alias) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", text) is not None
    return alias in text


def matches_categories(
    category: str,
    tags: list[str] | tuple[str, ...],
    categories: tuple[str, ...] | list[str] | None,
) -> bool:
    """True when the challenge belongs to one of the requested directions.

    ``categories`` accepts the aliases ``web`` / ``misc`` / ``pwn`` / ``re`` /
    ``crypto`` (case-insensitive); an empty sequence or ``{"all"}`` disables the
    filter.  Matching runs against the primary category tag *and* every tag.
    """
    wanted = [c.strip().lower() for c in (categories or ()) if c and c.strip()]
    if not wanted or "all" in wanted:
        return True
    text = " ".join([category or "", *(tags or [])]).lower()
    for want in wanted:
        aliases = CATEGORY_ALIASES.get(want, (want,))
        if any(_alias_matches(alias, text) for alias in aliases):
            return True
    return False


# The site puts difficulty into a free-form tag ("入门"/"简单"/"中等"/"困难");
# normalize the English words people tend to type onto those same labels.
DIFFICULTY_ALIASES: dict[str, str] = {
    "入门": "入门",
    "intro": "入门",
    "beginner": "入门",
    "简单": "简单",
    "easy": "简单",
    "basic": "简单",
    "中等": "中等",
    "medium": "中等",
    "normal": "中等",
    "困难": "困难",
    "hard": "困难",
}
DIFFICULTY_LEVELS: dict[str, int] = {"入门": 1, "简单": 2, "中等": 3, "困难": 4}


def difficulty_of(tags: list[str] | tuple[str, ...], category: str = "") -> str:
    """The challenge's difficulty tag ("入门"/"简单"/"中等"/"困难") or ""."""
    if category in DIFFICULTY_LEVELS:
        return category
    for tag in tags or ():
        name = str(tag).strip()
        if name and name != category and name in DIFFICULTY_LEVELS:
            return name
    return ""


def normalize_difficulties(spec: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Parse ``"easy,hard"`` / ``"简单"`` into canonical difficulty labels.

    Raises ``ValueError`` on an unknown word so the CLI can show the accepted
    spellings instead of silently pulling nothing.
    """
    if isinstance(spec, str):
        raw = [p.strip() for p in spec.split(",")]
    else:
        raw = [str(p).strip() for p in spec]
    wanted: list[str] = []
    for word in raw:
        if not word:
            continue
        key = word.lower()
        canonical = DIFFICULTY_ALIASES.get(key)
        if canonical is None:
            allowed = ", ".join(DIFFICULTY_LEVELS)
            raise ValueError(f"unknown difficulty {word!r} (use one of: {allowed}, or English easy/medium/hard)")
        if canonical not in wanted:
            wanted.append(canonical)
    return tuple(wanted)


def slugify(name: str) -> str:
    slug = re.sub(r'[<>:"/\\|?*.\x00-\x1f]', "", (name or "").lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "challenge"


def _flatten(items: Any) -> list[dict[str, Any]]:
    """The API likes to wrap lists as ``[[...], count]`` or ``{"data": [...]}``."""
    if isinstance(items, dict):
        items = items.get("data", items)
    if isinstance(items, list):
        if len(items) == 2 and isinstance(items[0], list):
            items = items[0]
        return [i for i in items if isinstance(i, dict)]
    return []


@dataclass
class Ret2ShellClient:
    base_url: str = "https://ctf.xidian.edu.cn"
    token: str = ""
    # Game id ("37"), game name ("MoeCTF 2026"), or "" for the active game.
    game: str = ""
    # Directions to pull ("web", "misc", "pwn", "re", "crypto"); empty = all.
    categories: tuple[str, ...] = ()
    # Difficulty labels to pull ("入门", "简单", "中等", "困难"); empty = all.
    difficulties: tuple[str, ...] = ()

    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _game_id: int | None = field(default=None, repr=False)
    _game_name: str = field(default="", repr=False)
    _challenge_ids: dict[str, int] = field(default_factory=dict, repr=False)
    _challenges: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _challenges_at: float = field(default=0.0, repr=False)
    _solved: dict[str, bool] = field(default_factory=dict, repr=False)
    _solved_at: float = field(default=0.0, repr=False)
    _solves: dict[str, int] = field(default_factory=dict, repr=False)
    _submit_lock: asyncio.Lock | None = field(default=None, repr=False)
    _last_submit_at: float = field(default=0.0, repr=False)

    # ------------------------------------------------------------------ http

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
            }
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = make_client(
                self.base_url,
                headers=headers,
                read_timeout=120.0,
                verify=False,
                # Domestic host: don't route through the local HTTP proxy.
                trust_env=False,
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = await self._ensure_client()
        # Ret2Shell answers 401/412/429 with hand-written advice, so a failed
        # request is surfaced immediately instead of being retried blindly.
        resp = await send(
            client,
            method,
            f"{API_PREFIX}{path}",
            policy=RET2SHELL_POLICY,
            **kwargs,
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "Ret2Shell 401 please login first — RET2SHELL_TOKEN 无效或已过期，"
                "请从浏览器 localStorage.account.token 重新复制（登录后立即获取）"
            )
        if resp.status_code == 412:
            raise RuntimeError(
                f"Ret2Shell 412 {resp.text[:120]} — 该接口不可用（可能需要走 /api 前缀或游戏 id 不对）"
            )
        if resp.status_code == 429:
            raise RuntimeError(
                f"Ret2Shell 429 提交过于频繁（限制 10 次/5 分钟）: {resp.text[:160]}"
            )
        if resp.status_code == 403:
            raise RuntimeError(f"Ret2Shell 403 {resp.text[:200]}")
        if resp.status_code >= 400:
            raise RuntimeError(f"Ret2Shell {resp.status_code} {method} {path}: {resp.text[:300]}")
        return resp

    async def _get_json(self, path: str, **kwargs: Any) -> Any:
        resp = await self._request("GET", path, **kwargs)
        return resp.json()

    # ------------------------------------------------------------ discovery

    async def _ensure_game(self) -> int:
        if self._game_id is not None:
            return self._game_id
        games = _flatten(await self._get_json("/game"))
        if not games:
            raise RuntimeError("Ret2Shell: /api/game returned no games")
        chosen: dict[str, Any] | None = None
        wanted = (self.game or "").strip()
        if wanted:
            for g in games:
                if str(g.get("id")) == wanted or str(g.get("name", "")).strip() == wanted:
                    chosen = g
                    break
            if chosen is None:
                names = ", ".join(f"{g.get('id')}:{g.get('name')}" for g in games)
                raise RuntimeError(f"Ret2Shell: game '{wanted}' not found. Available: {names}")
        else:
            now = time.time()
            active = [g for g in games if (g.get("start_at") or 0) <= now <= (g.get("end_at") or 0)]
            chosen = (active or games)[0]
        self._game_id = int(chosen["id"])
        self._game_name = str(chosen.get("name", ""))
        logger.info("Ret2Shell game: %s (id=%s)", self._game_name, self._game_id)
        return self._game_id

    async def _challenge_list(self, force: bool = False) -> list[dict[str, Any]]:
        # Round mode asks for the list twice (stubs + solved probe); cache it
        # briefly so one round costs one /challenge call instead of two.
        now = time.monotonic()
        if not force and self._challenges and now - self._challenges_at < 20.0:
            return self._challenges
        gid = await self._ensure_game()
        raw = _flatten(await self._get_json(f"/game/{gid}/challenge"))
        out: list[dict[str, Any]] = []
        for ch in raw:
            tags_raw = ch.get("tag") or []
            tags = [
                (t.get("name") if isinstance(t, dict) else str(t))
                for t in tags_raw
            ]
            primary = next(
                (
                    t.get("name")
                    for t in tags_raw
                    if isinstance(t, dict) and t.get("primary")
                ),
                tags[0] if tags else "",
            )
            out.append(
                {
                    "id": ch.get("id"),
                    "name": ch.get("name", "?"),
                    "category": primary,
                    "difficulty": difficulty_of(tags, primary),
                    "value": ch.get("score", 0) or 0,
            "has_container": any(
                key in str(primary).lower() for key in ("web", "pwn", "二进制", "渗透")
            ),
                    "description": ch.get("content") or "",
                    "tags": [t for t in tags if t],
                    "solves": 0,
                    "connection_info": "",
                    "release_at": ch.get("release_at"),
                    "archive_at": ch.get("archive_at"),
                }
            )
        if self.difficulties:
            before = len(out)
            out = [c for c in out if c.get("difficulty") in self.difficulties]
            logger.info(
                "Ret2Shell difficulty filter (%s): keeping %s/%s challenges",
                ",".join(self.difficulties),
                len(out),
                before,
            )
        if self.categories:
            before = len(out)
            out = [c for c in out if matches_categories(c["category"], c["tags"], self.categories)]
            if before != len(out):
                logger.info(
                    "Ret2Shell category filter (%s): keeping %s/%s challenges",
                    ",".join(self.categories),
                    len(out),
                    before,
                )

        self._challenge_ids = {c["name"]: int(c["id"]) for c in out if c.get("id") is not None}
        self._challenges = out
        self._challenges_at = time.monotonic()
        return out

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        return await self._challenge_list()

    async def fetch_all_challenges(self) -> list[dict[str, Any]]:
        return await self._challenge_list()

    async def _challenge_id(self, name: str) -> int:
        if name in self._challenge_ids:
            return self._challenge_ids[name]
        await self._challenge_list()
        if name not in self._challenge_ids:
            raise RuntimeError(f'Ret2Shell: challenge "{name}" not found')
        return self._challenge_ids[name]

    # -------------------------------------------------------------- solved

    async def _solved_map(self, force: bool = False, ttl: float = 20.0) -> dict[str, bool]:
        """Per-challenge solved flags (there is no bulk endpoint)."""
        now = time.monotonic()
        if not force and self._solved and now - self._solved_at < ttl:
            return self._solved
        gid = await self._ensure_game()
        challenges = await self._challenge_list()
        sem = asyncio.Semaphore(8)

        async def one(ch: dict[str, Any]) -> tuple[str, bool, int]:
            async with sem:
                try:
                    data = await self._get_json(f"/game/{gid}/challenge/{ch['id']}/submit")
                    return ch["name"], bool(data.get("solved")), int(data.get("solves") or 0)
                except Exception as e:  # noqa: BLE001 - one bad challenge must not kill the rest
                    logger.debug("solved probe failed for %s: %s", ch.get("name"), e)
                    return ch["name"], False, 0

        results = await asyncio.gather(*(one(c) for c in challenges))
        self._solved = {name: solved for name, solved, _ in results}
        self._solves = {name: solves for name, _, solves in results}
        self._solved_at = time.monotonic()
        return self._solved

    async def fetch_solved_names(self) -> set[str]:
        solved = await self._solved_map()
        return {name for name, ok in solved.items() if ok}

    # -------------------------------------------------------------- submit

    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        flag = (flag or "").strip()
        if not flag:
            return SubmitResult("incorrect", "empty flag", "Empty flag — nothing to submit.")

        gid = await self._ensure_game()
        cid = await self._challenge_id(challenge_name)

        if (await self._solved_map()).get(challenge_name):
            return SubmitResult(
                "already_solved", "", f'ALREADY SOLVED — "{flag}".'
            )

        if self._submit_lock is None:
            self._submit_lock = asyncio.Lock()

        async with self._submit_lock:
            gap = MIN_SUBMIT_INTERVAL_S - (time.monotonic() - self._last_submit_at)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last_submit_at = time.monotonic()

            path = f"/game/{gid}/challenge/{cid}/submit"
            try:
                resp = await self._request("POST", path, json={"content": flag})
            except RuntimeError as e:
                msg = str(e)
                if "429" in msg:
                    return SubmitResult(
                        "incorrect",
                        msg,
                        "RATE LIMITED — 平台限制 10 次/5 分钟，请等待几分钟再提交，"
                        "不要继续猜 flag，先做更深入的分析。",
                    )
                return SubmitResult("unknown", msg, f"提交失败: {msg}")

            body = resp.json()
            verdict = await self._wait_for_verdict(body)

        if verdict is True:
            self._solved[challenge_name] = True
            return SubmitResult("correct", str(body.get("result") or ""), f'CORRECT — "{flag}" accepted. 解题成功!')
        if verdict is False:
            msg = str(body.get("result") or "").strip()
            return SubmitResult("incorrect", msg, f'INCORRECT — "{flag}" rejected. {msg}'.strip())
        return SubmitResult(
            "unknown",
            "",
            "SUBMITTED — checker 还在运行（结果稍后确认），不要重复提交同一 flag。",
        )

    async def _wait_for_verdict(self, submission: dict[str, Any], timeout_s: float = 25.0) -> bool | None:
        """Poll the submission until the async checker fills ``solved``."""
        if not isinstance(submission, dict):
            return None
        if submission.get("solved") is not None:
            return bool(submission["solved"])
        sid = submission.get("id")
        gid = self._game_id
        if sid is None or gid is None:
            return None
        cid = submission.get("challenge_id")
        if cid is None:
            return None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(1.0)
            try:
                data = await self._get_json(
                    f"/game/{gid}/challenge/{cid}/submit", params={"id": sid}
                )
            except Exception as e:  # noqa: BLE001 - polling is best effort
                logger.debug("submit poll failed: %s", e)
                continue
            if isinstance(data, dict) and data.get("solved") is not None:
                submission["result"] = data.get("result")
                return bool(data["solved"])
        return None

    # ---------------------------------------------------------------- pull

    async def list_files(self, challenge_id: int) -> list[dict[str, str]]:
        gid = await self._ensure_game()
        raw = await self._get_json(f"/game/{gid}/challenge/{challenge_id}/file")
        files = raw if isinstance(raw, list) else []
        return [
            {"folder": f.get("folder", "static"), "file": f.get("file", "")}
            for f in files
            if isinstance(f, dict) and f.get("file") and f.get("folder") != "checker"
        ]

    async def _download_file(self, challenge_id: int, folder: str, name: str) -> bytes:
        gid = await self._ensure_game()
        resp = await self._request(
            "GET",
            f"/game/{gid}/challenge/{challenge_id}/file",
            params={"folder": folder, "file": name},
        )
        return resp.content

    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str:
        """Download attachments + write ``metadata.yml``. Returns the directory."""
        import yaml

        name = challenge.get("name") or f"challenge-{challenge.get('id')}"
        ch_dir = Path(output_dir) / slugify(name)
        dist_dir = ch_dir / "distfiles"
        dist_dir.mkdir(parents=True, exist_ok=True)

        cid = challenge.get("id") or await self._challenge_id(name)
        try:
            files = await self.list_files(int(cid))
        except Exception as e:  # noqa: BLE001 - challenges may have no files
            logger.warning("Ret2Shell: could not list files for %s: %s", name, e)
            files = []

        for f in files:
            fname = Path(f["file"]).name or "file"
            dest = dist_dir / fname
            if dest.exists() and dest.stat().st_size > 0:
                continue
            try:
                blob = await self._download_file(int(cid), f["folder"], f["file"])
                dest.write_bytes(blob)
                logger.info("Ret2Shell: downloaded %s (%d bytes)", fname, len(blob))
            except Exception as e:  # noqa: BLE001
                logger.warning("Ret2Shell: download failed for %s: %s", fname, e)

        connection_info = challenge.get("connection_info") or ""
        category = challenge.get("category", "") or "misc"
        # Container challenges get a fresh target every pull: an instance and
        # its tunnel are per-run, so reusing yesterday's connection_info would
        # point the solver at a dead (or someone else's) tunnel.
        if any(
            key in str(category).lower() for key in ("web", "pwn", "二进制", "渗透")
        ):
            try:
                connection_info = await self.tunnel_target(int(cid))
            except Exception as exc:  # noqa: BLE001 - never block a pull
                logger.warning("Ret2Shell: tunnel setup for %s failed: %s", name, exc)
        meta = {
            "name": name,
            "category": category,
            "description": (challenge.get("description") or "").strip(),
            "value": challenge.get("value", 0) or 0,
            "connection_info": connection_info,
            "tags": challenge.get("tags") or [],
            "solves": challenge.get("solves", 0) or 0,
        }
        (ch_dir / "metadata.yml").write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        return str(ch_dir)

    async def _instances(self) -> list[dict[str, Any]]:
        gid = int(self.game) if str(self.game or "").isdigit() else await self._ensure_game()
        try:
            data = await self._get_json(f"/game/{gid}/instance")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Ret2Shell: list instances: %s", exc)
            return []
        if isinstance(data, dict):
            data = data.get("data") or []
        return [item for item in (data or []) if isinstance(item, dict)]

    async def _drop_running(self, keep_challenge: int) -> None:
        """Stop every running instance except ``keep_challenge`` and wait for
        the platform to actually let go (it allows one instance per player)."""
        for item in await self._instances():
            cid = int(item.get("challenge_id") or 0)
            if cid == keep_challenge:
                continue
            if str(item.get("state") or "").lower() == "running":
                await self.stop_instance(cid)
        for _ in range(20):
            running = [
                item
                for item in await self._instances()
                if str(item.get("state") or "").lower() == "running"
                and int(item.get("challenge_id") or 0) != keep_challenge
            ]
            if not running:
                return
            await asyncio.sleep(0.5)

    async def stop_all_envs(self) -> int:
        """Stop every running instance of this account (used on exit)."""
        stopped = 0
        for item in await self._instances():
            if str(item.get("state") or "").lower() != "running":
                continue
            try:
                cid = int(item.get("challenge_id") or 0)
            except (TypeError, ValueError):
                continue
            if not cid:
                continue
            try:
                if await self.stop_instance(cid):
                    stopped += 1
            except Exception as exc:  # noqa: BLE001 - best effort
                logger.debug("Ret2Shell stop_all_envs(%s): %s", cid, exc)
        return stopped

    async def start_instance(self, challenge_id: int) -> dict[str, Any] | None:
        """Start the challenge container (idempotent) and return its instance."""
        gid = int(self.game) if str(self.game or "").isdigit() else await self._ensure_game()
        for item in await self._instances():
            if (
                int(item.get("challenge_id") or 0) == int(challenge_id)
                and str(item.get("state") or "").lower() == "running"
            ):
                return item
        for attempt in range(3):
            await self._drop_running(int(challenge_id))
            try:
                await self._request(
                    "POST", f"/game/{gid}/challenge/{challenge_id}/instance"
                )
            except Exception as exc:  # noqa: BLE001 - 412 while rebuilding
                logger.debug(
                    "Ret2Shell: start instance %s (attempt %s): %s",
                    challenge_id,
                    attempt + 1,
                    exc,
                )
                await asyncio.sleep(2.0 + attempt)
            for _ in range(20):
                for item in await self._instances():
                    if (
                        int(item.get("challenge_id") or 0) == int(challenge_id)
                        and str(item.get("state") or "").lower() == "running"
                    ):
                        return item
                await asyncio.sleep(1.0)
        return None

    async def stop_instance(self, challenge_id: int) -> None:
        gid = int(self.game) if str(self.game or "").isdigit() else await self._ensure_game()
        try:
            await self._request("DELETE", f"/game/{gid}/challenge/{challenge_id}/instance")
        except Exception as exc:  # noqa: BLE001 - nothing running is fine
            logger.debug("Ret2Shell: stop instance %s: %s", challenge_id, exc)

    async def max_environments(self) -> int:
        """Ret2Shell allows one running instance per player."""
        return 1

    async def renew_env(self, challenge_name: str) -> bool:
        """Extend the running instance's lifetime (PATCH .../instance)."""
        cid = self._challenge_ids.get(challenge_name) or await self._challenge_id(challenge_name)
        if not cid:
            return False
        gid = int(self.game) if str(self.game or "").isdigit() else await self._ensure_game()
        try:
            await self._request("PATCH", f"/game/{gid}/challenge/{int(cid)}/instance")
            logger.debug("Ret2Shell: renewed instance for %s", challenge_name)
            return True
        except Exception as exc:  # noqa: BLE001 - renewal is best effort
            logger.debug("Ret2Shell: renew instance %s: %s", challenge_name, exc)
            return False

    async def stop_env(self, challenge_name: str) -> bool:
        cid = self._challenge_ids.get(challenge_name) or await self._challenge_id(challenge_name)
        if not cid:
            return False
        await self.stop_instance(int(cid))
        return True

    async def ensure_env(self, challenge_name: str) -> str:
        """Start the instance for ``challenge_name`` and expose it via WSRX."""
        cid = self._challenge_ids.get(challenge_name) or await self._challenge_id(challenge_name)
        return await self.tunnel_target(int(cid))

    async def tunnel_target(self, challenge_id: int) -> str:
        """Start the instance and expose its ports on this machine via WSRX."""
        from backend import wsrx

        instance = await self.start_instance(challenge_id)
        if not instance:
            return ""
        traffic = str(instance.get("traffic") or "")
        ports = [p for p in (instance.get("ports") or []) if str(p)]
        if not traffic or not ports:
            return ""
        lines: list[str] = []
        for port in ports:
            try:
                local = wsrx.open_tunnel(self.base_url, traffic, port)
            except Exception as exc:  # noqa: BLE001 - keep the pull usable
                lines.append(f"- port {port}: WSRX tunnel failed ({exc})")
                continue
            lines.append(
                f"- port {port}: host.docker.internal:{local} (open http://<host>:"
                f"{port}/ inside the challenge; reachable from the sandbox as "
                f"host.docker.internal:{local})"
            )
        if not lines:
            return ""
        return (
            f"target: {traffic} (WSRX tunnel to this machine; the challenge "
            "service listens on the container port, the sandbox reaches it via "
            "the host ports below)\n" + "\n".join(lines)
        )

    async def close(self) -> None:
        await aclose(self._client)
        self._client = None
