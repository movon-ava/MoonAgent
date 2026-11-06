"""Per-model solver agent — one model, one container, one challenge."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import (
    ModelRequest,
    PartDeltaEvent,
    PartEndEvent,
    PartStartEvent,
    TextPart,
    ThinkingPart,
    UserPromptPart,
)
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.toolsets.abstract import ToolsetTool
from pydantic_ai.toolsets.wrapper import WrapperToolset
from rich.console import Console

from backend.cost_tracker import CostTracker
from backend.ctfd import CTFdClient
from backend import flagfmt
from backend.deps import SolverDeps
from backend.loop_detect import LOOP_WARNING_MESSAGE, LoopDetector
from backend.models import (
    model_id_from_spec,
    provider_from_spec,
    resolve_model,
    resolve_model_settings,
    supports_vision,
)
from backend.output_types import FlagFound
from backend.prompts import ChallengeMeta, build_prompt, list_distfiles, load_instructions
from backend.runtime import SolverSkipped
from backend.sandbox import DockerSandbox
from backend.solver_base import CANCELLED, ERROR, FLAG_FOUND, GAVE_UP, SolverResult
from backend.tools.flag import submit_flag
from backend.tools.sandbox import (
    bash,
    check_findings,
    list_files,
    notify_coordinator,
    read_file,
    web_fetch,
    webhook_create,
    webhook_get_requests,
    write_file,
)
from backend.tools.vision import view_image
from backend.tracing import SolverTracer

# DeepSeek (and other bilingual models) drift back to English reasoning on long
# agentic runs. The system prompt asks for Chinese; these two anchors keep it：
# `instructions` is re-sent with every request, and the reminder rides on every
# tool result.
THINK_CHINESE_RULE = (
    "始终用简体中文思考：你的 reasoning / thinking 内容必须是简体中文。"
    "shell 命令、代码、路径、flag、报错原文保持原样。"
)
THINK_CHINESE_REMINDER = (
    "[提醒：继续用简体中文思考（reasoning 必须是中文）；命令、代码、路径、flag 保持原样。]"
)

logger = logging.getLogger(__name__)

_console = Console()


def _clip(text: Any, limit: int = 240) -> str:
    """Collapse whitespace and truncate — one event must stay one line."""
    s = " ".join(str(text).split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


class SolverConsole:
    """Live view of a solver: thinking snippets, tool calls, tool results.

    Everything is prefixed with the challenge/model so concurrent solvers stay
    readable; full details still go to the JSONL trace file.
    """

    def __init__(self, label: str, show_thinking: bool = True) -> None:
        self.label = label
        self.show_thinking = show_thinking

    def _print(self, body: str) -> None:
        _console.print(f"[dim]{self.label}[/dim] {body}", highlight=False, soft_wrap=True)

    def tool_call(self, name: str, args: Any, step: int) -> None:
        self._print(f"[cyan]›[/cyan] [bold]{name}[/bold] [dim]{_clip(args, 180)}[/dim]")

    def tool_result(self, name: str, result: str, step: int) -> None:
        self._print(f"[green]‹[/green] [dim]{_clip(result, 200)}[/dim]")

    def thinking(self, text: str) -> None:
        if self.show_thinking and text.strip():
            self._print(f"[magenta]💭[/magenta] [dim italic]{_clip(text, 360)}[/dim italic]")

    def text(self, text: str) -> None:
        if text.strip():
            self._print(_clip(text, 500))



@dataclass
class TracingToolset(WrapperToolset[SolverDeps]):
    """Wraps a toolset to add per-call tracing and loop detection."""

    tracer: SolverTracer = field(repr=False)
    loop_detector: LoopDetector = field(repr=False)
    step_counter: list[int] = field(repr=False)
    console: SolverConsole | None = field(default=None, repr=False)
    challenge: str = field(default='', repr=False)

    async def call_tool(
        self, name: str, tool_args: dict[str, Any], ctx: RunContext[SolverDeps], tool: ToolsetTool[SolverDeps]
    ) -> Any:
        self.step_counter[0] += 1
        step = self.step_counter[0]

        if self.challenge:
            from backend import runtime

            if runtime.consume_skip(self.challenge):
                raise runtime.SolverSkipped(self.challenge)

        self.tracer.tool_call(name, tool_args, step)
        if self.console:
            self.console.tool_call(name, tool_args, step)

        # Loop detection
        loop_status = self.loop_detector.check(name, tool_args)
        if loop_status == "break":
            logger.warning(f"Loop break on {name} at step {step}")
            self.tracer.event("loop_break", tool=name, step=step)
            # Inject loop warning by returning it as the tool result
            return LOOP_WARNING_MESSAGE

        result = await self.wrapped.call_tool(name, tool_args, ctx, tool)

        result_str = str(result) if result is not None else ""
        self.tracer.tool_result(name, result_str, step)
        if self.console:
            self.console.tool_result(name, result_str, step)

        # Inject loop warning alongside result on "warn" level
        if loop_status == "warn":
            result = f"{result}\n\n{LOOP_WARNING_MESSAGE}" if isinstance(result, str) else result

        # Check for confirmed flag (startswith, so "INCORRECT" never matches)
        if name == "submit_flag":
            head = result_str.lstrip().upper()
            if head.startswith(("CORRECT", "ALREADY SOLVED")):
                self.tracer.event("flag_confirmed", tool=name, step=step)

        if step % 5 == 0 and ctx.deps.message_bus and isinstance(result, str):
            from backend.tools.core import do_check_findings
            findings_text = await do_check_findings(ctx.deps.message_bus, ctx.deps.model_spec)
            if findings_text and "No new findings" not in findings_text:
                result = f"{result}\n\n---\n{findings_text}"
                self.tracer.event("findings_injected", step=step)

        # Operator hint typed in the terminal while solving — sticky text the
        # model sees on its next step and must follow.
        if isinstance(result, str):
            from backend.hints import pop_hints

            hints = await pop_hints(self.challenge)
            if hints:
                joined = "\n".join(f"- {h}" for h in hints)
                result = (
                    f"{result}\n\n---\n[操作员提示 / OPERATOR HINT — follow this]"
                    f"\n{joined}"
                )
                self.tracer.event("hint_injected", count=len(hints), step=step)
                logger.info("Injected %d operator hint(s)", len(hints))

        # Models drift back to English on long runs — remind on every tool result.
        if (
            getattr(self.settings, "think_chinese", True)
            and isinstance(result, str)
            and result.strip()
        ):
            result = f"{result}\n\n{THINK_CHINESE_REMINDER}"

        return result


def _build_toolset(deps: SolverDeps) -> FunctionToolset[SolverDeps]:
    """Build the raw toolset for a solver agent."""
    tools = [bash, read_file, write_file, list_files, submit_flag, web_fetch,
             webhook_create, webhook_get_requests, check_findings, notify_coordinator]
    if deps.use_vision:
        tools.append(view_image)
    return FunctionToolset(tools=tools, max_retries=4)


class Solver:
    """A single solver: one model, one container, one challenge."""

    def __init__(
        self,
        model_spec: str,
        challenge_dir: str,
        meta: ChallengeMeta,
        ctfd: CTFdClient,
        cost_tracker: CostTracker,
        settings: object,
        cancel_event: asyncio.Event | None = None,
        sandbox: DockerSandbox | None = None,
        owns_sandbox: bool | None = None,
    ) -> None:
        self.model_spec = model_spec
        self.model_id = model_id_from_spec(model_spec)
        self.challenge_dir = challenge_dir
        self.meta = meta
        self.ctfd = ctfd
        self.cost_tracker = cost_tracker
        self.settings = settings
        self.cancel_event = cancel_event or asyncio.Event()
        self._owns_sandbox = owns_sandbox if owns_sandbox is not None else (sandbox is None)

        self.sandbox = sandbox or DockerSandbox(
            image=getattr(settings, "sandbox_image", "ctf-sandbox"),
            challenge_dir=challenge_dir,
            memory_limit=getattr(settings, "container_memory_limit", "4g"),
        )
        self.use_vision = supports_vision(model_spec)
        self.deps = SolverDeps(
            sandbox=self.sandbox,
            ctfd=ctfd,
            challenge_dir=challenge_dir,
            challenge_name=meta.name,
            workspace_dir="",
            use_vision=self.use_vision,
            cost_tracker=cost_tracker,
            connection_info=str(getattr(meta, "connection_info", "") or ""),
            needs_target=bool(getattr(meta, "has_container", False))
            or any(k in str(getattr(meta, "category", "") or "").lower() for k in ("web", "pwn", "二进制", "渗透")),
        )
        self.loop_detector = LoopDetector()
        self.tracer = SolverTracer(meta.name, self.model_id)
        self.agent_name = f"{meta.name}/{self.model_id}"
        self.console = SolverConsole(self.agent_name)
        self._agent: Agent[SolverDeps, FlagFound] | None = None
        self._messages: list = []
        self._step_count = [0]  # mutable ref shared with TracingToolset
        self._flag: str | None = None
        self._confirmed: bool = False
        self._findings: str = ""

    async def start(self) -> None:
        """Start the sandbox and build the agent."""
        if not self.sandbox._container:
            await self.sandbox.start()
        self.deps.workspace_dir = self.sandbox.workspace_dir

        arch_result = await self.sandbox.exec("uname -m", timeout_s=10)
        container_arch = arch_result.stdout.strip() or "unknown"

        distfile_names = list_distfiles(self.challenge_dir)
        system_prompt = build_prompt(
            self.meta,
            distfile_names,
            container_arch=container_arch,
            platform_instructions=load_instructions(
                getattr(self.settings, "instructions_file", None)
            ),
            think_chinese=bool(getattr(self.settings, "think_chinese", True)),
            flag_hint=flagfmt.describe(
                getattr(self.settings, "flag_format", "") or "",
                getattr(self.settings, "flag_submit_mode", "full") or "full",
            ),
        )

        model = resolve_model(self.model_spec, self.settings)
        model_settings = resolve_model_settings(self.model_spec)
        raw_toolset = _build_toolset(self.deps)
        toolset = TracingToolset(
            wrapped=raw_toolset,
            tracer=self.tracer,
            loop_detector=self.loop_detector,
            step_counter=self._step_count,
            console=self.console,
            challenge=self.meta.name,
        )

        self._agent = Agent(
            model,
            deps_type=SolverDeps,
            system_prompt=system_prompt,
            model_settings=model_settings,
            toolsets=[toolset],
            output_type=FlagFound,
        )

        self.tracer.event(
            "start",
            challenge=self.meta.name,
            model=self.model_id,
            category=self.meta.category,
            value=self.meta.value,
            difficulty=next(
                (t for t in (self.meta.tags or []) if t in ("入门", "简单", "中等", "困难")), ""
            ),
        )

        # Let the web UI inject hints through logs/hints/<challenge>.jsonl.
        try:
            from backend.hints import start_file_hint_watcher

            start_file_hint_watcher(self.meta.name)
        except Exception:
            pass
        logger.info(f"[{self.agent_name}] Solver started")

    async def _stream_events(self, ctx: RunContext[SolverDeps], events: Any) -> None:
        """Print the model's thinking / narration live, one entry per part."""
        kind = ""
        buf = ""
        try:
            async for ev in events:
                if isinstance(ev, PartStartEvent):
                    kind = type(ev.part).__name__
                    buf = ""
                elif isinstance(ev, PartDeltaEvent):
                    chunk = getattr(ev.delta, "content_delta", None)
                    if chunk:
                        buf += chunk
                elif isinstance(ev, PartEndEvent):
                    part = ev.part
                    text = getattr(part, "content", "") or buf
                    if isinstance(part, ThinkingPart):
                        self.console.thinking(text)
                        self.tracer.thinking(text)
                    elif isinstance(part, TextPart):
                        self.console.text(text)
                        self.tracer.message(text)
                    buf = ""
        except Exception:  # noqa: BLE001 - printing must never break solving
            logger.debug("console stream printing failed", exc_info=True)

    async def run_until_done_or_gave_up(self) -> SolverResult:
        """Run the solver loop until flag found, gave up, or cancelled."""
        if not self._agent:
            await self.start()
        assert self._agent is not None

        t0 = time.monotonic()
        steps_before = self._step_count[0]

        try:
            from pydantic_ai.usage import UsageLimits

            async def _run_once():
                return await self._agent.run(
                    "Solve this CTF challenge." if not self._messages else "Continue solving.",
                    deps=self.deps,
                    message_history=self._messages if self._messages else None,
                    usage_limits=UsageLimits(request_limit=None),
                    event_stream_handler=self._stream_events,
                    instructions=(
                        THINK_CHINESE_RULE
                        if getattr(self.settings, "think_chinese", True)
                        else None
                    ),
                )

            try:
                result = await _run_once()
            except Exception as exc:  # noqa: BLE001 - retry once without the offending image
                text = str(exc).lower()
                if "unsupported image" not in text and "image is valid" not in text:
                    raise
                logger.warning(
                    f"[{self.agent_name}] Vision rejected an image; dropping images and retrying once"
                )
                self._messages = self._strip_images(self._messages)
                result = await _run_once()

            duration = time.monotonic() - t0
            usage = result.usage

            self.cost_tracker.record(
                self.agent_name, usage, self.model_id,
                provider_spec=provider_from_spec(self.model_spec),
                duration_seconds=duration,
            )

            agent_usage = self.cost_tracker.by_agent.get(self.agent_name)

            # Track spend per model spec so configured budgets actually bind.
            try:
                from backend import quota
                from backend.cost_tracker import calc_cost

                quota.add_spend(
                    self.model_spec,
                    calc_cost(usage, self.model_id, provider_from_spec(self.model_spec)),
                )
            except Exception:  # noqa: BLE001 - quota accounting must never break solving
                pass

            self.tracer.usage(
                usage.input_tokens, usage.output_tokens,
                usage.cache_read_tokens,
                agent_usage.cost_usd if agent_usage else 0.0,
            )

            self._messages = result.all_messages()

            # Trace model responses from new messages
            from pydantic_ai.messages import ModelResponse, TextPart
            for msg in result.new_messages():
                if isinstance(msg, ModelResponse):
                    text_parts = [p.content for p in msg.parts if isinstance(p, TextPart)]
                    text = " ".join(text_parts)
                    msg_usage = msg.usage
                    self.tracer.model_response(
                        text[:500], self._step_count[0],
                        input_tokens=msg_usage.input_tokens if msg_usage else 0,
                        output_tokens=msg_usage.output_tokens if msg_usage else 0,
                    )

            output = result.output
            if isinstance(output, FlagFound):
                self._flag = output.flag
                self._findings = f"Flag found via {output.method}: {output.flag}"
                # In dry-run mode, structured output is sufficient (can't verify via CTFd)
                if self.deps.no_submit:
                    self._confirmed = True
            # CTFd confirmation always counts (the primary path when not in dry-run)
            if self.deps.confirmed_flag:
                self._confirmed = True
                self._flag = self._flag or self.deps.confirmed_flag

            if self._confirmed and self._flag:
                return self._result(FLAG_FOUND)
            if self.deps.practice_mode and isinstance(output, FlagFound) and output.flag:
                # Already-solved practice run: nothing can verify the flag, but the
                # solver did the work and reported one, so count it (unverified).
                self._flag = self._flag or output.flag
                self._findings = f"Flag (unverified practice run): {self._flag}"
                return self._result(FLAG_FOUND)
            return self._result(GAVE_UP)

        except SolverSkipped:
            logger.info(f'[{self.agent_name}] Skipped by operator')
            self.tracer.event('skipped', challenge=self.meta.name)
            return self._result('skipped')
        except asyncio.CancelledError:
            return self._result(CANCELLED)
        except Exception as e:
            logger.error(f"[{self.agent_name}] Error: {e}", exc_info=True)
            self._findings = f"Error: {e}"
            self.tracer.event("error", error=str(e))
            return self._result(ERROR)

    @staticmethod
    def _strip_images(messages):
        """Remove BinaryContent parts from a pydantic-ai message list."""
        import copy

        from pydantic_ai.messages import BinaryContent

        cleaned = copy.deepcopy(messages)
        for msg in cleaned:
            parts = getattr(msg, "parts", None)
            if not parts:
                continue
            kept = [p for p in parts if not isinstance(getattr(p, "content", None), BinaryContent)]
            if len(kept) != len(parts):
                try:
                    msg.parts = kept  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001 - frozen dataclasses can be skipped
                    pass
        return cleaned

    def bump(self, insights: str) -> None:
        """Inject insights from siblings and prepare to resume."""
        bump_msg = ModelRequest(
            parts=[
                UserPromptPart(
                    content=(
                        "Your previous attempt did not find the flag. Here are insights "
                        "from other agents working on the same challenge:\n\n"
                        f"{insights}\n\n"
                        "Use these insights to try a different approach. "
                        "Do NOT repeat what has already been tried."
                    )
                )
            ]
        )
        self._messages.append(bump_msg)
        self.loop_detector.reset()
        self.tracer.event("bump", insights=insights[:500])
        logger.info(f"[{self.agent_name}] Bumped with sibling insights")

    def _result(self, status: str, run_steps: int | None = None, run_cost: float | None = None) -> SolverResult:
        agent_usage = self.cost_tracker.by_agent.get(self.agent_name)
        cost = agent_usage.cost_usd if agent_usage else 0.0
        self.tracer.event("finish", status=status, flag=self._flag, confirmed=self._confirmed, cost_usd=round(cost, 4))
        return SolverResult(
            flag=self._flag,
            status=status,
            findings_summary=self._findings[:2000],
            step_count=run_steps if run_steps is not None else self._step_count[0],
            cost_usd=run_cost if run_cost is not None else cost,
            log_path=self.tracer.path,
        )

    async def stop(self) -> None:
        self.tracer.event("stop", step_count=self._step_count[0])
        self.tracer.close()
        if self._owns_sandbox and self.sandbox:
            await self.sandbox.stop()
