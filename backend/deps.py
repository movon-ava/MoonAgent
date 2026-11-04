"""Shared dependency types — avoids circular imports between agents and tools."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.cost_tracker import CostTracker
from backend.ctfd import CTFdClient
from backend.sandbox import DockerSandbox

if TYPE_CHECKING:
    from backend.message_bus import ChallengeMessageBus

# Type for the deduped submit callback: (flag) -> (display, is_confirmed)
SubmitFn = Callable[[str], Coroutine[Any, Any, tuple[str, bool]]]


@dataclass
class SolverDeps:
    sandbox: DockerSandbox
    ctfd: CTFdClient
    challenge_dir: str
    challenge_name: str
    workspace_dir: str
    use_vision: bool
    cost_tracker: CostTracker | None = None
    connection_info: str = ""  # host:port of the challenge target, if any
    confirmed_flag: str | None = None
    message_bus: ChallengeMessageBus | None = None
    model_spec: str = ""
    submit_fn: SubmitFn | None = None  # Deduped flag submission via swarm
    no_submit: bool = False
    needs_target: bool = False  # web/pwn/docker: bash is blocked until an env exists
    # Practice run: the challenge is already solved on the platform, so the
    # flag cannot be verified; we still require the solver to derive one.
    practice_mode: bool = False
    notify_coordinator: Callable[[str], Coroutine[Any, Any, None]] | None = None


@dataclass
class CoordinatorDeps:
    ctfd: CTFdClient
    cost_tracker: CostTracker
    settings: Any
    model_specs: list[str] = field(default_factory=list)
    challenges_root: str = "challenges"
    no_submit: bool = False
    max_concurrent_challenges: int = 10

    msg_port: int = 0  # 0 = auto-pick free port

    # Runtime state
    coordinator_inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    operator_inbox: asyncio.Queue = field(default_factory=asyncio.Queue)
    swarms: dict[str, Any] = field(default_factory=dict)
    swarm_tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    results: dict[str, dict] = field(default_factory=dict)
    challenge_dirs: dict[str, str] = field(default_factory=dict)
    challenge_metas: dict[str, Any] = field(default_factory=dict)
    # Drill-mode cursor: which direction batch the coordinator should take next.
    rotate_cursor: int = 0
    # Serialises challenges that need a live target (platform quota is tiny).
    env_sem: asyncio.Semaphore | None = None
    # challenge name -> needs a live target (from the platform's challenge list).
    container_flags: dict[str, bool] = field(default_factory=dict)
    # Challenges already spawned during this run (avoid re-picking the same one).
    attempted: set[str] = field(default_factory=set)
    # Drill state: the current direction batch (names) and the remaining batches.
    drill_active: bool = False
    drill_batch: list[str] = field(default_factory=list)
    drill_category: str = ""
    drill_chunks: list[list[str]] = field(default_factory=list)
    drill_cats: list[str] = field(default_factory=list)
    drill_index: int = 0
