"""Round mode — pull N unsolved challenges, solve them, submit, then stop.

This is the fully-automatic path for competition platforms:

1. fetch the challenge list + solved status from the platform
   (CTFd or Ret2Shell),
2. pick ``round_size`` unsolved challenges — random by default, optionally
   cheapest-first or by name (``--order``), skipping ones attempted recently,
3. download each challenge's attachments and write ``metadata.yml``,
4. race the configured models on them (respecting ``--max-challenges``),
5. flags are submitted to the platform by the solvers themselves
   (``submit_flag`` tool → platform API),
6. print a summary and exit — no continuous coordinator loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import time
from pathlib import Path
from typing import Any

from rich.console import Console

from backend import runtime, snapshot
from backend.agents.swarm import ChallengeSwarm
from backend.concurrency import DynamicSemaphore
from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.platform import make_platform, platform_kind
from backend.prompts import ChallengeMeta
from backend.sandbox import cleanup_orphan_containers, configure_semaphore
from backend.solver_base import FLAG_FOUND

logger = logging.getLogger(__name__)
console = Console()


def _filter_pool(
    challenges: list[dict[str, Any]],
    solved: set[str],
    min_score: int = 1,
    only: tuple[str, ...] = (),
    include_solved: bool = False,
) -> list[dict[str, Any]]:
    """Challenges that pass the solved / score / name filters.

    ``min_score`` drops zero-value "participation" challenges (poster contests
    etc. that no solver can flag), ``only`` keeps names containing any needle,
    ``include_solved`` also lets already-solved challenges back into the pool.
    """
    if include_solved:
        candidates = list(challenges)
    else:
        candidates = [c for c in challenges if c.get("name") not in solved]
    pool = [c for c in candidates if int(c.get("value") or 0) >= min_score]
    needles = [n.strip().lower() for n in only if n and n.strip()]
    if needles:
        pool = [c for c in pool if any(n in str(c.get("name") or "").lower() for n in needles)]
    return pool


def _wipe_challenge_dirs(challenges_dir: str) -> int:
    """Delete pulled challenge directories; returns how many were removed.

    Used by ``fresh_solve`` so an evaluation run cannot read a previous solve's
    scripts, notes or flag leftovers from the workspace.
    """
    base = Path(challenges_dir)
    if not base.exists():
        return 0
    wiped = 0
    for child in base.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
            wiped += 1
    return wiped


def _score_key(ch: dict[str, Any]) -> tuple[int, str]:
    return (int(ch.get("value") or 0), str(ch.get("name") or ""))


_DIFF_WEIGHT = {"困难": 4.0, "中等": 3.0, "简单": 2.0, "入门": 1.0}


def _difficulty_weight(ch: dict[str, Any]) -> float:
    return _DIFF_WEIGHT.get(str(ch.get("difficulty") or "").strip(), 1.5)


def _weighted_sample(pool: list[dict[str, Any]], k: int, rng: random.Random) -> list[dict[str, Any]]:
    """Sample ``k`` challenges without replacement, biased towards hard ones."""
    items = list(pool)
    weights = [_difficulty_weight(c) for c in items]
    out: list[dict[str, Any]] = []
    while items and len(out) < k:
        total = sum(weights)
        if total <= 0:
            out.extend(items[: k - len(out)])
            break
        point = rng.uniform(0.0, total)
        acc = 0.0
        for index, weight in enumerate(weights):
            acc += weight
            if point <= acc:
                out.append(items.pop(index))
                weights.pop(index)
                break
    return out


def _pick(pool: list[dict[str, Any]], k: int, order: str = "random") -> list[dict[str, Any]]:
    """Choose ``k`` challenges out of ``pool``.

    ``random`` (default) is **stratified**: it first takes one challenge from
    every difficulty tier and every category present in the pool, so a round
    always mixes 入门/简单/中等/困难 and web/pwn/misc/re/crypto instead of
    draining whichever bucket happens to come first. The remainder is filled
    with difficulty-weighted sampling.

    ``hard`` takes the hardest first, ``score`` the cheapest, ``name``
    alphabetically.
    """
    k = max(0, min(k, len(pool)))
    rng = random.SystemRandom()
    if order == "score":
        return sorted(pool, key=_score_key)[:k]
    if order == "name":
        return sorted(pool, key=lambda c: str(c.get("name") or ""))[:k]
    if k >= len(pool):
        chosen = list(pool)
        rng.shuffle(chosen)
        return chosen

    chosen: list[dict[str, Any]] = []
    used: set[int] = set()

    tier_count: dict[str, int] = {}

    def take(bucket: list[dict[str, Any]]) -> None:
        cand = [c for c in bucket if id(c) not in used]
        if not cand or len(chosen) >= k:
            return
        # Prefer the difficulty tier we have picked the least so far, so a
        # category that is mostly 简单 does not skew the round.
        groups: dict[str, list[dict[str, Any]]] = {}
        for c in cand:
            groups.setdefault(str(c.get("difficulty") or ""), []).append(c)
        floor = min(tier_count.get(t, 0) for t in groups)
        pool_tiers = [t for t in groups if tier_count.get(t, 0) == floor]
        tier = rng.choice(sorted(pool_tiers))
        pick = rng.choice(groups[tier])
        chosen.append(pick)
        used.add(id(pick))
        tier_count[tier] = tier_count.get(tier, 0) + 1

    # Categories first (fewer of them: web / pwn / misc / re / crypto), then
    # difficulty tiers, then tier-balanced fill. A small round therefore still
    # spans directions, which is what "no web/pwn at all" used to break.
    cats = sorted({str(c.get("category") or "") for c in pool})
    rng.shuffle(cats)
    for cat in cats:
        take([c for c in pool if str(c.get("category") or "") == cat])
    tiers = ["困难", "中等", "简单", "入门"]
    rng.shuffle(tiers)
    for tier in tiers:
        take([c for c in pool if str(c.get("difficulty") or "") == tier])

    rest = [c for c in pool if id(c) not in used]
    if order == "hard":
        rest.sort(key=lambda c: -_difficulty_weight(c))
        chosen.extend(rest[: k - len(chosen)])
        return chosen[:k]

    # Fill the remainder tier-balanced: draw a tier first, then a challenge
    # inside it, so the biggest bucket (usually 简单) cannot dominate.
    by_tier: dict[str, list[dict[str, Any]]] = {}
    for c in rest:
        by_tier.setdefault(str(c.get("difficulty") or ""), []).append(c)
    while len(chosen) < k and by_tier:
        tier_key = rng.choice(sorted(by_tier))
        bucket = by_tier[tier_key]
        chosen.append(bucket.pop(rng.randrange(len(bucket))))
        if not bucket:
            del by_tier[tier_key]
    return chosen[:k]


def _load_history(path: Path) -> dict[str, float]:
    """name -> last attempt timestamp (epoch seconds); missing/corrupt = empty."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): float(v) for k, v in raw.items()}
    except Exception:  # noqa: BLE001 - history is best-effort
        return {}


