"""CTF² (ctf2.dasctf.com) Agent Arena client.

Talks to the public *Agent Open API* (``/api/open/v1/user``) with an Agent
PAT.  Everything the solver needs goes through this class: list practice
challenges, download attachments, start target environments, submit flags.

Auth: ``Authorization: Bearer <CTF2_AGENT_TOKEN>`` (an ``X-CTF2-API-Key``
header is accepted by the platform too; we use the Bearer form).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from backend.ctfd import SubmitResult
from backend.platforms.base import Policy, aclose, make_client, send
from backend.ret2shell import matches_categories, slugify

logger = logging.getLogger(__name__)

OPEN_PREFIX = "/api/open/v1/user"
DETAIL_PAUSE_S = 0.25
ENV_WAIT_TIMEOUT_S = 180.0
ENV_POLL_INTERVAL_S = 3.0
DOWNLOAD_TIMEOUT_S = 300.0
# Safety ceiling for paging through one practice ground (100 per page).
MAX_GROUND_PAGES = 200

# A ground's challenge list rarely changes mid-round; caching it keeps the
# coordinator (which asks every turn) from re-paging 30+ requests per turn.
GROUND_CACHE_TTL_S = 180.0

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _ground_key(value: str) -> str:
    """Normalise a ground selector: accept a bare UUID, a full practice URL, or a name."""
    text = str(value or "").strip()
    if not text:
        return ""
    match = _UUID_RE.search(text)
    if match:
        return match.group(0).lower()
    return text.lower()

DIFFICULTY_LABELS = {
    "VERY_EASY": "入门",
    "EASY": "简单",
    "MEDIUM": "中等",
    "HARD": "困难",
    "VERY_HARD": "困难",
}

URL_RE = re.compile(r"https?://[^\s<>()\"'`]+")


def difficulty_label(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    return DIFFICULTY_LABELS.get(text.upper(), text)


class Ctf2Error(RuntimeError):
    """Raised when the CTF² API answers with an error."""

    def __init__(self, message: str, *, status: int = 0, code: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def _is_env_limit(exc: Ctf2Error) -> bool:
    """True when the platform refused because the agent has no free target slot."""
    if exc.code == "agent_environment_limit":
        return True
    text = f"{exc.message} {exc.code}".lower()
    return "environment_limit" in text or "environment limit" in text


@dataclass
class Ctf2Client:
    """Minimal CTF² Agent Arena adapter used by the solver/round runner."""

    base_url: str = "https://ctf2.dasctf.com"
    token: str = ""
    categories: tuple[str, ...] = ()
    difficulties: tuple[str, ...] = ()
    # Optional: only this practice ground (slug or id); empty = all grounds.
    ground: str = ""
    # Minimum seconds between two platform requests (the API rate-limits
    # bursts aggressively). Shared across processes through platformgate.
    request_interval: float = 0.8

    _client: httpx.AsyncClient | None = field(default=None, repr=False)
    _me: dict[str, Any] | None = field(default=None, repr=False)
    _grounds: list[dict[str, Any]] | None = field(default=None, repr=False)
    _challenges: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _by_name: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _details: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict, repr=False)
    # Ground id -> (fetched_at, challenges). A full CTF² list is 30+ paced
    # requests and the coordinator asks for it every turn; refetching each time
    # made the first spawn look like "nothing is happening".
    _ground_cache: dict[str, tuple[float, list[dict[str, Any]]]] = field(
        default_factory=dict, repr=False
    )
    _submit_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _last_submit_at: float = 0.0
    _scope: str = field(default="", repr=False)

    def _submission_scope(self) -> str:
        if not self._scope:
            from backend import submissions

            self._scope = submissions.scope_for("ctf2", self.base_url, self.token)
        return self._scope

    # ---------------------------------------------------------------- HTTP
    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json", "User-Agent": "ctf-agent/1.0"}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"
            self._client = make_client(self.base_url, headers=headers, read_timeout=180.0)
        return self._client

    def _require_token(self) -> None:
        if not self.token:
            raise Ctf2Error(
                "CTF² requires an Agent token — paste the CTF2_AGENT_TOKEN from the "
                "agent-arena connect page into the config panel (or .env)."
            )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> Any:
        self._require_token()
        client = await self._ensure_client()
        try:
            resp = await send(
                client,
                method,
                path,
                policy=Policy(
                    name="CTF2",
                    attempts=3,
                    backoff=1.5,
                    retry_cap=8.0,
                    pace=self.request_interval,
                ),
                params=params,
                json=payload,
                attempts=attempts,
            )
        except httpx.HTTPError as exc:
            raise Ctf2Error(f"cannot reach {self.base_url}: {exc}") from exc

        if resp.status_code == 401:
            raise Ctf2Error(
                "CTF² rejected the token (HTTP 401) — generate a new Agent token on the "
                "agent-arena connect page.",
                status=401,
            )
        if resp.status_code >= 400:
            raise Ctf2Error(f"HTTP {resp.status_code}: {resp.text[:200]}", status=resp.status_code)

        try:
            body = resp.json()
        except ValueError as exc:
            raise Ctf2Error(f"non-JSON response: {resp.text[:200]}") from exc

        if isinstance(body, dict) and body.get("success") is False:
            data = body.get("data") or {}
            message = ""
            if isinstance(data, dict):
                message = str(data.get("message") or data.get("error") or "")
            raise Ctf2Error(message or "CTF² returned success=false", code=str(data)[:80])
        if isinstance(body, dict) and "data" in body:
            return body["data"]
        return body

    # ------------------------------------------------------------- account
    async def whoami(self) -> dict[str, Any]:
        if self._me is None:
            self._me = await self._request("GET", f"{OPEN_PREFIX}/agent/me/")
        return self._me

    async def grounds(self) -> list[dict[str, Any]]:
        if self._grounds is None:
            # The practice index is occasionally 503 during maintenance; retry
            # for ~1 minute before giving up on a round.
            data = await self._request("GET", f"{OPEN_PREFIX}/practice/", attempts=6)
            items = data.get("items", data) if isinstance(data, dict) else data
            self._grounds = [g for g in items if isinstance(g, dict)]
        return self._grounds

    async def _ground_by_name(self, name: str) -> dict[str, Any] | None:
        wanted = _ground_key(name)
        if not wanted:
            return None
        for g in await self.grounds():
            keys = {_ground_key(str(g.get("id"))), _ground_key(str(g.get("slug"))), _ground_key(str(g.get("name")))}
            if wanted in keys:
                return g
        return None

    def _matching_grounds(self, grounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Grounds selected by ``self.ground`` (all when it is empty)."""
        if not self.ground:
            return grounds
        wanted = _ground_key(self.ground)
        picked = [
            g
            for g in grounds
            if wanted
            in {
                _ground_key(str(g.get("id"))),
                _ground_key(str(g.get("slug"))),
                _ground_key(str(g.get("name"))),
            }
        ]
        if not picked:
            available = ", ".join(f"{g.get('name')} ({g.get('id')})" for g in grounds)
            raise Ctf2Error(
                f"CTF² practice ground {self.ground!r} not found — use the UUID from the "
                f"practice page URL, or one of: {available}"
            )
        return picked

    # --------------------------------------------------------- challenges
    async def _ground_challenges(
        self, ground: dict[str, Any], force: bool = False
    ) -> list[dict[str, Any]]:
        gid = str(ground.get("id"))
        cached = self._ground_cache.get(gid)
        if (
            not force
            and cached
            and asyncio.get_running_loop().time() - cached[0] < GROUND_CACHE_TTL_S
        ):
            return cached[1]
        raw_items: list[dict[str, Any]] = []
        # BUUCTF alone has 3200+ challenges: follow ``total_page`` instead of a
        # fixed page cap, with a generous safety ceiling. Pages are fetched
        # concurrently — sequentially this took ~30s and made "pull" feel slow.
        first = await self._request(
            "GET",
            f"{OPEN_PREFIX}/practice/{gid}/challenges/",
            params={"limit": 100, "page": 1},
            attempts=5,
        )
        if not isinstance(first, dict):
            return []
        raw_items.extend(item for item in (first.get("items") or []) if isinstance(item, dict))
        total_page = min(int(first.get("total_page") or 1), MAX_GROUND_PAGES)
        if total_page > 1:
            gate = asyncio.Semaphore(5)

            async def fetch_page(number: int) -> list[dict[str, Any]]:
                async with gate:
                    data = await self._request(
                        "GET",
                        f"{OPEN_PREFIX}/practice/{gid}/challenges/",
                        params={"limit": 100, "page": number},
                    )
                if not isinstance(data, dict):
                    return []
                return [item for item in (data.get("items") or []) if isinstance(item, dict)]

            pages = await asyncio.gather(
                *(fetch_page(n) for n in range(2, total_page + 1)), return_exceptions=True
            )
            for chunk in pages:
                if isinstance(chunk, list):
                    raw_items.extend(chunk)
                else:
                    logger.warning("CTF2: page fetch failed for ground %s: %s", gid, chunk)
        expected = ground.get("challenge_count")
        if isinstance(expected, int) and expected > len(raw_items):
            logger.warning(
                "CTF2: ground %s listed %s of %s challenges",
                ground.get("name"), len(raw_items), expected,
            )
        out: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            tags = [t for t in [category, difficulty_label(item.get("difficulty"))] if t]
            if self.categories and not matches_categories(category, tags, self.categories):
                continue
            out.append(
                {
                    "id": str(item.get("id")),
                    "name": str(item.get("name") or item.get("title") or f"challenge-{item.get('id')}"),
                    "category": category or "misc",
                    "value": int(item.get("points") or item.get("score") or 0),
                    "description": str(item.get("description") or ""),
                    "tags": tags,
                    "difficulty": difficulty_label(item.get("difficulty")),
                    "solved": bool(item.get("is_solved") or item.get("solved")),
                    "has_container": bool(
                        item.get("has_container") or item.get("has_containers")
                    ),
                    "ground_id": gid,
                    "ground_name": str(ground.get("name") or ground.get("slug") or gid),
                }
            )
        self._ground_cache[gid] = (asyncio.get_running_loop().time(), out)
        return out

    async def fetch_challenge_stubs(self) -> list[dict[str, Any]]:
        return await self.fetch_all_challenges(enrich=False)

    async def fetch_all_challenges(
        self, enrich: bool = True, force: bool = False
    ) -> list[dict[str, Any]]:
        all_challenges: list[dict[str, Any]] = []
        for ground in self._matching_grounds(await self.grounds()):
            try:
                all_challenges.extend(await self._ground_challenges(ground, force=force))
            except Ctf2Error as exc:
                logger.warning("CTF2: ground %s list failed: %s", ground.get("name"), exc)
        lowered = tuple(d.lower() for d in self.difficulties)
        if lowered:
            all_challenges = [
                ch for ch in all_challenges if ch.get("difficulty", "").lower() in lowered
            ]
        if enrich:
            for index, ch in enumerate(all_challenges):
                # The list endpoint already carries category/difficulty/points;
                # only pay for a detail call when the score is missing.
                if ch.get("value"):
                    continue
                if index:
                    await asyncio.sleep(DETAIL_PAUSE_S)
                try:
                    detail = await self._detail(ch["ground_id"], ch["id"])
                except Ctf2Error as exc:
                    logger.warning("CTF2: detail for %s failed: %s", ch["name"], exc)
                    continue
                ch["value"] = int(detail.get("points") or detail.get("score") or ch["value"] or 0)
                ch["description"] = str(detail.get("description") or ch.get("description") or "")
        self._challenges = all_challenges
        self._by_name = {str(c["name"]): c for c in all_challenges}
        logger.info(
            "CTF2: %s challenges from %s ground(s) — %s solved",
            len(all_challenges),
            len(await self.grounds()),
            sum(1 for c in all_challenges if c.get("solved")),
        )
        return all_challenges

    async def fetch_solved_names(self) -> set[str]:
        if not self._challenges:
            await self.fetch_all_challenges(enrich=False)
        return {str(c["name"]) for c in self._challenges if c.get("solved")}

    async def _detail(self, ground_id: str, challenge_id: str) -> dict[str, Any]:
        key = (str(ground_id), str(challenge_id))
        if key not in self._details:
            data = await self._request(
                "GET", f"{OPEN_PREFIX}/practice/{ground_id}/challenges/{challenge_id}/"
            )
            self._details[key] = data if isinstance(data, dict) else {}
        return self._details[key]

    def _entry(self, challenge_name: str) -> dict[str, Any]:
        entry = self._by_name.get(challenge_name)
        if entry is None:
            for name, item in self._by_name.items():
                if name.lower() == challenge_name.lower():
                    return item
            raise Ctf2Error(f"CTF²: unknown challenge {challenge_name!r}")
        return entry

    # --------------------------------------------------------------- files
    async def _file_url(self, ground_id: str, challenge_id: str, file_id: str) -> str:
        data = await self._request(
            "GET",
            f"{OPEN_PREFIX}/practice/{ground_id}/challenges/{challenge_id}/files/{file_id}/download/",
        )
        if isinstance(data, dict):
            for key in ("url", "download_url", "signed_url"):
                if data.get(key):
                    return str(data[key])
        if isinstance(data, str):
            return data
        raise Ctf2Error("CTF²: download endpoint returned no URL")

    async def _download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        client = await self._ensure_client()
        try:
            async with client.stream("GET", url, timeout=DOWNLOAD_TIMEOUT_S) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    async for chunk in resp.aiter_bytes(1 << 20):
                        fh.write(chunk)
            logger.info("CTF2: downloaded %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
        except Exception as exc:  # noqa: BLE001 - never fail the whole pull on one file
            logger.warning("CTF2: download %s failed: %s", url, exc)
            if dest.exists() and dest.stat().st_size == 0:
                dest.unlink(missing_ok=True)

    # ----------------------------------------------------------- env
    async def env_state(self, challenge_name: str) -> dict[str, Any]:
        entry = self._entry(challenge_name)
        data = await self._request(
            "GET",
            f"{OPEN_PREFIX}/practice/{entry['ground_id']}/challenges/{entry['id']}/environment/",
        )
        return data if isinstance(data, dict) else {}

    async def ensure_env(self, challenge_name: str) -> str:
        """Start (or reuse) the target environment and return connection info."""
        entry = self._entry(challenge_name)
        state = await self.env_state(challenge_name)
        started = bool(state.get("access_ready"))
        if not state.get("access_ready"):
            try:
                await self._request(
                    "POST",
                    f"{OPEN_PREFIX}/practice/{entry['ground_id']}/challenges/{entry['id']}/environment/start/",
                    payload={},
                )
                started = True
            except Ctf2Error as exc:
                if _is_env_limit(exc):
                    # A target from an earlier run may still hold the quota.
                    # Close the ones we know about, then retry once.
                    freed = await self.close_stale_envs(exclude={challenge_name})
                    if freed:
                        try:
                            await self._request(
                                "POST",
                                f"{OPEN_PREFIX}/practice/{entry['ground_id']}/challenges/{entry['id']}/environment/start/",
                                payload={},
                            )
                            started = True
                        except Ctf2Error as retry_exc:
                            if not _is_env_limit(retry_exc):
                                logger.warning(
                                    "CTF2: environment start for %s: %s", challenge_name, retry_exc
                                )
                            exc = retry_exc
                    if not started:
                        # The agent may hold only `max_environments` targets at
                        # a time. Fail fast so the round slot is freed instead
                        # of polling for three minutes for a box never coming.
                        raise Ctf2Error(
                            f"CTF² environment limit reached ({challenge_name}): "
                            "close a running target first",
                            status=exc.status,
                            code=exc.code,
                        ) from exc
                else:
                    logger.warning("CTF2: environment start for %s: %s", challenge_name, exc)
                    return ""
        deadline = asyncio.get_running_loop().time() + ENV_WAIT_TIMEOUT_S
        while started and asyncio.get_running_loop().time() < deadline:
            state = await self.env_state(challenge_name)
            if state.get("access_ready") and state.get("access_url"):
                break
            await asyncio.sleep(ENV_POLL_INTERVAL_S)
        if state.get("access_ready"):
            from backend import targetenv

            targetenv.register(
                challenge_name,
                ground_id=str(entry.get("ground_id") or ""),
                challenge_id=str(entry.get("id") or ""),
                access_url=str(state.get("access_url") or ""),
            )
        return self._connection_info(state)

    async def max_environments(self) -> int:
        """How many targets this agent may run at the same time (usually 1)."""
        try:
            me = await self.whoami()
        except Exception:  # noqa: BLE001 - quota is advisory
            return 1
        quotas = (me or {}).get("quotas") or {}
        try:
            return max(1, int(quotas.get("max_environments") or 1))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _connection_info(state: dict[str, Any]) -> str:
        lines: list[str] = []
        access_type = str(state.get("access_type") or "")
        if state.get("access_url"):
            tls = " (TLS)" if state.get("nc_ssl") else ""
            kind = f" [{access_type}]" if access_type else ""
            lines.append(f"target: {state['access_url']}{tls}{kind}")
        for item in state.get("access_urls") or []:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("access_url")
            kind = item.get("type") or item.get("name") or ""
            if not url:
                continue
            tls = " (TLS)" if item.get("nc_ssl") else ""
            lines.append(f"- {kind}: {url}{tls}".strip())
        if state.get("expires_at"):
            lines.append(f"expires: {state['expires_at']}")
        remaining = state.get("remaining_seconds")
        if remaining:
            lines.append(f"remaining: {remaining}s")
        return "\n".join(dict.fromkeys(lines))

    async def renew_env(self, challenge_name: str) -> bool:
        """Extend the running target's lifetime (POST .../environment/extend/)."""
        entry = self._entry(challenge_name)
        try:
            await self._request(
                "POST",
                f"{OPEN_PREFIX}/practice/{entry['ground_id']}/challenges/{entry['id']}/environment/extend/",
                payload={},
            )
            logger.debug("CTF2: renewed env for %s", challenge_name)
            return True
        except Ctf2Error as exc:
            logger.debug("CTF2: renew env for %s: %s", challenge_name, exc)
            return False

    async def stop_env(self, challenge_name: str) -> None:
        entry = self._entry(challenge_name)
        try:
            await self._request(
                "DELETE",
                f"{OPEN_PREFIX}/practice/{entry['ground_id']}/challenges/{entry['id']}/environment/",
            )
        except Ctf2Error as exc:
            logger.debug("CTF2: stop env for %s: %s", challenge_name, exc)
        finally:
            from backend import targetenv

            targetenv.unregister(challenge_name)

    async def stop_env_by_ids(
        self, ground_id: str, challenge_id: str, attempts: int = 3
    ) -> bool:
        """Close a target using ids straight from a metadata.yml file."""
        try:
            await self._request(
                "DELETE",
                f"{OPEN_PREFIX}/practice/{ground_id}/challenges/{challenge_id}/environment/",
                attempts=attempts,
            )
            return True
        except Ctf2Error as exc:
            logger.info("CTF2: stop env %s/%s: %s", ground_id, challenge_id, exc)
            return False

    async def reconcile_envs(self, keep: set[str] | None = None) -> int:
        """Close targets this agent registered earlier but no longer needs.

        Runs once per round: any env in ``logs/target-envs.json`` that is not in
        ``keep`` was left over from a crashed or finished run and still eats the
        platform's environment quota.
        """
        from backend import targetenv

        keep = {str(k).strip().lower() for k in (keep or set())}
        closed = 0
        for name, info in list(targetenv.owned().items()):
            if name.strip().lower() in keep:
                continue
            ground_id = str(info.get("ground_id") or "")
            challenge_id = str(info.get("challenge_id") or "")
            if not ground_id or not challenge_id:
                targetenv.unregister(name)
                continue
            try:
                ok = await asyncio.wait_for(
                    self.stop_env_by_ids(ground_id, challenge_id, attempts=1), timeout=30
                )
            except (TimeoutError, Exception):  # noqa: BLE001 - best effort
                ok = False
            targetenv.unregister(name)
            if ok:
                closed += 1
        if closed:
            logger.info("CTF2: reconciled %s leftover target env(s)", closed)
        return closed

    async def stop_all_envs(self) -> int:
        """Close every registered CTF² target (used on any exit path)."""
        return await self.reconcile_envs(set())

    async def close_stale_envs(self, exclude: set[str] | None = None) -> int:
        """Close targets left behind by earlier runs (frees the env quota).

        Walks ``challenges/*/metadata.yml`` for the ids stored while pulling;
        ``exclude`` holds challenge names that must keep their target.
        """
        root = Path("challenges")
        if not root.exists():
            return 0
        # Nothing is running -> every DELETE would only burn quota with 429s.
        try:
            me = await self.whoami()
            if not ((me or {}).get("quotas") or {}).get("active_environments"):
                return 0
        except Ctf2Error as exc:
            logger.debug("CTF2: cannot check active envs: %s", exc)
        skip = {name.strip().lower() for name in (exclude or set())}
        freed = 0
        candidates = sorted(root.glob("*/metadata.yml"), key=lambda p: p.stat().st_mtime, reverse=True)
        for meta_path in candidates[:8]:
            try:
                with open(meta_path, encoding="utf-8") as fh:
                    meta = yaml.safe_load(fh) or {}
            except Exception:  # noqa: BLE001 - best effort
                continue
            name = str(meta.get("name") or "").strip().lower()
            if name in skip:
                continue
            ground_id = str(meta.get("ctf2_ground_id") or "")
            challenge_id = str(meta.get("ctf2_challenge_id") or "")
            if not ground_id or not challenge_id:
                continue
            try:
                ok = await asyncio.wait_for(
                    self.stop_env_by_ids(ground_id, challenge_id, attempts=1), timeout=12
                )
            except (TimeoutError, Exception):  # noqa: BLE001 - best effort
                ok = False
            if ok:
                freed += 1
        if freed:
            logger.info("CTF2: closed %s stale target env(s)", freed)
        return freed

    # ------------------------------------------------------------ submit
    async def submit_flag(self, challenge_name: str, flag: str) -> SubmitResult:
        entry = self._entry(challenge_name)
        if entry.get("solved"):
            return SubmitResult(
                status="already_solved",
                message=f"{challenge_name} is already solved on CTF².",
                display=f"ALREADY SOLVED — {challenge_name} was solved before.",
            )
        text = str(flag).strip()
        if not text or len(text) > 4096:
            return SubmitResult(
                status="incorrect",
                message="flag must be 1..4096 characters.",
                display="INCORRECT — flag rejected locally (length must be 1..4096).",
            )
        from backend import pauses, submissions

        if pauses.is_paused(challenge_name):
            return SubmitResult(
                status="unknown",
                message="challenge is paused (out of submission attempts)",
                display=f"PAUSED — {challenge_name} ran out of attempts on CTF²; not submitting.",
            )

        scope = self._submission_scope()
        previous = submissions.previous(scope, challenge_name, text)
        if previous:
            stored = previous["status"]
            if stored == "correct":
                return SubmitResult(
                    status="already_solved",
                    message=previous.get("message") or "already accepted",
                    display=f"ALREADY SUBMITTED — {challenge_name} accepted this exact flag earlier.",
                )
            return SubmitResult(
                status="incorrect",
                message=previous.get("message") or "rejected earlier",
                display=(
                    f"INCORRECT — this exact flag was already rejected on CTF² "
                    f"({(previous.get('message') or 'no detail')[:120]}); not resubmitted."
                ),
            )
        if not submissions.reserve(scope, challenge_name, text):
            return SubmitResult(
                status="unknown",
                message="another solver is submitting this flag",
                display="SKIPPED — the same flag is being submitted by another solver.",
            )

        async with self._submit_lock:
            now = asyncio.get_running_loop().time()
            wait = 3.0 - (now - self._last_submit_at)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                data = await self._request(
                    "POST",
                    f"{OPEN_PREFIX}/practice/{entry['ground_id']}/challenges/{entry['id']}/submit/",
                    payload={"flag": text, "confirmation": True},
                )
            except Ctf2Error as exc:
                message = str(exc.message or exc)
                submissions.record(scope, challenge_name, text, "unknown", message)
                if "max_attempts" in message or "40409" in str(exc.code or ""):
                    pauses.pause(challenge_name, "submission attempts exhausted")
                    return SubmitResult(
                        status="unknown",
                        message=message,
                        display=(
                            f"PAUSED — {challenge_name} has no attempts left on CTF²; "
                            "this challenge will be skipped from now on."
                        ),
                    )
                raise
            self._last_submit_at = asyncio.get_running_loop().time()
        data = data if isinstance(data, dict) else {}
        message = str(data.get("message") or data.get("detail") or "")
        accepted = data.get("accepted")
        points = data.get("earned_points")
        if accepted:
            entry["solved"] = True
            submissions.record(scope, challenge_name, text, "correct", message or f"+{points}")
            return SubmitResult(
                status="correct",
                message=message or f"accepted (+{points} pts)",
                display=f"CORRECT — {challenge_name} solved on CTF²"
                + (f" (+{points} pts)." if points else "."),
            )
        if data.get("is_solved"):
            entry["solved"] = True
            submissions.record(scope, challenge_name, text, "correct", message or "already solved")
            return SubmitResult(
                status="already_solved",
                message=message or "already solved",
                display=f"ALREADY SOLVED — {challenge_name} is solved on CTF².",
            )
        attempts_left = data.get("attempts_left")
        submissions.record(scope, challenge_name, text, "incorrect", message or "flag not accepted")
        suffix = f" ({attempts_left} attempts left)" if attempts_left is not None else ""
        return SubmitResult(
            status="unknown",
            message=message or "flag not accepted",
            display=f"INCORRECT — CTF² rejected the flag{suffix}.",
        )

    # -------------------------------------------------------------- pull
    async def pull_challenge(self, challenge: dict[str, Any], output_dir: str) -> str:
        """Create ``challenges/<slug>`` with attachments, target and metadata."""
        import yaml

        name = str(challenge.get("name") or f"challenge-{challenge.get('id')}")
        ground_id = str(challenge.get("ground_id") or "")
        if not ground_id:
            ground = await self._ground_by_name(self.ground) if self.ground else None
            if ground is None:
                raise Ctf2Error(f"CTF²: no ground id for {name!r}")
            ground_id = str(ground.get("id"))

        ch_dir = Path(output_dir) / slugify(name)
        dist_dir = ch_dir / "distfiles"
        dist_dir.mkdir(parents=True, exist_ok=True)

        detail = await self._detail(ground_id, str(challenge["id"]))
        await self._download_detail_files(ground_id, str(challenge["id"]), detail, dist_dir)

        description = str(detail.get("description") or challenge.get("description") or "")
        for url in URL_RE.findall(description):
            fname = Path(url.split("?")[0].split("/")[-1]).name
            if "." not in fname:
                continue
            dest = dist_dir / fname
            if dest.exists() and dest.stat().st_size > 0:
                continue
            await self._download(url, dest)

        connection_info = ""
        if detail.get("has_container") or challenge.get("has_container"):
            connection_info = await self.ensure_env(name)

        meta = {
            "name": name,
            "category": str(detail.get("category") or challenge.get("category") or "misc"),
            "description": description.strip(),
            "value": int(detail.get("points") or detail.get("score") or challenge.get("value") or 0),
            "difficulty": difficulty_label(detail.get("difficulty") or challenge.get("difficulty")),
            "connection_info": connection_info,
            "tags": [
                t
                for t in [
                    str(detail.get("category") or challenge.get("category") or ""),
                    difficulty_label(detail.get("difficulty") or challenge.get("difficulty")),
                ]
                if t
            ],
            "solves": int(challenge.get("solves") or 0),
            "ctf2_ground_id": ground_id,
            "ctf2_challenge_id": str(challenge["id"]),
        }
        (ch_dir / "metadata.yml").write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
        logger.info("CTF2: pulled %s -> %s", name, ch_dir)
        return str(ch_dir)

    async def _download_detail_files(
        self,
        ground_id: str,
        challenge_id: str,
        detail: dict[str, Any],
        dist_dir: Path,
    ) -> None:
        for item in detail.get("files") or []:
            if not isinstance(item, dict):
                continue
            file_id = item.get("id")
            meta = item.get("file") if isinstance(item.get("file"), dict) else {}
            fname = Path(
                str(
                    item.get("name")
                    or meta.get("original_name")
                    or meta.get("filename")
                    or f"file-{file_id}"
                )
            ).name
            dest = dist_dir / fname
            if dest.exists() and dest.stat().st_size > 0:
                continue
            if not file_id:
                url = item.get("url")
                if url:
                    await self._download(str(url), dest)
                continue
            try:
                url = await self._file_url(ground_id, challenge_id, str(file_id))
                await self._download(url, dest)
            except Ctf2Error as exc:
                logger.warning("CTF2: attachment %s failed: %s", fname, exc)

    async def close(self) -> None:
        await aclose(self._client)
        self._client = None
