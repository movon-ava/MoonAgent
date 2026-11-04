"""Shared coordinator tool logic — called by both Claude SDK and Codex coordinators."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from backend.deps import CoordinatorDeps
from backend.prompts import ChallengeMeta
from backend.solver_base import FLAG_FOUND


_CONTAINER_CATEGORIES = ("web", "pwn", "二进制", "渗透")


def _is_container(meta: ChallengeMeta | None) -> bool:
    """True for challenges that need a live target (web / pwn / docker)."""
    if meta is None:
        return False
    if bool(getattr(meta, "has_container", False)):
        return True
    category = str(getattr(meta, "category", "") or "").lower()
    return any(key in category for key in _CONTAINER_CATEGORIES)


async def _container_flags(deps: CoordinatorDeps) -> dict[str, bool]:
    """challenge name -> needs a live target, straight from the platform list.

    Metadata files on disk can be stale (pulled before this field existed), so
    the network answer wins. Cached on the deps object.
    """
    if deps.container_flags:
        return deps.container_flags
    try:
        for ch in await deps.ctfd.fetch_all_challenges():
            deps.container_flags[str(ch.get("name"))] = bool(ch.get("has_container"))
    except Exception as exc:  # noqa: BLE001 - fall back to metadata
        logger.debug("container flag lookup failed: %s", exc)
    return deps.container_flags


def _write_connection_info(challenge_dir: str, name: str, info: str) -> None:
    """Persist the target info into metadata.yml so restarts reuse it."""
    import yaml

    path = Path(challenge_dir) / "metadata.yml"
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        data["connection_info"] = info
        with open(path, "w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)
    except Exception as exc:  # noqa: BLE001 - best effort
        logger.debug("could not write connection_info for %s: %s", name, exc)


logger = logging.getLogger(__name__)

# Keep background writeup tasks alive until they finish.
_WRITEUP_TASKS: set[asyncio.Task] = set()


async def do_fetch_challenges(deps: CoordinatorDeps) -> str:
    challenges = await deps.ctfd.fetch_all_challenges()
    solved = await deps.ctfd.fetch_solved_names()
    allow_solved = include_solved(deps)
    result = [
        {
            "name": ch.get("name", "?"),
            "category": ch.get("category", "?"),
            "value": ch.get("value", 0),
            "solves": ch.get("solves", 0),
            "status": "SOLVED" if ch.get("name") in solved else "unsolved",
            "spawnable": (allow_solved or ch.get("name") not in solved),
            "description": (ch.get("description") or "")[:200],
        }
        for ch in challenges
    ]
    payload = {"include_solved": allow_solved, "challenges": result}
    return json.dumps(payload, indent=2)


async def do_get_solve_status(deps: CoordinatorDeps) -> str:
    solved = await deps.ctfd.fetch_solved_names()
    swarm_status = {name: swarm.get_status() for name, swarm in deps.swarms.items()}
    return json.dumps({"solved": sorted(solved), "active_swarms": swarm_status}, indent=2)


def drill_enabled(deps: CoordinatorDeps) -> bool:
    """True when the round was started with --rotate (drill mode)."""
    return bool(getattr(getattr(deps, "settings", None), "round_rotate", False))


def include_solved(deps: CoordinatorDeps) -> bool:
    """True when the run was started with --include-solved."""
    return bool(getattr(getattr(deps, "settings", None), "round_include_solved", False))


def _spawnable(deps: CoordinatorDeps, challenges: list[dict]) -> list[dict]:
    """Challenges the coordinator may still spawn."""
    allow_solved = include_solved(deps)
    running = set(deps.swarms)
    return [
        c
        for c in challenges
        if (allow_solved or not c.get("solved"))
        and str(c.get("name") or "") not in running
        and str(c.get("name") or "") not in deps.results
    ]


def _drill_advance(deps: CoordinatorDeps) -> None:
    deps.drill_index += 1
    if deps.drill_index < len(deps.drill_chunks):
        deps.drill_batch = list(deps.drill_chunks[deps.drill_index])
        deps.drill_category = deps.drill_cats[deps.drill_index]
    else:
        deps.drill_batch = []
        deps.drill_category = ""
        deps.drill_chunks = []
        deps.drill_cats = []


async def _drill_load(deps: CoordinatorDeps) -> str | None:
    """Build the direction batches on first use; returns an error string or None."""
    if deps.drill_chunks:
        return None
    from backend.selector import rotate_chunks

    try:
        challenges = await deps.ctfd.fetch_all_challenges()
    except Exception as exc:  # noqa: BLE001
        return f"Could not list challenges: {exc}"
    available = _spawnable(deps, challenges)
    if not available:
        return (
            "Every remaining challenge is already solved - start the run with "
            "--include-solved to practice on them anyway."
            if not include_solved(deps)
            else "No challenges left to spawn."
        )

    settings = deps.settings
    size = int(getattr(settings, "rotate_batch", 0) or 0) or int(
        getattr(settings, "max_concurrent_challenges", 5) or 5
    )
    order = [
        part.strip()
        for part in str(getattr(settings, "challenge_categories", "")).split(",")
        if part.strip()
    ]
    chunks = rotate_chunks(available, size, order)
    deps.drill_chunks = [[str(c.get("name") or "") for c in chunk] for chunk in chunks]
    deps.drill_cats = [str(chunk[0].get("category") or "?") for chunk in chunks]
    deps.drill_index = 0
    deps.drill_batch = list(deps.drill_chunks[0])
    deps.drill_category = deps.drill_cats[0]
    deps.drill_active = True
    return None


async def drill_allow(deps: CoordinatorDeps, challenge_name: str) -> str | None:
    """Gate one spawn through the current direction batch.

    Returns None when the spawn is allowed (and consumes the slot), or a
    message telling the coordinator what it may spawn instead.
    """
    error = await _drill_load(deps)
    if error:
        return error
    if not deps.drill_batch:
        return "Drill mode: all batches are done - call spawn_batch to start over."
    if challenge_name not in deps.drill_batch:
        allowed = ", ".join(deps.drill_batch[:8])
        return (
            f"Drill mode: the current batch is {deps.drill_category} "
            f"({allowed}). Spawn one of those, or call spawn_batch for the next direction."
        )
    deps.drill_batch.remove(challenge_name)
    if not deps.drill_batch:
        _drill_advance(deps)
        if deps.drill_batch:
            return (
                f"Batch finished - next direction is "
                f"{deps.drill_category} ({', '.join(deps.drill_batch[:8])})."
            )
        return "Drill mode: all batches are done."
    return None


async def do_spawn_batch(deps: CoordinatorDeps, count: int = 5) -> str:
    """Spawn the next direction batch (drill mode), one category at a time."""
    count = max(1, int(count or 1))

    if drill_enabled(deps):
        error = await _drill_load(deps)
        if error:
            return error
        if not deps.drill_batch:
            return "Drill mode: all batches are done."
        names = list(deps.drill_batch)[:count]
        lines: list[str] = []
        for name in names:
            try:
                lines.append(f"{name}: {await do_spawn_swarm(deps, name)}")
            except Exception as exc:  # noqa: BLE001
                lines.append(f"{name}: failed ({exc})")
        header = (
            f"Batch {deps.drill_index + 1}/{len(deps.drill_chunks)} "
            f"({deps.drill_category}, {len(names)} challenge(s))"
        )
        return header + "\n" + "\n".join(lines)

    from backend.selector import rotate_chunks

    try:
        challenges = await deps.ctfd.fetch_all_challenges()
    except Exception as exc:  # noqa: BLE001 - report, do not crash the turn
        return f"Could not list challenges: {exc}"

    available = _spawnable(deps, challenges)
    if not available:
        return (
            "Every remaining challenge is already solved - start the run with "
            "--include-solved to practice on them anyway."
            if not include_solved(deps)
            else "No challenges left to spawn."
        )

    chunks = rotate_chunks(available, count)
    if not chunks:
        return "No unsolved challenges left to spawn."
    index = deps.rotate_cursor % len(chunks)
    batch = chunks[index]
    deps.rotate_cursor = index + 1

    lines = []
    for ch in batch:
        name = str(ch.get("name") or "")
        if not name:
            continue
        try:
            lines.append(f"{name}: {await do_spawn_swarm(deps, name)}")
        except Exception as exc:  # noqa: BLE001
            lines.append(f"{name}: failed ({exc})")
    cats = sorted({str(c.get("category") or "?") for c in batch})
    header = (
        f"Batch {index + 1}/{len(chunks)} ({'/'.join(cats)}, {len(batch)} challenge(s)); "
        f"call spawn_batch again for the next direction when this batch is done."
    )
    return header + "\n" + "\n".join(lines)


async def do_spawn_swarm(deps: CoordinatorDeps, challenge_name: str) -> str:
    if drill_enabled(deps):
        blocked = await drill_allow(deps, challenge_name)
        if blocked and not blocked.startswith("Batch finished"):
            return blocked
    # Retire ALL finished swarms before checking capacity
    finished = [
        name for name, swarm in deps.swarms.items()
        if swarm.cancel_event.is_set()
        or (name in deps.swarm_tasks and deps.swarm_tasks[name].done())
    ]
    for name in finished:
        del deps.swarms[name]
        deps.swarm_tasks.pop(name, None)

    active_count = len(deps.swarms)
    if active_count >= deps.max_concurrent_challenges:
        return f"At capacity ({active_count}/{deps.max_concurrent_challenges} challenges running). Wait for one to finish."

    if challenge_name in deps.swarms:
        return f"Swarm still running for {challenge_name}"

    extra_rounds = max(0, int(getattr(deps.settings, "challenge_extra_rounds", 0) or 0))
    tries = deps.attempt_counts.get(challenge_name, 0)
    if challenge_name in deps.attempted and challenge_name not in deps.swarms:
        if tries <= extra_rounds:
            # The operator allowed extra rounds: let this challenge run again.
            deps.attempted.discard(challenge_name)
            logger.info(
                "[%s] extra round %s/%s", challenge_name, tries, extra_rounds
            )
        else:
            return (
                f"{challenge_name} was already attempted in this run. Pick a different "
                "challenge (the goal is breadth: one pass over many challenges)."
            )

    # Decide whether this challenge needs the (scarce) target slot *before*
    # pulling: pulling a container challenge starts its instance, so a swarm
    # that later fails the capacity check would have already stolen the slot
    # from the challenge that is currently running.
    flags = await _container_flags(deps)
    holds_env = bool(flags.get(challenge_name)) or _is_container(
        deps.challenge_metas.get(challenge_name)
    )
    cap = 1
    acquired = False
    if holds_env:
        max_env = getattr(deps.ctfd, "max_environments", None)
        if callable(max_env):
            try:
                cap = int(await max_env()) or 1
            except Exception:  # noqa: BLE001 - quota probe must not abort
                cap = 1
        if deps.env_sem is None:
            deps.env_sem = asyncio.Semaphore(cap)
        if deps.env_sem.locked():
            return (
                f"Target capacity full ({cap} container challenge(s) running). "
                "Wait for one to finish before spawning another target challenge."
            )
        await deps.env_sem.acquire()
        acquired = True

    try:
        if challenge_name not in deps.challenge_dirs:
            challenges = await deps.ctfd.fetch_all_challenges()
            ch_data = next((c for c in challenges if c.get("name") == challenge_name), None)
            if not ch_data:
                return f"Challenge '{challenge_name}' not found on CTFd"
            output_dir = str(Path(deps.challenges_root))
            ch_dir = await deps.ctfd.pull_challenge(ch_data, output_dir)
            deps.challenge_dirs[challenge_name] = ch_dir
            deps.challenge_metas[challenge_name] = ChallengeMeta.from_yaml(
                Path(ch_dir) / "metadata.yml"
            )

        meta = deps.challenge_metas[challenge_name]
        holds_env = holds_env or _is_container(meta)
        if holds_env:
            ensure = getattr(deps.ctfd, "ensure_env", None)
            if callable(ensure):
                try:
                    info = await ensure(challenge_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("ensure_env failed for %s: %s", challenge_name, exc)
                    info = ""
                if info:
                    _write_connection_info(
                        deps.challenge_dirs[challenge_name], challenge_name, info
                    )
                    deps.challenge_metas[challenge_name] = ChallengeMeta.from_yaml(
                        Path(deps.challenge_dirs[challenge_name]) / "metadata.yml"
                    )
            if not str(
                getattr(deps.challenge_metas[challenge_name], "connection_info", "") or ""
            ).strip():
                return (
                    f"No target available for {challenge_name}: the platform instance or the "
                    "WSRX tunnel could not be created. Try again later."
                )
    finally:
        if acquired and deps.env_sem is not None:
            deps.env_sem.release()

    from backend.agents.swarm import ChallengeSwarm

    swarm = ChallengeSwarm(
        challenge_dir=deps.challenge_dirs[challenge_name],
        meta=deps.challenge_metas[challenge_name],
        ctfd=deps.ctfd,
        cost_tracker=deps.cost_tracker,
        settings=deps.settings,
        model_specs=deps.model_specs,
        no_submit=deps.no_submit,
        coordinator_inbox=deps.coordinator_inbox,
    )
    deps.swarms[challenge_name] = swarm
    acquired = False  # ownership moves to _run_and_cleanup

    async def _run_and_cleanup() -> None:
        result = None
        # Per-challenge wall-clock budget: without it a solver can grind on one
        # unsolvable challenge and burn tokens for the whole session.
        timeout_min = float(getattr(deps.settings, "challenge_timeout_min", 0) or 0)
        swarm_task = asyncio.create_task(swarm.run(), name=f"swarm-{challenge_name}")
        try:
            if timeout_min > 0:
                try:
                    result = await asyncio.wait_for(
                        asyncio.shield(swarm_task), timeout=timeout_min * 60
                    )
                except asyncio.TimeoutError:
                    swarm.cancel_event.set()
                    deps.results[challenge_name] = {"flag": None, "status": "timeout"}
                    logger.warning(
                        "[%s] timed out after %g min - stopping this swarm",
                        challenge_name,
                        timeout_min,
                    )
                    try:
                        await asyncio.wait_for(swarm_task, timeout=30)
                    except Exception:  # noqa: BLE001 - best effort unwind
                        swarm_task.cancel()
                        await asyncio.gather(swarm_task, return_exceptions=True)
                    # A cancelled solver can leave its sandbox behind. Remove
                    # containers that are not in the live registry (other
                    # challenges keep theirs).
                    try:
                        from backend.sandbox import cleanup_orphan_containers

                        await cleanup_orphan_containers(0)
                    except Exception:  # noqa: BLE001
                        pass
                    return
            else:
                result = await swarm_task
        finally:
            from backend import heartbeat

            heartbeat.untrack(challenge_name)
            # Destroy the platform target on every exit path (solved, gave up,
            # timeout, operator skip): containers must not outlive the challenge.
            if holds_env:
                stopper = getattr(deps.ctfd, "stop_env", None)
                if stopper is not None:
                    try:
                        await asyncio.wait_for(stopper(challenge_name), timeout=30)
                    except Exception as exc:  # noqa: BLE001 - best effort
                        logger.debug("stop_env(%s) failed: %s", challenge_name, exc)
            if holds_env and deps.env_sem is not None:
                deps.env_sem.release()
            # Flag already submitted/confirmed by solver's submit_fn — record it
            if result and result.status == FLAG_FOUND:
                deps.results[challenge_name] = {
                    "flag": result.flag,
                    "submit": "DRY RUN" if deps.no_submit else "confirmed by solver",
                }
                if getattr(deps.settings, "writeup_enabled", False):
                    from backend import writeup as _writeup

                    task = asyncio.create_task(
                        _writeup.write(
                            deps.settings,
                            deps.challenge_metas.get(challenge_name),
                            result,
                        )
                    )
                    _WRITEUP_TASKS.add(task)
                    task.add_done_callback(_WRITEUP_TASKS.discard)

    deps.attempted.add(challenge_name)
    deps.attempt_counts[challenge_name] = deps.attempt_counts.get(challenge_name, 0) + 1
    from backend import heartbeat

    heartbeat.track(challenge_name)
    task = asyncio.create_task(_run_and_cleanup(), name=f"swarm-{challenge_name}")
    deps.swarm_tasks[challenge_name] = task
    return f"Swarm spawned for {challenge_name} with {len(deps.model_specs)} models"


async def do_check_swarm_status(deps: CoordinatorDeps, challenge_name: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    return json.dumps(swarm.get_status(), indent=2)


async def do_submit_flag(deps: CoordinatorDeps, challenge_name: str, flag: str) -> str:
    if deps.no_submit:
        return f'DRY RUN — would submit "{flag.strip()}" for {challenge_name}'
    try:
        result = await deps.ctfd.submit_flag(challenge_name, flag)
        return result.display
    except Exception as e:
        return f"submit_flag error: {e}"


async def do_kill_swarm(deps: CoordinatorDeps, challenge_name: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    swarm.kill()
    return f"Swarm for {challenge_name} cancelled"


async def do_bump_agent(deps: CoordinatorDeps, challenge_name: str, model_spec: str, insights: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    solver = swarm.solvers.get(model_spec)
    if not solver:
        return f"No solver for {model_spec} in {challenge_name}"
    solver.bump(insights)
    return f"Bumped {model_spec} on {challenge_name}"


async def do_read_solver_trace(deps: CoordinatorDeps, challenge_name: str, model_spec: str, last_n: int = 20) -> str:
    """Read the last N trace events from a solver's JSONL log."""
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm for {challenge_name}"
    solver = swarm.solvers.get(model_spec)
    if not solver:
        return f"No solver for {model_spec}"
    trace_path = getattr(solver, "tracer", None)
    if not trace_path:
        return "No tracer on solver"
    path = trace_path.path if hasattr(trace_path, "path") else str(trace_path)
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").strip().split("\n")
        recent = lines[-last_n:]
        summary = []
        for line in recent:
            try:
                d = json.loads(line)
                t = d.get("type", "?")
                if t == "tool_call":
                    args_str = str(d.get("args", ""))[:100]
                    summary.append(f"step {d.get('step','?')} CALL {d.get('tool','?')}: {args_str}")
                elif t == "tool_result":
                    result_str = str(d.get("result", ""))[:100]
                    summary.append(f"step {d.get('step','?')} RESULT {d.get('tool','?')}: {result_str}")
                elif t in ("finish", "error", "bump", "turn_failed"):
                    summary.append(f"** {t}: {json.dumps({k:v for k,v in d.items() if k != 'ts'})}")
                elif t == "usage":
                    summary.append(f"usage: in={d.get('input_tokens',0)} out={d.get('output_tokens',0)} cost=${d.get('cost_usd',0):.4f}")
                else:
                    summary.append(f"{t}: {str(d)[:80]}")
            except Exception:
                summary.append(line[:100])
        return "\n".join(summary)
    except FileNotFoundError:
        return f"Trace file not found: {path}"
    except Exception as e:
        return f"Error reading trace: {e}"


async def do_broadcast(deps: CoordinatorDeps, challenge_name: str, message: str) -> str:
    """Broadcast a message to all solvers working on a challenge."""
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    await swarm.message_bus.broadcast(message)
    return f"Broadcast to all solvers on {challenge_name}"
