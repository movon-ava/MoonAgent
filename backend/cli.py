"""Click CLI entry point."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
from rich.console import Console

from backend.config import Settings
from backend.models import default_model_specs

logger = logging.getLogger(__name__)

console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    # -v shows *our* debug logs; SDK HTTP chatter would bury the solver activity.
    for noisy in (
        "httpx",
        "httpcore",
        "hpack",
        "h2",
        "urllib3",
        "botocore",
        "aiodocker",
        "openai",
        "openai._base_client",
        "anthropic",
        "google",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s", datefmt="%X"))
    logging.basicConfig(level=level, handlers=[handler], force=True)


@click.command()
@click.option("--ctfd-url", default=None, help="CTFd URL (overrides .env)")
@click.option("--ctfd-token", default=None, help="CTFd API token (overrides .env)")
@click.option("--image", default="ctf-sandbox", help="Docker sandbox image name")
@click.option("--models", multiple=True, help="Model specs (default: all configured)")
@click.option("--challenge", default=None, help="Solve a single challenge directory")
@click.option("--challenges-dir", default="challenges", help="Directory for challenge files")
@click.option("--no-submit", is_flag=True, help="Dry run — don't submit flags")
@click.option("--coordinator-model", default=None, help="Model for coordinator (default: claude-opus-4-6 / deepseek-flash)")
@click.option("--coordinator", default=None, type=click.Choice(["claude", "codex", "deepseek"]), help="Coordinator backend (default: deepseek when only DeepSeek models are configured, else claude)")
@click.option("--max-challenges", default=None, type=int, help="Max challenges solved concurrently (default: MAX_CONCURRENT_CHALLENGES, then 10)")
@click.option("--resume", default="", metavar="[latest|RUN_ID]", help="Resume an unfinished run snapshot from logs/runs (latest = newest unfinished)")
@click.option("--challenge-timeout", default=None, type=float, help="Per-challenge budget in minutes, 0 = no limit (default: CHALLENGE_TIMEOUT_MIN)")
@click.option("--knowledge/--no-knowledge", "knowledge_enabled", default=None, help="Inject knowledge/<category>.md checklists into the prompt (default: KNOWLEDGE_ENABLED)")
@click.option("--skills/--no-skills", "skills_enabled", default=None, help="List skills/*.md in the prompt and let the solver load one with use_skill() (default: SKILLS_ENABLED)")
@click.option("--chains/--no-chains", "chains_enabled", default=None, help="List chains/*.md (stage checklists) in the prompt and let the solver load one with use_chain() (default: CHAINS_ENABLED)")
@click.option("--extra-rounds", default=None, type=int, help="Extra swarm rounds when a challenge came back unsolved, 0 = none (default: CHALLENGE_EXTRA_ROUNDS)")
@click.option("--writeup/--no-writeup", default=None, help="Write a Chinese writeup for every solved challenge (default: WRITEUP_ENABLED)")
@click.option("--flag-format", default=None, help="Expected flag shape for this contest, e.g. moectf{} (hint for the solver, default: FLAG_FORMAT)")
@click.option("--flag-submit-mode", default=None, type=click.Choice(["full", "inner"]), help="full = submit the whole flag, inner = only the text inside {} (default: FLAG_SUBMIT_MODE)")
@click.option("--think-chinese/--no-think-chinese", default=None, help="Ask the model to reason in Simplified Chinese (default: THINK_CHINESE)")
@click.option("--require-evidence/--no-require-evidence", "require_flag_evidence", default=None, help="Require submit_flag(evidence=...) so guessed flags do not burn quota (default: REQUIRE_FLAG_EVIDENCE)")
@click.option("--skip-solved/--no-skip-solved", default=None, help="Skip challenges the platform already marks solved (default: SKIP_SOLVED_PULL)")
@click.option("--trace-mask/--no-trace-mask", default=None, help="Mask flags and tokens in logs/trace-*.jsonl (default: TRACE_MASK)")
@click.option("--fresh/--no-fresh", default=None, help="Evaluation mode: ignore cross-round memory and wipe local challenge dirs (default: FRESH_SOLVE)")
@click.option("--max-env", default=None, type=int, help="How many platform targets may run at once (0 = platform quota; default: MAX_ENVIRONMENTS)")
@click.option("--msg-port", default=0, type=int, help="Operator message port (0 = auto)")
@click.option(
    "--platform",
    default=None,
    type=click.Choice(["auto", "ctfd", "ret2shell", "dasctf", "ctf2", "ctfplus"]),
    help="Platform backend (auto: ret2shell when RET2SHELL_TOKEN is set, dasctf when DASCTF_ACCESS_KEY is set, ctf2 when CTF2_AGENT_TOKEN is set, ctfplus when CTFPLUS_TOKEN is set, else ctfd)",
)
@click.option("--ret2shell-url", default=None, help="Ret2Shell base URL (default https://ctf.xidian.edu.cn)")
@click.option("--ret2shell-token", default=None, help="Ret2Shell session token (localStorage.account.token)")
@click.option("--dasctf-url", default=None, help="DASCTF server host (default https://pro.dasctf.com)")
@click.option("--access-key", default=None, help="DASCTF agent access key (ak_live_..., from 平台接入凭证)")
@click.option("--ctf2-url", default=None, help="CTF² base URL (default https://ctf2.dasctf.com)")
@click.option("--ctf2-token", default=None, help="CTF² agent PAT (CTF2_AGENT_TOKEN from the connect page)")
@click.option("--ctf2-ground", default=None, help="CTF² practice ground id or slug (default: all grounds)")
@click.option("--ctfplus-url", default=None, help="CTF+ base URL (default https://geek2026.play.ctfplus.cn)")
@click.option("--game", default=None, help="Ret2Shell game id or name (default: active game)")
@click.option(
    "--categories",
    default=None,
    help="Directions to pull, comma separated: web,misc,pwn,re,crypto (all = no filter)",
)
@click.option(
    "--difficulty",
    default=None,
    help="Difficulty filter: 入门,简单,中等,困难 (or easy/medium/hard; comma separated)",
)
@click.option(
    "--round",
    "round_size",
    default=None,
    type=int,
    help="Round mode: pull N unsolved challenges, solve, submit, then stop",
)
@click.option(
    "--instructions",
    default=None,
    help="Prompt file with flag format / submission rules (default INSTRUCTIONS.md)",
)
@click.option(
    "--min-score",
    default=None,
    type=int,
    help="Round mode: skip challenges worth less than this (default 1, 0 = keep all)",
)
@click.option(
    "--only",
    multiple=True,
    help="Round mode: only solve names containing this text (repeatable)",
)
@click.option(
    "--order",
    default=None,
    type=click.Choice(["random", "hard", "score", "name", "easy"], case_sensitive=False),
    help="Round mode: pick order (random = difficulty-weighted; hard = hardest first; score = cheapest first; easy = easiest first)",
)
@click.option(
    "--cooldown-hours",
    default=None,
    type=float,
    help="Round mode: skip challenges attempted within N hours (default 6, 0 = off)",
)
@click.option(
    "--retry",
    is_flag=True,
    help="Round mode: ignore the recent-attempt cooldown and allow repeats",
)
@click.option(
    "--rotate/--no-rotate",
    "rotate",
    default=None,
    help="Round mode: drill one direction per batch (misc -> re -> crypto ...)",
)
@click.option(
    "--rotate-batch",
    default=None,
    type=int,
    help="Round mode: challenges per direction batch in drill mode (default: concurrency)",
)
@click.option(
    "--blitz/--no-blitz",
    "blitz",
    default=None,
    help="Round mode: fast attack - sweep the pool easy to hard, drop slow challenges",
)
@click.option(
    "--blitz-max",
    default=None,
    type=int,
    help="Blitz mode: stop after N challenges (default: the whole candidate pool)",
)
@click.option(
    "--blitz-timeout",
    default=None,
    type=float,
    help="Blitz mode: minutes per challenge before moving on (default: 6)",
)
@click.option(
    "--pick",
    "pick",
    multiple=True,
    help="Run only these challenges (name or substring); repeatable",
)
@click.option(
    "--include-solved",
    is_flag=True,
    help="Round mode: also allow already-solved challenges in the pool",
)
@click.option("-v", "--verbose", is_flag=True, help="Verbose logging")
def main(
    ctfd_url: str | None,
    ctfd_token: str | None,
    image: str,
    models: tuple[str, ...],
    challenge: str | None,
    challenges_dir: str,
    no_submit: bool,
    coordinator_model: str | None,
    coordinator: str,
    max_challenges: int | None,
    challenge_timeout: float | None,
    resume: str,
    knowledge_enabled: bool | None,
    skills_enabled: bool | None,
    chains_enabled: bool | None,
    extra_rounds: int | None,
    writeup: bool | None,
    flag_format: str | None,
    flag_submit_mode: str | None,
    think_chinese: bool | None,
    require_flag_evidence: bool | None,
    skip_solved: bool | None,
    trace_mask: bool | None,
    fresh: bool | None,
    max_env: int | None,
    msg_port: int,
    platform: str | None,
    ret2shell_url: str | None,
    ret2shell_token: str | None,
    dasctf_url: str | None,
    access_key: str | None,
    ctf2_url: str | None,
    ctf2_token: str | None,
    ctf2_ground: str | None,
    ctfplus_url: str | None,
    game: str | None,
    categories: str | None,
    difficulty: str | None,
    round_size: int | None,
    instructions: str | None,
    min_score: int | None,
    only: tuple[str, ...],
    order: str | None,
    cooldown_hours: float | None,
    retry: bool,
    rotate: bool | None,
    blitz: bool | None,
    blitz_max: int | None,
    blitz_timeout: float | None,
    pick: tuple[str, ...],
    rotate_batch: int | None,
    include_solved: bool,
    verbose: bool,
) -> None:
    """CTF Agent — multi-model solver swarm.

    Run without --challenge to start the full coordinator (Ctrl+C to stop).
    Use --round N for a one-shot round: pull N unsolved challenges, solve and
    submit them, then exit.
    """
    _setup_logging(verbose)

    settings = Settings(sandbox_image=image)
    if ctfd_url:
        settings.ctfd_url = ctfd_url
    if ctfd_token:
        settings.ctfd_token = ctfd_token
    if max_challenges is None:
        max_challenges = max(1, int(settings.max_concurrent_challenges or 10))
    settings.max_concurrent_challenges = max_challenges
    if knowledge_enabled is not None:
        settings.knowledge_enabled = bool(knowledge_enabled)
    if skills_enabled is not None:
        settings.skills_enabled = bool(skills_enabled)
    if chains_enabled is not None:
        settings.chains_enabled = bool(chains_enabled)
    if resume:
        settings.resume_run = str(resume).strip()
    if challenge_timeout is not None:
        settings.challenge_timeout_min = max(0.0, float(challenge_timeout))
    if extra_rounds is not None:
        settings.challenge_extra_rounds = max(0, int(extra_rounds))
    if writeup is not None:
        settings.writeup_enabled = bool(writeup)
    if flag_format is not None:
        settings.flag_format = str(flag_format).strip()
    if flag_submit_mode is not None:
        settings.flag_submit_mode = str(flag_submit_mode)
    if think_chinese is not None:
        settings.think_chinese = bool(think_chinese)
    if require_flag_evidence is not None:
        settings.require_flag_evidence = bool(require_flag_evidence)
    if skip_solved is not None:
        settings.skip_solved_pull = bool(skip_solved)
    if trace_mask is not None:
        settings.trace_mask = bool(trace_mask)
    if fresh is not None:
        settings.fresh_solve = bool(fresh)
    if max_env is not None:
        settings.max_environments = max(0, int(max_env))

    if platform:
        settings.platform = platform
    if ret2shell_url:
        settings.ret2shell_url = ret2shell_url
    if ret2shell_token:
        settings.ret2shell_token = ret2shell_token
    if dasctf_url:
        settings.dasctf_url = dasctf_url
    if access_key:
        settings.dasctf_access_key = access_key
    if ctf2_url:
        settings.ctf2_url = ctf2_url
    if ctf2_token:
        settings.ctf2_token = ctf2_token
    if ctf2_ground:
        settings.ctf2_ground = ctf2_ground
    if ctfplus_url:
        settings.ctfplus_url = ctfplus_url
    if game:
        settings.ret2shell_game = game
    if categories:
        settings.challenge_categories = categories
    if difficulty is not None:
        settings.challenge_difficulty = difficulty
    if settings.challenge_difficulty:
        from backend.ret2shell import normalize_difficulties

        try:
            settings.challenge_difficulty = ",".join(
                normalize_difficulties(settings.challenge_difficulty)
            )
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise SystemExit(2) from exc
    if instructions:
        settings.instructions_file = instructions
    if round_size is not None:
        settings.round_size = round_size
    if min_score is not None:
        settings.round_min_score = min_score
    if only:
        settings.round_only = ",".join(only)
    if order:
        settings.round_order = order.lower()
    if cooldown_hours is not None:
        settings.round_cooldown_hours = cooldown_hours
    if retry:
        settings.round_cooldown_hours = 0.0
    if rotate is not None:
        settings.round_rotate = bool(rotate)
    if rotate_batch is not None:
        settings.rotate_batch = max(0, int(rotate_batch))
    if blitz is not None:
        settings.blitz_mode = bool(blitz)
    if blitz_max is not None:
        settings.blitz_max_challenges = max(0, int(blitz_max))
    if blitz_timeout is not None:
        settings.blitz_timeout_min = max(1.0, float(blitz_timeout))
    if pick:
        settings.pick_challenges = ",".join(p.strip() for p in pick if p.strip())
    if include_solved:
        settings.round_include_solved = True

    # --challenge always means "solve exactly this one", even when ROUND_SIZE is set.
    if challenge:
        settings.round_size = 0
        settings.round_only = ""

    from backend.platform import platform_kind

    kind = platform_kind(settings)
    model_specs = list(models) if models else default_model_specs(settings)

    # Honour per-model budgets configured from the web dashboard.
    from backend import quota

    if any(s.startswith("deepseek/") for s in model_specs):
        # DeepSeek budgets are measured against the official balance, so pull a
        # fresh one before deciding (cheap GET, 10s timeout).
        quota.refresh_balance(settings.deepseek_base_url, settings.deepseek_api_key)
    blocked = [s for s in model_specs if not quota.available(s)]
    if blocked:
        console.print(f"[yellow]Budget exhausted, skipping: {', '.join(blocked)}[/yellow]")
        model_specs = [s for s in model_specs if quota.available(s)]
    if not model_specs:
        console.print(
            "[red]All selected models are out of budget — raise the limit in the web "
            "dashboard (配置 → 模型配置) or reset the spend.[/red]"
        )
        raise SystemExit(2)

    if not coordinator:
        only_deepseek = bool(model_specs) and all(s.startswith("deepseek/") for s in model_specs)
        coordinator = "deepseek" if (settings.deepseek_api_key and only_deepseek) else "claude"

    console.print("[bold]CTF Agent v2[/bold]")
    if kind == "ret2shell":
        console.print(f"  Platform: ret2shell ({settings.ret2shell_url})")
        console.print(f"  Categories: {settings.challenge_categories or 'all'}")
        if settings.challenge_difficulty:
            console.print(f"  Difficulties: {settings.challenge_difficulty}")
        if not settings.ret2shell_token:
            console.print("  [yellow]RET2SHELL_TOKEN missing — set it in .env before running[/yellow]")
    elif kind == "dasctf":
        console.print(f"  Platform: dasctf ({settings.dasctf_url})")
        console.print(f"  Categories: {settings.challenge_categories or 'all'}")
        if settings.challenge_difficulty:
            console.print(f"  Difficulties: {settings.challenge_difficulty}")
        if not settings.dasctf_access_key:
            console.print("  [yellow]DASCTF_ACCESS_KEY missing — set it in .env before running[/yellow]")
    elif kind == "ctf2":
        console.print(f"  Platform: ctf2 ({settings.ctf2_url})")
        console.print(f"  Categories: {settings.challenge_categories or 'all'}")
        if settings.challenge_difficulty:
            console.print(f"  Difficulties: {settings.challenge_difficulty}")
        if settings.ctf2_ground:
            console.print(f"  Practice ground: {settings.ctf2_ground}")
        if not settings.ctf2_token:
            console.print("  [yellow]CTF2_AGENT_TOKEN missing — set it in .env before running[/yellow]")
    elif kind == "ctfplus":
        console.print(f"  Platform: ctfplus ({settings.ctfplus_url})")
        console.print(f"  Categories: {settings.challenge_categories or 'all'}")
        if settings.challenge_difficulty:
            console.print(f"  Difficulties: {settings.challenge_difficulty}")
        if not settings.ctfplus_token:
            console.print("  [yellow]CTFPLUS_TOKEN missing — paste the SessionStore cookie value in .env[/yellow]")
    else:
        console.print(f"  Platform: ctfd ({settings.ctfd_url})")
        console.print(f"  CTFd: {settings.ctfd_url}")
    console.print(f"  Models: {', '.join(model_specs)}")
    console.print(f"  Coordinator: {coordinator}")
    console.print(f"  Image: {settings.sandbox_image}")
    console.print(f"  Max challenges: {max_challenges}")
    console.print(
        f"  Instructions: {settings.instructions_file}"
        f"{'' if Path(settings.instructions_file).exists() else ' [yellow](missing)[/yellow]'}"
    )
    if settings.round_size and settings.round_size > 0:
        console.print(
            f"  Round: {settings.round_size} challenge(s), order={settings.round_order}, "
            f"cooldown={settings.round_cooldown_hours:g}h"
            f"{', include-solved' if settings.round_include_solved else ''}"
            f"{', drill mode' if settings.round_rotate else ''}"
        )
    console.print()

    try:
        if settings.round_size and settings.round_size > 0:
            asyncio.run(_run_round(settings, model_specs, challenges_dir, no_submit))
        elif challenge:
            asyncio.run(_run_single(settings, challenge, model_specs, no_submit, max_challenges))
        else:
            asyncio.run(_run_coordinator(settings, model_specs, challenges_dir, no_submit, coordinator_model, coordinator, max_challenges, msg_port))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted - closing platform targets…[/yellow]")
        asyncio.run(_stop_all_targets(settings))
        raise SystemExit(130) from None


async def _stop_all_targets(settings: Settings) -> None:
    """Close every platform target we may still be holding (Ctrl+C path)."""
    from backend.platform import make_platform

    try:
        platform = make_platform(settings)
    except Exception:  # noqa: BLE001
        return
    try:
        stop_all = getattr(platform, "stop_all_envs", None)
        if stop_all is not None:
            try:
                stopped = await asyncio.wait_for(stop_all(), timeout=120)
                if stopped:
                    console.print(f"[dim]Closed {stopped} platform target(s).[/dim]")
            except Exception:  # noqa: BLE001
                logger.debug("suppressed exception in _stop_all_targets", exc_info=True)
    finally:
        try:
            await platform.close()
        except Exception:  # noqa: BLE001
            logger.debug("suppressed exception in _stop_all_targets", exc_info=True)


async def _run_round(
    settings: Settings,
    model_specs: list[str],
    challenges_dir: str,
    no_submit: bool,
) -> None:
    """One-shot round: pull N unsolved challenges, solve, submit, exit."""
    from backend.hints import start_hint_listener
    from backend.round_runner import run_round

    start_hint_listener()
    console.print(
        "[dim]提示：解题过程中直接输入文字并回车，会作为提示注入正在运行的 agent。[/dim]"
    )

    only = tuple(s.strip() for s in (settings.round_only or "").split(",") if s.strip())
    summary = await run_round(
        settings=settings,
        model_specs=model_specs,
        round_size=int(settings.round_size),
        challenges_dir=challenges_dir,
        no_submit=no_submit,
        min_score=int(settings.round_min_score),
        only=only,
        order=settings.round_order or "random",
        cooldown_hours=float(settings.round_cooldown_hours),
        include_solved=bool(settings.round_include_solved),
    )
    if summary.get("error"):
        sys.exit(1)


async def _run_single(
    settings: Settings,
    challenge_dir: str,
    model_specs: list[str],
    no_submit: bool,
    max_challenges: int,
) -> None:
    """Run a single challenge with a swarm."""
    from backend.agents.swarm import ChallengeSwarm
    from backend.cost_tracker import CostTracker
    from backend.hints import start_hint_listener
    from backend.platform import make_platform
    from backend.prompts import ChallengeMeta
    from backend.sandbox import cleanup_orphan_containers, configure_semaphore

    start_hint_listener()
    console.print(
        "[dim]提示：解题过程中直接输入文字并回车，会作为提示注入正在运行的 agent。[/dim]"
    )
    max_containers = max_challenges * len(model_specs)
    configure_semaphore(max_containers)
    await cleanup_orphan_containers()

    challenge_path = Path(challenge_dir)
    meta_path = challenge_path / "metadata.yml"
    if not meta_path.exists():
        console.print(f"[red]No metadata.yml found in {challenge_dir}[/red]")
        sys.exit(1)

    if getattr(settings, "fresh_solve", False):
        # Evaluation mode: drop the solve workspace left by an earlier attempt so
        # the model cannot read a previous exploit script (or the flag in it).
        try:
            from backend.round_runner import _wipe_challenge_dirs

            if _wipe_challenge_dirs(str(challenge_path / "workspace")):
                console.print("[dim]fresh mode: cleared the previous workspace[/dim]")
        except Exception as e:  # noqa: BLE001 - cleaning is best effort
            console.print(f"[dim]fresh mode: could not clear the workspace: {e}[/dim]")

    meta = ChallengeMeta.from_yaml(meta_path)
    console.print(f"[bold]Challenge:[/bold] {meta.name} ({meta.category}, {meta.value} pts)")

    ctfd = make_platform(settings)

    # DASCTF targets live in remote environments: start one when needed.
    if hasattr(ctfd, "ensure_env") and not meta.connection_info:
        try:
            conn = await ctfd.ensure_env(meta.name)
        except Exception as e:  # noqa: BLE001 - never block a solve on this
            console.print(f"[yellow]Could not start the target environment: {e}[/yellow]")
            conn = ""
        if conn:
            meta.connection_info = conn
            console.print(f"[bold]Target:[/bold] {conn}")
            try:
                import yaml

                raw = yaml.safe_load(meta_path.read_text(encoding="utf-8")) or {}
                raw["connection_info"] = conn
                meta_path.write_text(
                    yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
                    encoding="utf-8",
                )
            except Exception as e:  # noqa: BLE001 - metadata refresh is best effort
                console.print(f"[dim]Could not update metadata.yml: {e}[/dim]")

    cost_tracker = CostTracker()

    swarm = ChallengeSwarm(
        challenge_dir=str(challenge_path),
        meta=meta,
        ctfd=ctfd,
        cost_tracker=cost_tracker,
        settings=settings,
        model_specs=model_specs,
        no_submit=no_submit,
    )

    try:
        timeout_min = float(getattr(settings, "challenge_timeout_min", 0) or 0)
        if timeout_min > 0:
            try:
                result = await asyncio.wait_for(swarm.run(), timeout=timeout_min * 60)
            except TimeoutError:
                console.print(f"[yellow]Timed out after {timeout_min:g} min[/yellow]")
                result = None
        else:
            result = await swarm.run()
        from backend.solver_base import FLAG_FOUND
        if result and result.status == FLAG_FOUND:
            console.print(f"\n[bold green]FLAG FOUND:[/bold green] {result.flag}")
            if getattr(settings, "writeup_enabled", False):
                try:
                    from backend import writeup as _writeup

                    wp = await _writeup.write(settings, meta, result)
                    if wp:
                        console.print(f"[dim]WP saved: {wp}[/dim]")
                except Exception as exc:  # noqa: BLE001 - never lose a solve
                    console.print(f"[yellow]WP failed: {exc}[/yellow]")
        else:
            console.print("\n[bold red]No flag found.[/bold red]")

        console.print("\n[bold]Cost Summary:[/bold]")
        for agent_name in cost_tracker.by_agent:
            console.print(f"  {agent_name}: {cost_tracker.format_usage(agent_name)}")
        console.print(f"  [bold]Total: ${cost_tracker.total_cost_usd:.2f}[/bold]")
    finally:
        await ctfd.close()


async def _run_coordinator(
    settings: Settings,
    model_specs: list[str],
    challenges_dir: str,
    no_submit: bool,
    coordinator_model: str | None,
    coordinator_backend: str,
    max_challenges: int,
    msg_port: int = 0,
) -> None:
    """Run the full coordinator (continuous until Ctrl+C)."""
    from backend.sandbox import cleanup_orphan_containers, configure_semaphore

    max_containers = max_challenges * len(model_specs)
    configure_semaphore(max_containers)
    await cleanup_orphan_containers()
    console.print(f"[bold]Starting coordinator ({coordinator_backend}, Ctrl+C to stop)...[/bold]\n")

    if coordinator_backend == "codex":
        from backend.agents.codex_coordinator import run_codex_coordinator
        results = await run_codex_coordinator(
            settings=settings,
            model_specs=model_specs,
            challenges_root=challenges_dir,
            no_submit=no_submit,
            coordinator_model=coordinator_model,
            msg_port=msg_port,
        )
    elif coordinator_backend == "deepseek":
        from backend.agents.deepseek_coordinator import run_deepseek_coordinator
        results = await run_deepseek_coordinator(
            settings=settings,
            model_specs=model_specs,
            challenges_root=challenges_dir,
            no_submit=no_submit,
            coordinator_model=coordinator_model,
            msg_port=msg_port,
        )
    else:
        from backend.agents.claude_coordinator import run_claude_coordinator
        results = await run_claude_coordinator(
            settings=settings,
            model_specs=model_specs,
            challenges_root=challenges_dir,
            no_submit=no_submit,
            coordinator_model=coordinator_model,
            msg_port=msg_port,
        )

    console.print("\n[bold]Final Results:[/bold]")
    for challenge, data in results.get("results", {}).items():
        console.print(f"  {challenge}: {data.get('flag', 'no flag')}")
    console.print(f"\n[bold]Total cost: ${results.get('total_cost_usd', 0):.2f}[/bold]")


@click.command()
@click.argument("message")
@click.option("--port", default=9400, type=int, help="Coordinator message port")
@click.option("--host", default="127.0.0.1", help="Coordinator host")
def msg(message: str, port: int, host: str) -> None:
    """Send a message to the running coordinator."""
    import json
    import urllib.request

    body = json.dumps({"message": message}).encode()
    req = urllib.request.Request(
        f"http://{host}:{port}/msg",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            console.print(f"[green]Sent:[/green] {data.get('queued', message[:200])}")
    except Exception as e:
        console.print(f"[red]Failed:[/red] {e}")
        console.print("Is the coordinator running?")
        sys.exit(1)


if __name__ == "__main__":
    main()
