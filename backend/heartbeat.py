"""Keep live challenge targets alive for the whole solve.

Two platforms expire the container under us (`ret2shell` has ``expireTime``,
CTF+ has ``rest_time``), so a 40-minute solve would lose its target halfway.
This heartbeat renews every target that is currently being solved, and every
platform client exposes it as ``renew_env(challenge_name)``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# challenge name -> epoch when it was registered
_active: dict[str, float] = {}


def track(name: str) -> None:
    if name:
        _active[name] = time.time()


def untrack(name: str) -> None:
    _active.pop(name, None)


def active_names() -> list[str]:
    return list(_active)


def clear() -> None:
    _active.clear()


class EnvHeartbeat:
    """Periodically renew the targets of the challenges currently running."""

    def __init__(self, platform: Any | None, interval: float = 300.0) -> None:
        self.platform = platform
        self.interval = max(30.0, float(interval or 0))
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is not None or self.platform is None:
            return
        if not hasattr(self.platform, "renew_env"):
            logger.debug("heartbeat: %s has no renew_env()", type(self.platform).__name__)
            return
        self._task = asyncio.create_task(self._loop(), name="env-heartbeat")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                logger.debug("suppressed exception in stop", exc_info=True)
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
                return  # stop requested
            except TimeoutError:
                logger.debug("suppressed exception", exc_info=True)
            await self.beat()

    async def beat(self) -> int:
        renewed = 0
        for name in active_names():
            try:
                ok = await self.platform.renew_env(name)
            except Exception as exc:  # noqa: BLE001 - never kill a solve
                logger.debug("heartbeat: renew %s failed: %s", name, exc)
                continue
            if ok:
                renewed += 1
                logger.debug("heartbeat: renewed %s", name)
        return renewed
