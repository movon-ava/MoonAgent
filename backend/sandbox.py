"""Docker sandbox for CTF challenge solving — native async via aiodocker."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import re
import shlex
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import aiodocker

logger = logging.getLogger(__name__)

CONTAINER_LABEL = "ctf-agent"

# Containers started by a live ctf-solve process. Orphan cleanup must never
# touch these: deleting another run's container makes every tool call in that
# run fail with 404 and forces a full package reinstall in the sandbox.
_LIVE_REGISTRY = Path("logs") / "live-sandboxes.json"
_REGISTRY_TTL_S = 12 * 3600.0
_registry_lock = asyncio.Lock()

# Concurrency control
_start_semaphore: asyncio.Semaphore | None = None
_active_count: int = 0
_count_lock = asyncio.Lock()

_WARN_THRESHOLDS = {100, 200, 500}


def _read_registry() -> dict[str, dict[str, float]]:
    try:
        data = json.loads(_LIVE_REGISTRY.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception:
        return {}


def _write_registry(data: dict[str, dict[str, float]]) -> None:
    try:
        _LIVE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
        tmp = _LIVE_REGISTRY.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(_LIVE_REGISTRY)
    except Exception as e:
        logger.debug("Could not update live sandbox registry: %s", e)


def _register_container(container_id: str) -> None:
    data = _read_registry()
    data[container_id] = {"started": time.time(), "pid": float(os.getpid())}
    _write_registry(data)


def _unregister_container(container_id: str) -> None:
    data = _read_registry()
    if container_id in data:
        data.pop(container_id, None)
        _write_registry(data)


def _live_container_ids() -> set[str]:
    """Container ids started by a run that is still alive (and not too old)."""
    now = time.time()
    data = _read_registry()
    live: set[str] = set()
    changed = False
    for cid, meta in list(data.items()):
        started = float(meta.get("started", 0) or 0)
        if now - started > _REGISTRY_TTL_S:
            data.pop(cid, None)
            changed = True
            continue
        live.add(cid)
    if changed:
        _write_registry(data)
    return live


def configure_semaphore(max_concurrent: int = 50) -> None:
    """Set the max concurrent container starts. Call once at startup."""
    global _start_semaphore
    _start_semaphore = asyncio.Semaphore(max_concurrent)


async def _track_start() -> None:
    global _active_count
    async with _count_lock:
        _active_count += 1
        if _active_count in _WARN_THRESHOLDS:
            logger.warning("Active containers: %d", _active_count)


async def _track_stop() -> None:
    global _active_count
    async with _count_lock:
        _active_count = max(0, _active_count - 1)


def _makedirs_workspace() -> str:
    """Create a per-challenge workspace on the configured (large) drive.

    Extracted attachments can be several GB (memory dumps, disk images), so the
    default lives next to the project instead of on the system drive:
    ``F:\\ctf_agent\\workspaces``. Override with ``CTF_WORKSPACE_ROOT``.
    """
    root = os.environ.get("CTF_WORKSPACE_ROOT", r"F:\ctf_agent\workspaces")
    try:
        Path(root).mkdir(parents=True, exist_ok=True)
        return tempfile.mkdtemp(prefix="ctf-workspace-", dir=root)
    except Exception:
        return tempfile.mkdtemp(prefix="ctf-workspace-")


async def cleanup_orphan_containers(min_age_seconds: float = 3600.0, force: bool = False) -> None:
    """Kill leftover ctf-agent containers from a previous run.

    Containers started by a live run are protected by a registry file
    (``logs/live-sandboxes.json``); only containers older than
    ``min_age_seconds`` *and* not registered are removed. Deleting another
    run's container makes every tool call in that run fail with
    ``404 No such container`` and forces a full package reinstall.

    ``force=True`` removes every container with our label, registry included.
    The dashboard uses it after killing a run: the solver processes are gone,
    so their containers can only be leftovers.
    """
    try:
        docker = aiodocker.Docker()
        try:
            containers = await docker.containers.list(
                all=True,
                filters={"label": [CONTAINER_LABEL]},
            )
            removed = 0
            live = _live_container_ids()
            for c in containers:
                try:
                    info = await c.show()
                except Exception:
                    continue
                if info.get("Id") in live and not force:
                    continue  # a running ctf-solve owns it
                age = _container_age_seconds(info.get("Created"))
                if not force and age is not None and age < min_age_seconds:
                    continue
                try:
                    await c.delete(force=True)
                    removed += 1
                except Exception:
                    logger.debug("suppressed exception in cleanup_orphan_containers", exc_info=True)
            if removed:
                logger.info("Cleaned up %d orphan container(s)", removed)
        finally:
            await docker.close()
    except Exception as e:
        logger.warning("Orphan cleanup failed: %s", e)


def _is_missing_container(exc: Exception) -> bool:
    """True when a Docker error means the container no longer exists."""
    status = getattr(exc, "status", None)
    message = str(getattr(exc, "message", "") or exc)
    return status == 404 or "No such container" in message or "404 Not Found" in message


def _container_age_seconds(created: str | None) -> float | None:
    """Age of a Docker ``Created`` timestamp in seconds (None if unparsable)."""
    if not created:
        return None
    text = created.strip()
    # Docker emits nanosecond precision; fromisoformat accepts microseconds only.
    text = re.sub(r"\.(\d{6})\d+", r".\1", text)
    try:
        return time.time() - datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str


@dataclass
class DockerSandbox:
    """Isolated Docker container for a single solver agent."""

    image: str
    challenge_dir: str
    memory_limit: str = "16g"
    workspace_dir: str = ""
    _container: Any = field(default=None, repr=False)
    _docker: Any = field(default=None, repr=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def container_id(self) -> str:
        """The Docker container ID, available after start()."""
        if not self._container:
            raise RuntimeError("Sandbox not started")
        return self._container.id

    def _parse_memory_limit(self) -> int:
        s = self.memory_limit.strip().lower()
        try:
            if s.endswith("g"):
                return int(s[:-1]) * 1024 * 1024 * 1024
            if s.endswith("m"):
                return int(s[:-1]) * 1024 * 1024
            return int(s)
        except (ValueError, IndexError):
            logger.warning("Invalid memory_limit %r, defaulting to 4GB", self.memory_limit)
            return 4 * 1024 * 1024 * 1024

    async def start(self) -> None:
        sem = _start_semaphore or asyncio.Semaphore(50)
        async with sem:
            self._docker = aiodocker.Docker()
            self.workspace_dir = _makedirs_workspace()
            await self._start_container()

    async def _start_container(self) -> None:
        """Create and start the challenge container (also used for recovery)."""
        if self._docker is None:
            raise RuntimeError("Sandbox not started")
        if not self.workspace_dir:
            self.workspace_dir = _makedirs_workspace()

        challenge_root = Path(self.challenge_dir).resolve()
        distfiles = str(challenge_root / "distfiles")
        meta_yml = str(challenge_root / "metadata.yml")

        binds: list[str] = [f"{self.workspace_dir}:/challenge/workspace:rw"]
        if Path(distfiles).exists():
            binds.append(f"{distfiles}:/challenge/distfiles:ro")
        if Path(meta_yml).exists():
            binds.append(f"{meta_yml}:/challenge/metadata.yml:ro")

        host_config: dict[str, Any] = {
            "Binds": binds,
            "ExtraHosts": ["host.docker.internal:host-gateway"],
            "CapAdd": ["SYS_ADMIN", "SYS_PTRACE"],
            "SecurityOpt": ["seccomp=unconfined"],
            "Memory": self._parse_memory_limit(),
            "NanoCpus": int(2 * 1e9),
        }

        # Docker Desktop's WSL2 VM has no /dev/loop-control, and mapping a
        # device that does not exist makes container creation fail. Only map
        # it when the host really exposes it (native Linux with loop module).
        loop_device = "/dev/loop-control"
        if Path(loop_device).exists():
            host_config["Devices"] = [
                {
                    "PathOnHost": loop_device,
                    "PathInContainer": loop_device,
                    "CgroupPermissions": "rwm",
                }
            ]

        config = {
            "Image": self.image,
            "Cmd": ["sleep", "infinity"],
            "WorkingDir": "/challenge",
            "Tty": False,
            "Labels": {CONTAINER_LABEL: "true"},
            "HostConfig": host_config,
        }

        self._container = await self._docker.containers.create(config)
        await self._container.start()
        await _track_start()
        _register_container(self._container.id)

        info = await self._container.show()
        short_id = info["Id"][:12]
        logger.info("Sandbox started: %s", short_id)

    async def _recover_container(self) -> bool:
        """Recreate the container after it disappeared (docker rm, engine reset).

        The workspace/distfiles binds are still on the host, so a fresh
        container sees the same files again. Without this the solver keeps
        retrying against a dead container id and burns its whole step budget.
        """
        logger.warning("Sandbox container is gone — recreating it")
        try:
            if self._container is not None:
                _unregister_container(self._container.id)
        except Exception:
            logger.debug("suppressed exception in _recover_container", exc_info=True)
        try:
            await _track_stop()  # the dead container is still counted as active
        except Exception:
            logger.debug("suppressed exception in _recover_container", exc_info=True)
        try:
            await self._start_container()
            return True
        except Exception as e:
            logger.error("Sandbox recovery failed: %s", e)
            return False

    async def exec(self, command: str, timeout_s: int = 300) -> ExecResult:
        if not self._container:
            raise RuntimeError("Sandbox not started")

        async with self._lock:
            try:
                return await self._exec_inner(command, timeout_s)
            except aiodocker.exceptions.DockerError as e:
                # Container was deleted (e.g., sibling solver found the flag,
                # or docker rm from another process). Recreate it once and
                # retry so the solver does not spin on a dead container id.
                if _is_missing_container(e) and await self._recover_container():
                    try:
                        return await self._exec_inner(command, timeout_s)
                    except aiodocker.exceptions.DockerError as retry_error:
                        return ExecResult(
                            exit_code=-1, stdout="", stderr=f"Container gone: {retry_error}"
                        )
                return ExecResult(exit_code=-1, stdout="", stderr=f"Container gone: {e}")

    async def _exec_inner(self, command: str, timeout_s: int) -> ExecResult:
        # Wrap command with `timeout` so the container kills the process on expiry.
        # --signal=KILL ensures hard kill; --kill-after=5 is a safety net.
        wrapped = f"timeout --signal=KILL --kill-after=5 {timeout_s} bash -c {shlex.quote(command)}"
        exec_instance = await self._container.exec(
            cmd=["bash", "-c", wrapped],
            stdout=True,
            stderr=True,
            tty=False,
        )

        stream = exec_instance.start(detach=False)
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        async def _collect() -> None:
            while True:
                msg = await stream.read_out()
                if msg is None:
                    break
                if msg.stream == 1:
                    stdout_chunks.append(msg.data)
                else:
                    stderr_chunks.append(msg.data)

        try:
            # Give extra margin beyond the container-side timeout
            await asyncio.wait_for(_collect(), timeout=timeout_s + 30)
        except TimeoutError:
            try:
                await stream.close()
            except Exception:
                logger.debug("suppressed exception in _collect", exc_info=True)
            return ExecResult(
                exit_code=-1,
                stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
                stderr="Command timed out",
            )

        inspect = await exec_instance.inspect()
        exit_code = inspect.get("ExitCode", 0)

        return ExecResult(
            exit_code=exit_code,
            stdout=b"".join(stdout_chunks).decode("utf-8", errors="replace"),
            stderr=b"".join(stderr_chunks).decode("utf-8", errors="replace"),
        )

    async def read_file(self, path: str) -> str | bytes:
        """Read a file from the container. Returns str for text, bytes for binary."""
        if not self._container:
            raise RuntimeError("Sandbox not started")

        try:
            tar = await asyncio.wait_for(
                self._container.get_archive(path),
                timeout=30,
            )
        except aiodocker.exceptions.DockerError as e:
            if not (_is_missing_container(e) and await self._recover_container()):
                raise
            tar = await asyncio.wait_for(
                self._container.get_archive(path),
                timeout=30,
            )
        except TimeoutError as e:
            raise TimeoutError(f"Timed out reading {path}") from e

        # aiodocker 0.26.0 returns tarfile.TarFile directly
        with tar:
            for member in tar:
                if member.isfile():
                    f = tar.extractfile(member)
                    if f:
                        data = f.read()
                        try:
                            return data.decode("utf-8")
                        except UnicodeDecodeError:
                            return data
        raise FileNotFoundError(f"No file found at {path}")

    async def read_file_bytes(self, path: str) -> bytes:
        """Read a file from the container as raw bytes."""
        result = await self.read_file(path)
        if isinstance(result, str):
            return result.encode("utf-8")
        return result

    async def write_file(self, path: str, content: str | bytes) -> None:
        """Write a file into the container via tar archive."""
        if not self._container:
            raise RuntimeError("Sandbox not started")

        if isinstance(content, str):
            content = content.encode("utf-8")

        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=path.rsplit("/", 1)[-1])
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
        buf.seek(0)

        # Docker paths are POSIX; str(Path(...)) on Windows would send
        # "\challenge\workspace" and the engine answers 404 "Could not find
        # the file".
        parent = path.rsplit("/", 1)[0] or "/"

        try:
            await asyncio.wait_for(
                self._container.put_archive(parent, buf.getvalue()),
                timeout=30,
            )
        except aiodocker.exceptions.DockerError as e:
            if not (_is_missing_container(e) and await self._recover_container()):
                raise
            await asyncio.wait_for(
                self._container.put_archive(parent, buf.getvalue()),
                timeout=30,
            )
        except TimeoutError as e:
            raise TimeoutError(f"Timed out writing {path}") from e

    async def copy_from(self, container_path: str, host_path: str) -> None:
        """Copy a file from the container to the host."""
        data = await self.read_file_bytes(container_path)
        Path(host_path).parent.mkdir(parents=True, exist_ok=True)
        Path(host_path).write_bytes(data)

    async def stop(self) -> None:
        if self._container:
            try:
                _unregister_container(self._container.id)
            except Exception:
                logger.debug("suppressed exception in stop", exc_info=True)
            try:
                await self._container.delete(force=True)
            except Exception:
                logger.debug("suppressed exception in stop", exc_info=True)
            self._container = None
            await _track_stop()

        if self._docker:
            try:
                await self._docker.close()
            except Exception:
                logger.debug("suppressed exception in stop", exc_info=True)
            self._docker = None

        if self.workspace_dir:
            import shutil
            try:
                shutil.rmtree(self.workspace_dir, ignore_errors=True)
            except Exception:
                logger.debug("suppressed exception in stop", exc_info=True)
            self.workspace_dir = ""
        logger.info("Sandbox stopped")