def _save_history(path: Path, history: dict[str, float]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(history, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001 - never fail a round because of bookkeeping
        logger.debug("could not write round history %s", path, exc_info=True)


async def run_round(
    settings: Settings,
    model_specs: list[str],
    round_size: int,
    challenges_dir: str = "challenges",
    no_submit: bool = False,
    min_score: int = 1,
    only: tuple[str, ...] = (),
    order: str = "random",
    cooldown_hours: float = 6.0,
    include_solved: bool = False,
) -> dict[str, Any]:
    """Run one round of ``round_size`` challenges and return a summary dict."""
    platform = make_platform(settings)
    kind = platform_kind(settings)
    concurrency = max(1, int(getattr(settings, "max_concurrent_challenges", 10) or 1))

    configure_semaphore(concurrency * max(1, len(model_specs)))

    await cleanup_orphan_containers()

    if kind == "ret2shell":
        base_url = getattr(settings, "ret2shell_url", "")
    elif kind == "dasctf":
        base_url = getattr(settings, "dasctf_url", "")
    elif kind == "ctf2":
        base_url = getattr(settings, "ctf2_url", "")
    elif kind == "ctfplus":
        base_url = getattr(settings, "ctfplus_url", "")
    else:
        base_url = settings.ctfd_url
    console.print(f"[bold]Platform:[/bold] {kind} ({base_url})")
    if kind in ("ret2shell", "dasctf", "ctf2", "ctfplus"):
        console.print(f"[bold]Categories:[/bold] {getattr(settings, 'challenge_categories', '') or 'all'}")
        if getattr(settings, "challenge_difficulty", ""):
            console.print(f"[bold]Difficulties:[/bold] {settings.challenge_difficulty}")
    if kind == "ret2shell" and not getattr(settings, "ret2shell_token", ""):
        console.print("[red]RET2SHELL_TOKEN missing - set it in .env (localStorage.account.token)[/red]")
        return {"error": "missing token"}
    if kind == "dasctf" and not getattr(settings, "dasctf_access_key", ""):
        console.print("[red]DASCTF_ACCESS_KEY missing - set it in .env (平台接入凭证)[/red]")
        return {"error": "missing access key"}
    if kind == "ctf2" and not getattr(settings, "ctf2_token", ""):
        console.print("[red]CTF2_AGENT_TOKEN missing - paste it from the agent-arena connect page[/red]")
        return {"error": "missing ctf2 token"}
    if kind == "ctfplus" and not getattr(settings, "ctfplus_token", ""):
        console.print("[red]CTFPLUS_TOKEN missing - paste the SessionStore cookie value[/red]")
        return {"error": "missing ctfplus token"}

    try:
        challenges = await platform.fetch_all_challenges()
        solved = await platform.fetch_solved_names()
    except Exception as e:  # noqa: BLE001 - report a clean error, not a traceback
        console.print(f"[red]Failed to fetch challenges: {e}[/red]")
        await platform.close()
        return {"error": str(e)}

    skip_solved = bool(getattr(settings, "skip_solved_pull", True))
    include_solved_flag = bool(include_solved)
    if include_solved_flag and skip_solved:
        # Explicitly re-solving finished challenges contradicts "skip solved on
        # pull"; the include-solved flag wins so the two switches cannot deadlock.
        skip_solved = False

    pool = _filter_pool(
        challenges, solved, min_score=min_score, only=only, include_solved=include_solved
    )
    # Challenges the platform will not accept any more are parked forever;
    # picking them again only burns solver time and model tokens.
    try:
        from backend import pauses

        paused = pauses.paused_names()
        if paused:
            before = len(pool)
            pool = [c for c in pool if str(c.get("name") or "") not in paused]
            if len(pool) != before:
                console.print(
                    f"[dim]Skipped {before - len(pool)} paused challenge(s) "
                    f"(no submission attempts left).[/dim]"
                )
    except Exception:  # noqa: BLE001 - pause bookkeeping must not break a round
        logger.debug("suppressed exception in run_round", exc_info=True)

    # Reclaim target environments left over by a crashed or finished run.
    reconcile = getattr(platform, "reconcile_envs", None)
    if callable(reconcile):
        try:
            closed = await reconcile(keep=set())
            if closed:
                console.print(f"[dim]Closed {closed} leftover target env(s).[/dim]")
        except Exception as exc:  # noqa: BLE001
            logger.debug("round: env reconcile failed: %s", exc)
    # Resume: an unfinished run (crash / closed terminal) leaves its open
    # challenges in logs/runs/<id>/state.json; --resume limits this round to them.
    run_id = ""
    resume_state = None
    resume_id = str(getattr(settings, "resume_run", "") or "").strip()
    if resume_id:
        from backend import snapshot as _snapshot

        resume_state = (
            _snapshot.latest_open() if resume_id == "latest" else _snapshot.load(resume_id)
        )
        if resume_state:
            todo = set(_snapshot.unfinished(resume_state))
            before = len(pool)
            pool = [c for c in pool if str(c.get("name") or "") in todo]
            console.print(
                f"[cyan]Resumed run {resume_state.get('run_id')}: "
                f"{len(pool)}/{before} candidate(s) still open.[/cyan]"
            )
        else:
            console.print(
                f"[yellow]Run {resume_id!r} not found - starting a normal round.[/yellow]"
            )

    history_path = Path(getattr(settings, "round_history_file", "logs/round-history.json"))
    history = _load_history(history_path)
    now = time.time()
    cooldown_s = max(0.0, float(cooldown_hours)) * 3600.0
    recent = {n for n, ts in history.items() if cooldown_s > 0 and now - ts < cooldown_s}
    fresh = [
        c
        for c in pool
        if str(c.get("name") or "") not in recent
        # When explicitly re-solving finished challenges, the cooldown does
        # not apply to them (they were attempted when they were still open).
        # --include-solved is "pull everything": solved AND unsolved, even if
        # an unsolved one was attempted earlier in the cooldown window.
        or include_solved
    ]
    skipped_recent = len(pool) - len(fresh)
    if fresh or not pool:
        selected = _pick(fresh, round_size, order)
    else:
        # Every candidate was recently attempted: prefer progress over purity.
        console.print(
            f"[yellow]All {len(pool)} candidates were attempted in the last "
            f"{cooldown_hours:g}h - retrying anyway (use --retry to always allow this).[/yellow]"
        )
        selected = _pick(pool, round_size, order)
    console.print(
        f"[bold]Challenges:[/bold] {len(challenges)} total, {len(solved)} solved, "
        f"{len(challenges) - len(solved)} unsolved -> this round: [bold]{len(selected)}[/bold]"
        + (f" (min score {min_score})" if min_score > 0 else "")
        + (f" (only: {', '.join(only)})" if only else "")
        + (" (include solved)" if include_solved else "")
        + f" [dim](order: {order}, cooldown {cooldown_hours:g}h, skipped {skipped_recent} recent)[/dim]"
    )
    if not selected:
        if pool:
            console.print("[yellow]Nothing fresh to solve - exiting.[/yellow]")
        else:
            console.print("[yellow]Nothing to solve - exiting.[/yellow]")
            if solved and not include_solved:
                console.print(
                    f"[yellow]Every challenge the platform lists is already solved "
                    f"({len(solved)}/{len(challenges)}). Tick 含已解题 / pass "
                    f"--include-solved to re-solve them; 拉题跳过已解 only decides "
                    f"whether solved ones are skipped, it never adds them back.[/yellow]"
                )
        await platform.close()
        return {"results": {}, "selected": 0}

    # Snapshot the run so an interrupted round can be resumed (--resume).
    try:
        run_id = str((resume_state or {}).get("run_id") or "") or snapshot.new_run(
            getattr(settings, "platform", "") or type(platform).__name__,
            len(selected),
            model_specs,
        )
        if resume_state:
            resume_state["finished"] = False
            snapshot.save(run_id, resume_state)
        console.print(f"[dim]Run snapshot: logs/runs/{run_id}/state.json[/dim]")
    except Exception as exc:  # noqa: BLE001 - snapshots must never break a round
        logger.debug("round: snapshot init failed: %s", exc)

    # ---------------------------------------------------------- scheduling
    # Do NOT start all N challenges at once. A dispatcher feeds the solver
    # slots and prefers attachment-only challenges whenever the platform's
    # target quota is exhausted, so a container-heavy pick never stalls the
    # round: solve an attachment challenge, and when a target frees up (the
    # container challenge is done and its env closed) pull the next container.
    # ``selected`` above is already the stratified pick for this round; use it
    # directly instead of re-shuffling the whole pool.
    # The platform grants very few live targets (often just one), so cap the
    # container challenges at that quota and backfill with attachment-only work
    # - otherwise "concurrency 3" degenerates into one solver while the rest
    # wait for a target that will never be free.
    try:
        max_targets = int(await platform.max_environments())
    except Exception:  # noqa: BLE001 - quota probe must not abort the round
        max_targets = 1
    max_targets = max(1, max_targets)
    containers = [c for c in selected if c.get("has_container")]
    if len(containers) > max_targets:
        keep = {id(c) for c in containers[:max_targets]}
        ordered = [c for c in selected if not c.get("has_container") or id(c) in keep]
        used = {id(c) for c in ordered}
        spare = [c for c in pool if not c.get("has_container") and id(c) not in used]
        ordered = ordered + spare[: max(0, len(selected) - len(ordered))]
        console.print(
            f"[dim]Target quota {max_targets}: {len(containers)} container challenge(s) "
            f"capped, backfilled with {len(ordered) - (len(selected) - len(containers) + max_targets)} "
            "attachment challenge(s).[/dim]"
        )
    else:
        ordered = list(selected)
    budget = len(ordered)
    containers = [c for c in ordered if c.get("has_container")]
    plain = [c for c in ordered if not c.get("has_container")]
    console.print(
        f"[bold]Round budget:[/bold] {budget} challenge(s) | concurrency {concurrency} | "
        f"{len(containers)} need a target, {len(plain)} attachment-only"
    )

    Path(challenges_dir).mkdir(parents=True, exist_ok=True)
    if getattr(settings, "fresh_solve", False):
        # Evaluation mode: earlier answers/solve scripts must not be readable from
        # the workspace, so the model really solves it from the attachments.
        wiped = _wipe_challenge_dirs(challenges_dir)
        if wiped:
            console.print(
                f"[dim]fresh mode: wiped {wiped} local challenge dir(s) under "
                f"{challenges_dir} (memory and writeups are ignored too)[/dim]"
            )
    cost_tracker = CostTracker()
    results: dict[str, dict[str, Any]] = {}
    sem = DynamicSemaphore(concurrency)
    runtime.set_concurrency(concurrency)
    # Tunnels from a previous (crashed) round would otherwise shadow this one.
    try:
        from backend import wsrx

        wsrx.close_all()
    except Exception:  # noqa: BLE001 - tunnel cleanup is best effort
        logger.debug("suppressed exception in run_round", exc_info=True)
    # Two worker pools, borrowed from the reference agent: attachment-only
    # challenges and challenges that need a live target queue separately, so a
    # long target build cannot starve the quick attachment work.
    attach_limit = int(getattr(settings, "max_attachment_workers", 0) or 0) or concurrency
    attach_sem = asyncio.Semaphore(max(1, min(concurrency, attach_limit)))
    target_sem: asyncio.Semaphore | None = None
    watcher_stop = asyncio.Event()

    from backend import heartbeat

    heartbeat.clear()
    env_beat = heartbeat.EnvHeartbeat(
        platform, interval=float(getattr(settings, "env_heartbeat_s", 300.0) or 300.0)
    )
    env_beat.start()

    max_envs = 1
    if containers:
        override = int(getattr(settings, "max_environments", 0) or 0)
        try:
            quota = await platform.max_environments()
        except Exception:  # noqa: BLE001 - quota lookup is best effort
            quota = 1
        # Never dispatch more targets than the platform actually allows, even
        # when MAX_ENVIRONMENTS asks for more; if the quota is raised later the
        # scheduler automatically uses it.
        max_envs = max(1, min(override, quota) if override else quota)
        if override and override > quota:
            console.print(
                f"[yellow]MAX_ENVIRONMENTS={override} but the platform allows "
                f"{quota} target(s) - using {quota}.[/yellow]"
            )
        target_override = int(getattr(settings, "max_target_workers", 0) or 0)
        target_limit = max(1, min(target_override or max_envs, max_envs))
        target_sem = asyncio.Semaphore(max(1, min(concurrency, target_limit)))
        console.print(
            f"[dim]Container challenges: at most {max_envs} target(s) at a time "
            f"(pool {target_limit}).[/dim]"
        )
        # Targets left over from an earlier round keep the quota busy; close
        # them up front so this round can actually start one.
        closer = getattr(platform, "close_stale_envs", None)
        if closer is not None:
            try:
                freed = await closer({str(c.get("name") or "") for c in ordered[:budget]})
                if freed:
                    console.print(f"[dim]Closed {freed} stale target env(s).[/dim]")
            except Exception as exc:  # noqa: BLE001 - best effort
                logger.debug("stale env cleanup failed: %s", exc)

    async def watch_concurrency() -> None:
        """Follow the dashboard's runtime setting so 并发数 can change live."""
        while not watcher_stop.is_set():
            want = runtime.get_concurrency()
            if want is not None:
                target = max(1, min(want, budget))
                if target != sem.limit:
                    await sem.set_limit(target)
                    configure_semaphore(target * max(1, len(model_specs)))
                    console.print(f"[cyan]concurrency -> {target}[/cyan]")
            try:
                await asyncio.wait_for(watcher_stop.wait(), timeout=2.0)
            except TimeoutError:
                continue

    watcher = asyncio.create_task(watch_concurrency())

    async def solve_one(ch: dict[str, Any], holds_env: bool) -> None:
        name = str(ch.get("name") or "?")
        snapshot.update_challenge(run_id, name, status="running")
        if (
            skip_solved
            and not include_solved_flag
            and name in solved
        ):
            results[name] = {"flag": None, "status": "already_solved"}
            console.print(f"[dim]=[/dim] {name}: already solved on the platform - skipped")
            snapshot.update_challenge(run_id, name, status="already_solved")
            return
        if holds_env and target_sem is not None:
            await target_sem.acquire()
        else:
            await attach_sem.acquire()
        await sem.acquire()
        try:
            ch_dir = await platform.pull_challenge(ch, challenges_dir)
            meta = ChallengeMeta.from_yaml(Path(ch_dir) / "metadata.yml")
            heartbeat.track(name)
            console.print(f"[cyan]>[/cyan] {name} -> {ch_dir}")
            timeout_min = float(getattr(settings, "challenge_timeout_min", 0) or 0)
            extra = max(0, int(getattr(settings, "challenge_extra_rounds", 0) or 0))
            result = None
            timed_out = False
            for attempt in range(extra + 1):
                if attempt:
                    console.print(f"[yellow]~[/yellow] {name}: extra round {attempt}/{extra}")
                swarm = ChallengeSwarm(
                    challenge_dir=ch_dir,
                    meta=meta,
                    ctfd=platform,
                    cost_tracker=cost_tracker,
                    settings=settings,
                    model_specs=model_specs,
                    no_submit=no_submit,
                )
                if timeout_min > 0:
                    try:
                        result = await asyncio.wait_for(swarm.run(), timeout=timeout_min * 60)
                    except TimeoutError:
                        console.print(f"[yellow]![/yellow] {name}: timed out after {timeout_min:g} min")
                        results[name] = {"flag": None, "status": "timeout"}
                        timed_out = True
                        break
                else:
                    result = await swarm.run()
                if result is not None and result.status in (FLAG_FOUND, "skipped"):
                    break
            if timed_out:
                return
            if result and result.status == "skipped":
                results[name] = {"flag": None, "status": "skipped"}
                console.print(f"[yellow]~[/yellow] {name}: skipped by operator")
            elif result and result.status == FLAG_FOUND:
                results[name] = {"flag": result.flag, "status": "solved"}
                console.print(f"[green]+[/green] {name}: {result.flag}")
                if getattr(settings, "writeup_enabled", False):
                    try:
                        from backend import writeup

                        wp = await writeup.write(settings, meta, result)
                        if wp:
                            console.print(f"[dim]WP saved: {wp}[/dim]")
                    except Exception as exc:  # noqa: BLE001 - never lose a solve
                        console.print(f"[yellow]WP failed for {name}: {exc}[/yellow]")
            else:
                results[name] = {"flag": None, "status": "unsolved"}
                console.print(f"[yellow]-[/yellow] {name}: no flag")
        except Exception as e:  # noqa: BLE001 - one challenge must not abort the round
            logger.exception("round challenge failed: %s", name)
            results[name] = {"flag": None, "status": f"error: {e}"}
            console.print(f"[red]![/red] {name}: {e}")
        finally:
            heartbeat.untrack(name)
            # Close the target before releasing the slot so the next container
            # challenge does not get a 409 from a stale env.
            if holds_env:
                stopper = getattr(platform, "stop_env", None)
                if stopper is not None:
                    try:
                        await stopper(name)
                    except Exception:  # noqa: BLE001 - best effort
                        logger.debug("suppressed exception in solve_one", exc_info=True)
            await sem.release()
            if holds_env and target_sem is not None:
                target_sem.release()
            else:
                attach_sem.release()
            try:
                entry = results.get(name) or {}
                snapshot.update_challenge(
                    run_id,
                    name,
                    status=str(entry.get("status") or "failed"),
                    flag=entry.get("flag"),
                    trace=str(getattr(entry, "log_path", "") or ""),
                    cost_usd=round(cost_tracker.challenge_cost(name), 6),
                )
            except Exception as exc:  # noqa: BLE001 - snapshots are best effort
                logger.debug("round: snapshot update failed: %s", exc)
            console.print(f"[dim]progress {len(results)}/{budget}[/dim]")

    rotate = bool(getattr(settings, "round_rotate", False))
    batch_size = int(getattr(settings, "rotate_batch", 0) or 0) or concurrency

    def _spawn(chunk: list[dict[str, Any]]) -> list[asyncio.Task[Any]]:
        tasks: list[asyncio.Task[Any]] = []
        for ch in chunk:
            history[str(ch.get("name") or "?")] = time.time()
            _save_history(history_path, history)
            tasks.append(asyncio.create_task(solve_one(ch, bool(ch.get("has_container")))))
        return tasks

    try:
        if rotate:
            from backend.selector import rotate_chunks

            order_hint = [
                c.strip()
                for c in str(getattr(settings, "challenge_categories", "")).split(",")
                if c.strip()
            ]
            # Chunk the whole candidate pool (not just this round's slice) so
            # "10 challenges" really means 5 MISC then 5 RE: the direction
            # queues are round-robined before we take the first ``budget``.
            pool_all = list(pool)
            if include_solved:
                pool_all = pool_all + [
                    c for c in challenges if c.get("solved") and id(c) not in {id(x) for x in pool_all}
                ]
            chunks = rotate_chunks(pool_all, batch_size, order_hint)
            trimmed: list[list[dict[str, Any]]] = []
            left = budget
            for chunk in chunks:
                if left <= 0:
                    break
                piece = chunk[:left]
                trimmed.append(piece)
                left -= len(piece)
            if trimmed:
                console.print(
                    f"[bold]Drill mode:[/bold] {len(trimmed)} batch(es) of <= {batch_size}, "
                    "one direction per batch."
                )
            for index, chunk in enumerate(trimmed, start=1):
                category = str(chunk[0].get("category") or "-")
                console.print(
                    f"[bold]Batch {index}/{len(trimmed)}[/bold]: {category} x {len(chunk)}"
                )
                await asyncio.gather(*_spawn(chunk), return_exceptions=True)
        else:
            pending = set(_spawn(ordered[:budget]))
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
    finally:
        watcher_stop.set()
        watcher.cancel()
        await env_beat.stop()
        heartbeat.clear()
        # Every exit path must destroy the platform targets we started, or the
        # next run finds the environment quota still consumed.
        stop_all = getattr(platform, "stop_all_envs", None)
        if stop_all is not None:
            try:
                stopped = await asyncio.wait_for(stop_all(), timeout=120)
                if stopped:
                    console.print(f"[dim]Closed {stopped} platform target(s).[/dim]")
            except Exception:  # noqa: BLE001 - cleanup must not fail the round
                logger.debug("post-round target cleanup failed", exc_info=True)
        await platform.close()
        # Cancelled solvers can leave their sandbox containers behind (a
        # cancelled task cannot reliably finish its own cleanup), so reap every
        # ctf-agent container once the round is over.
        try:
            await cleanup_orphan_containers(0, force=True)
        except Exception:  # noqa: BLE001 - cleanup must not fail the round
            logger.debug("post-round container cleanup failed", exc_info=True)
        # WSRX tunnels are child processes of this run; leaving them behind
        # would keep ports bound and instances half-exposed.
        try:
            from backend import wsrx

            closed = wsrx.close_all()
            if closed:
                console.print(f"[dim]Closed {closed} WSRX tunnel(s).[/dim]")
        except Exception:  # noqa: BLE001
            logger.debug("post-round wsrx cleanup failed", exc_info=True)

    solved_n = sum(1 for r in results.values() if r["status"] == "solved")
    per_challenge = cost_tracker.get_usage_by_challenge()
    console.print("\n[bold]Round summary[/bold]")
    for name, r in results.items():
        flag = r.get("flag") or "-"
        spent = per_challenge.get(name, {}).get("cost", 0.0)
        cost = f" [dim](${spent:.4f})[/dim]" if spent else ""
        console.print(f"  {name}: {r['status']} {flag if flag != '-' else ''}{cost}")
    console.print(
        f"\n[bold]Solved {solved_n}/{len(results)}[/bold] | total cost ${cost_tracker.total_cost_usd:.4f}"
    )
    cost_tracker.log_challenge_summary()
    snapshot.finish(run_id)
    console.print("[dim]Round finished - stopping.[/dim]")

    return {
        "results": results,
        "selected": len(results),
        "solved": solved_n,
        "total_cost_usd": cost_tracker.total_cost_usd,
        "cost_by_challenge": {k: v["cost"] for k, v in per_challenge.items()},
    }
