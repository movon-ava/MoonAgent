"""Shared HTTP plumbing for the platform adapters.

Each adapter used to carry its own copy of "lazy ``httpx.AsyncClient`` + retry
on 429/5xx + honour ``Retry-After`` + close".  Five copies of that logic meant
five places to fix a bug and five slightly different retry policies, so the
mechanics live here and the adapters keep only what is genuinely
platform-specific: headers, envelope shape and error mapping.

The functions take the ``httpx.AsyncClient`` as an argument (instead of owning
it) so adapters keep their ``_client`` attribute — the self-check scripts
inject a ``MockTransport`` client there.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
RETRY_NETWORK: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)


def double_json(payload: Any) -> str:
    """Serialise ``payload`` as a JSON string containing JSON (DASCTF quirk)."""
    return json.dumps(json.dumps(payload, ensure_ascii=False), ensure_ascii=False)


def retry_after(resp: httpx.Response, attempt: int, *, base: float, cap: float) -> float:
    """Seconds to wait before retrying ``resp``."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), cap)
        except ValueError:
            logger.debug("Retry-After is not numeric: %r", header)
    return min(base * attempt, cap)


def make_client(
    base_url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    read_timeout: float | None = None,
    follow_redirects: bool = True,
    trust_env: bool = True,
    verify: bool = True,
) -> httpx.AsyncClient:
    """Build the adapter's ``httpx.AsyncClient`` with the shared defaults."""
    limit: Any = httpx.Timeout(timeout, read=read_timeout) if read_timeout else timeout
    return httpx.AsyncClient(
        base_url=base_url.rstrip("/"),
        headers=dict(headers or {}),
        timeout=limit,
        follow_redirects=follow_redirects,
        trust_env=trust_env,
        verify=verify,
    )


@dataclass(frozen=True)
class Policy:
    """Retry + pacing knobs for one adapter."""

    name: str
    attempts: int = 3
    retry_statuses: frozenset[int] = RETRY_STATUSES
    backoff: float = 1.5
    retry_cap: float = 8.0
    # Minimum seconds between requests, enforced across processes through
    # backend.platformgate (0 disables pacing).
    pace: float = 0.0


async def send(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    policy: Policy,
    params: dict[str, Any] | None = None,
    json: Any = None,
    content: Any = None,
    data: Any = None,
    headers: Mapping[str, str] | None = None,
    attempts: int | None = None,
) -> httpx.Response:
    """Send one request, retrying transient failures the way every adapter wants.

    A retryable status on the *last* attempt is returned as-is, so callers keep
    their existing "inspect status code" logic.
    """
    total = max(1, attempts or policy.attempts)
    kwargs: dict[str, Any] = {}
    if params:
        kwargs["params"] = params
    if json is not None:
        kwargs["json"] = json
    if content is not None:
        kwargs["content"] = content
    if data is not None:
        kwargs["data"] = data
    if headers:
        kwargs["headers"] = dict(headers)

    for attempt in range(1, total + 1):
        if policy.pace:
            from backend import platformgate

            await platformgate.wait_turn(policy.pace)
        try:
            resp = await client.request(method, path, **kwargs)
        except RETRY_NETWORK as exc:
            if attempt >= total:
                raise
            logger.warning(
                "%s: %s %s failed (%s), retry %s/%s",
                policy.name,
                method,
                path,
                exc.__class__.__name__,
                attempt,
                total,
            )
            await asyncio.sleep(min(policy.backoff * attempt, policy.retry_cap))
            continue
        if resp.status_code in policy.retry_statuses and attempt < total:
            delay = retry_after(resp, attempt, base=policy.backoff, cap=policy.retry_cap)
            logger.warning(
                "%s: %s %s -> HTTP %s, retry %s/%s in %.1fs",
                policy.name,
                method,
                path,
                resp.status_code,
                attempt,
                total,
                delay,
            )
            await asyncio.sleep(delay)
            continue
        return resp

    raise RuntimeError(f"{policy.name}: {method} {path} failed after {total} attempts")


async def aclose(client: httpx.AsyncClient | None) -> None:
    """Close ``client`` if it exists (adapters' ``close()`` bodies)."""
    if client is not None:
        await client.aclose()
