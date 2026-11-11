"""Local web control panel for ctf-agent.

One command starts everything; every other setting is configured in the
browser:

    uv run python scripts/webui.py            # http://127.0.0.1:8099
    uv run python scripts/webui.py --port 8100

Two pages:

* **配置** — model settings (keys, base URL, model picks), platform settings
  (DASCTF / Ret2Shell / CTFd plus that platform's URL and token), and solving
  settings (how many challenges, concurrency, categories, difficulty, order).
* **解题** — run control plus a picker for watching one solver at a time while
  several run concurrently; each solver has a hint box.

No extra dependencies — stdlib HTTP server only.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("ctf-webui")
sys.path.insert(0, str(ROOT))

from backend import quota, runtime  # noqa: E402
from backend import settings_schema as _schema  # noqa: E402
from backend.config import Settings  # noqa: E402
from backend.hints import append_hint, hint_file_for  # noqa: E402
from backend.models import DEFAULT_MODELS  # noqa: E402
from backend.platform import make_platform, platform_kind  # noqa: E402
from backend.providers import (  # noqa: E402
    add_extra_models,
    delete_provider,
    fetch_models,
    known_model_specs,
    load_store,
    set_provider_models,
    upsert_provider,
)
from backend.ret2shell import matches_categories  # noqa: E402

TRACE_DIR = ROOT / "logs"
ENV_FILE = ROOT / ".env"
RUN_LOG = TRACE_DIR / "webui-run.log"
TAIL_BYTES = 400_000
ACTIVE_WINDOW_S = 90.0
# Traces touched before this process started belong to earlier sessions (or to
# runs this dashboard never watched). They are hidden so a restart starts with
# a clean slate instead of replaying every historical smoke test.
WEBUI_STARTED_AT = time.time()
_BALANCE_CACHE: dict = {"at": 0.0, "data": None}


def _deepseek_balance() -> dict:
    """DeepSeek's official balance (same number as the website's 充值余额)."""
    now = time.time()
    if _BALANCE_CACHE["data"] is not None and now - _BALANCE_CACHE["at"] < 60:
        return _BALANCE_CACHE["data"]
    settings = Settings()
    key = settings.deepseek_api_key
    if not key:
        data: dict = {"ok": False, "error": "未配置 DEEPSEEK_API_KEY"}
    else:
        try:
            import urllib.request

            url = settings.deepseek_base_url.rstrip("/") + "/user/balance"
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            infos = body.get("balance_infos") or []
            info = infos[0] if infos else {}
            data = {
                "ok": True,
                "available": bool(body.get("is_available")),
                "currency": info.get("currency") or "CNY",
                "total": info.get("total_balance"),
                "granted": info.get("granted_balance"),
                "topped_up": info.get("topped_up_balance"),
            }
            try:
                quota.record_balance(float(data["total"]))
                data["spent"] = quota.balance_info().get("spent_cny")
            except (TypeError, ValueError):
                logger.debug("suppressed exception", exc_info=True)
        except Exception as exc:  # noqa: BLE001 - the chip just shows nothing
            data = {"ok": False, "error": f"余额查询失败: {exc}"}
    _BALANCE_CACHE.update(at=now, data=data)
    return data

# Model specs offered as checkboxes. The configured default is always added.
MODEL_CHOICES = [
    "deepseek/deepseek-flash",
    "deepseek/deepseek-flash/low",
    "deepseek/deepseek-flash/max",
    "deepseek/deepseek-v4-pro",
    *DEFAULT_MODELS,
]

PLATFORM_LABELS = {
    "dasctf": "DASCTF / 羊城杯",
    "ctf2": "CTF² Agent Arena",
    "ctfplus": "CTF+ / 极客挑战赛",
    "ret2shell": "Ret2Shell / 西电 MoeCTF",
    "ctfd": "CTFd",
    "auto": "自动（按凭据猜测）",
}


def _mask(value: str) -> str:
    value = value or ""
    if len(value) <= 8:
        return "•" * len(value)
    return value[:4] + "•" * (len(value) - 8) + value[-4:]


def _config_view() -> dict:
    """Current settings, with secrets masked, plus model choices."""
    s = Settings()
    configured = [m.strip() for m in (s.default_models or "").split(",") if m.strip()]
    choices = list(dict.fromkeys([*configured, *MODEL_CHOICES, *known_model_specs()]))
    resolved = platform_kind(s)
    return {
        "platform": s.platform,
        "resolved_platform": resolved,
        "resolved_platform_label": PLATFORM_LABELS.get(resolved, resolved),
        "platform_labels": PLATFORM_LABELS,
        "models": configured,
        "model_choices": choices,
        "round_size": s.round_size,
        "max_concurrent": s.max_concurrent_challenges,
        "challenge_timeout_min": s.challenge_timeout_min,
        "challenge_extra_rounds": s.challenge_extra_rounds,
        "max_environments": s.max_environments,
        "categories": s.challenge_categories,
        "difficulty": s.challenge_difficulty,
        "round_order": s.round_order,
        "round_only": s.round_only,
        "min_score": s.round_min_score,
        "include_solved": s.round_include_solved,
        "writeup_enabled": bool(s.writeup_enabled),
        "flag_format": s.flag_format,
        "flag_submit_mode": s.flag_submit_mode,
        "think_chinese": bool(s.think_chinese),
        "require_flag_evidence": bool(s.require_flag_evidence),
        "skip_solved_pull": bool(s.skip_solved_pull),
        "trace_mask": bool(s.trace_mask),
        "fresh_solve": bool(s.fresh_solve),
        "skills_enabled": bool(getattr(s, "skills_enabled", True)),
        "round_rotate": s.round_rotate,
        "blitz_mode": bool(getattr(s, "blitz_mode", False)),
        "rotate_batch": s.rotate_batch,
        "ret2shell_url": s.ret2shell_url,
        "ret2shell_token_set": bool(s.ret2shell_token),
        "ret2shell_token_masked": _mask(s.ret2shell_token),
        "ret2shell_game": s.ret2shell_game,
        "dasctf_url": s.dasctf_url,
        "dasctf_access_key_set": bool(s.dasctf_access_key),
        "dasctf_access_key_masked": _mask(s.dasctf_access_key),
        "ctf2_url": s.ctf2_url,
        "ctf2_token_set": bool(s.ctf2_token),
        "ctf2_token_masked": _mask(s.ctf2_token),
        "ctf2_ground": s.ctf2_ground,
        "ctfplus_url": s.ctfplus_url,
        "ctfplus_token_set": bool(s.ctfplus_token),
        "ctfplus_token_masked": _mask(s.ctfplus_token),
        "ctfd_url": s.ctfd_url,
        "ctfd_token_set": bool(s.ctfd_token),
        "ctfd_token_masked": _mask(s.ctfd_token),
        "deepseek_api_key_set": bool(s.deepseek_api_key),
        "deepseek_api_key_masked": _mask(s.deepseek_api_key),
        "deepseek_base_url": s.deepseek_base_url,
        "instructions_file": s.instructions_file,
        "providers": _providers_view(),
        "quotas": quota.view(),
    }


def _providers_view() -> list[dict]:
    """Registered custom providers, API keys masked."""
    out = []
    for prov in load_store()["providers"]:
        key = str(prov.get("api_key") or "")
        out.append({
            "name": prov.get("name", ""),
            "base_url": prov.get("base_url", ""),
            "api_key_set": bool(key),
            "api_key_masked": _mask(key),
            "models": list(prov.get("models") or []),
        })
    return out


# Keys the form may write back into .env. The canonical table lives in
# backend/settings_schema.py so the panel, .env.example and the CLI cannot drift
# apart (scripts/test_settings_schema.py fails when they do).
_ENV_KEYS = _schema.form_env_keys()
SECRET_FIELDS = tuple(_schema.SECRET_FIELDS)


def _render_env_value(key: str, value) -> str:
    setting = _schema.setting_for(key)
    if setting is None:
        return "" if value is None else str(value)
    return _schema.render_env_value(setting, value)


def _is_placeholder(value: str) -> bool:
    """True for the masked echo the panel shows for an already saved secret."""
    return any(ch in value for ch in ("•", "…", "*"))


def _validate_payload(payload: dict) -> None:
    """Catch credentials pasted into the wrong box before they reach ``.env``.

    Only checks the DASCTF box when DASCTF is actually the chosen platform: the
    form submits every field it can read, including ones hidden for other
    platforms, and a stale value there used to block saving on CTF+.
    """
    platform = str(payload.get("platform") or "").strip().lower()
    if platform and platform != "dasctf":
        return
    key = str(payload.get("dasctf_access_key") or "").strip()
    if not key or _is_placeholder(key):
        return
    if "://" in key or not key.startswith("ak_"):
        raise ValueError(
            "DASCTF AccessKey 应该是运行环境页里的 ak_live_… 密钥，不是站点地址；"
            "站点地址请填在 SERVER HOST 里"
        )


def _scrub_bogus_secrets() -> None:
    """Clear credentials that are obviously not credentials (pasted URLs)."""
    if not ENV_FILE.exists():
        return
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    changed: list[str] = []
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            field = _schema.BY_ENV.get(name.strip())
            field_name = field.field if field else ""
            if field_name == "dasctf_access_key" and "://" in value:
                out.append(f"{name}=")
                changed.append("DASCTF_ACCESS_KEY")
                continue
        out.append(line)
    if changed:
        ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"cleared {', '.join(changed)}: it held a URL, not a key")


def save_config(payload: dict) -> None:
    """Merge the form payload into ``.env`` (create it if missing).

    Secret fields are left untouched when the payload sends an empty string, so
    a masked value is never written back over the real one.
    """
    _validate_payload(payload)
    updates: dict[str, str] = {}
    for key, env_name in _ENV_KEYS.items():
        if key not in payload:
            continue
        if key in SECRET_FIELDS and not str(payload.get(key) or "").strip():
            continue
        updates[env_name] = _render_env_value(key, payload.get(key))

    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in line:
            name = line.split("=", 1)[0].strip()
            if name in updates:
                out.append(f"{name}={updates[name]}")
                seen.add(name)
                continue
        out.append(line)
    for name, value in updates.items():
        if name not in seen:
            out.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")


def _preflight(platform: str) -> str:
    """Return an error message when the chosen platform is not usable yet."""
    s = Settings()
    if platform == "dasctf":
        if not s.dasctf_access_key.strip():
            return "DASCTF 需要 Access Key：请到 配置 → 平台配置 里填写"
        if not s.dasctf_url.strip():
            return "DASCTF 需要服务器地址（SERVER HOST）"
    elif platform == "ret2shell":
        if not s.ret2shell_token.strip():
            return "Ret2Shell 需要登录 Token：请到 配置 → 平台配置 里填写"
    elif platform == "ctfplus":
        if not s.ctfplus_token.strip():
            return "CTF+ 需要 SessionStore cookie 值（CTFPLUS_TOKEN）：请到 配置 → 平台配置 里填写"
        if not s.ctfplus_url.strip():
            return "CTF+ 需要站点地址（例如 https://geek2026.play.ctfplus.cn）"
    elif platform == "ctf2":
        if not s.ctf2_token.strip():
            return "CTF² 需要 Agent Token（CTF2_AGENT_TOKEN）：请到 配置 → 平台配置 里填写"
        if not s.ctf2_url.strip():
            return "CTF² 需要服务器地址（默认 https://ctf2.dasctf.com）"
    elif platform == "ctfd":
        if not s.ctfd_url.strip():
            return "CTFd 需要 URL"
    elif platform == "auto":
        return "请明确选择平台（自动模式会按已有凭据猜测，容易拉错比赛）"
    else:
        return f"未知平台: {platform}"
    if not s.deepseek_api_key.strip() and not any(
        m.startswith(("claude-sdk/", "codex/")) for m in _configured_models(s)
    ):
        return "没有可用的模型凭据：请填写 DeepSeek API Key，或选择 claude-sdk/codex 模型"
    return ""


def _configured_models(s: Settings) -> list[str]:
    return [m.strip() for m in (s.default_models or "").split(",") if m.strip()]


class RunManager:
    """Owns the single ``ctf-solve`` child process the panel can launch."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._log = None
        self._started_at = 0.0
        self._argv: list[str] = []

    def status(self) -> dict:
        with self._lock:
            proc = self._proc
            running = proc is not None and proc.poll() is None
            return {
                "running": running,
                "pid": proc.pid if running else None,
                "exit_code": None if running or proc is None else proc.poll(),
                "started_at": self._started_at if proc else 0,
                "argv": self._argv,
                "log": RUN_LOG.name,
                "concurrency": runtime.get_concurrency(),
            }

    def start(self, payload: dict) -> dict:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                if not payload.get("restart"):
                    return {
                        "ok": False,
                        "error": "已有一个解题进程在运行（已有轮次）：点「停止」后重试，"
                        "或在弹窗里确认自动停掉它再开始新的",
                    }
                logger.info("restart: stopping the previous run first")
                self._stop_locked()
            save_config(payload)
            platform = str(payload.get("platform") or Settings().platform or "auto").strip()
            error = _preflight(platform)
            if error:
                return {"ok": False, "error": error}
            wanted = payload.get("models") or _configured_models(Settings())
            usable = [m for m in wanted if quota.available(m)]
            if wanted and not usable:
                return {
                    "ok": False,
                    "error": "选中的模型额度已用尽：到 配置 → 模型配置 调高限额，或把已用额度清零",
                }
            # A previous run may have died leaving a platform target open.
            _close_platform_envs()
            argv = _build_argv(payload)
            try:
                runtime.set_concurrency(int(payload.get("max_concurrent") or 1))
            except (TypeError, ValueError):
                runtime.set_concurrency(1)
            TRACE_DIR.mkdir(parents=True, exist_ok=True)
            self._log = open(RUN_LOG, "ab")
            self._log.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
            self._log.write((" ".join(argv) + "\n").encode())
            self._log.flush()
            self._proc = subprocess.Popen(
                argv,
                cwd=str(ROOT),
                stdout=self._log,
                stderr=subprocess.STDOUT,
                start_new_session=(os.name != "nt"),
            )
            self._started_at = time.time()
            self._argv = argv
            board_invalidate()
            return {"ok": True, "pid": self._proc.pid, "argv": argv}

    def stop(self) -> dict:
        with self._lock:
            return self._stop_locked()

    def _stop_locked(self) -> dict:
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return {"ok": True, "stopped": False}
        _kill_tree(proc.pid)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _kill_tree(proc.pid)
        # The solver processes are gone, so any sandbox container still
        # carrying our label is a leftover - free it before the next run
        # hits the memory ceiling.
        _cleanup_containers()
        try:
            from backend import wsrx

            wsrx.close_all()
        except Exception:  # noqa: BLE001
            logger.debug("suppressed exception in stop", exc_info=True)
        # taskkill /T /F skips the CLI's finally, so close the platform
        # targets from here - otherwise the container quota stays used.
        _close_platform_envs()
        return {"ok": True, "stopped": True}


def _close_platform_envs() -> None:
    """Run scripts/close_envs.py so killed runs do not leak platform targets."""
    try:
        subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "close_envs.py")],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001 - never break the stop button
        logger.debug("suppressed exception in _close_platform_envs", exc_info=True)


def _cleanup_containers() -> None:
    """Remove leftover ctf-agent sandboxes (used after a run is killed)."""
    code = (
        "import asyncio;"
        "from backend.sandbox import cleanup_orphan_containers;"
        "asyncio.run(cleanup_orphan_containers(0, force=True))"
    )
    try:
        subprocess.Popen(
            [sys.executable, "-c", code],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=(os.name != "nt"),
        )
    except Exception:  # noqa: BLE001 - cleanup is best effort
        logger.debug("suppressed exception in _cleanup_containers", exc_info=True)


def _prune_logs() -> None:
    """Trim old traces/snapshots so ``logs/`` does not grow forever."""
    try:
        from backend.maintenance import prune_logs

        removed = prune_logs()
        if removed["traces"] or removed["runs"]:
            print(
                f"pruned {removed['traces']} trace(s), {removed['runs']} run(s), "
                f"{removed['bytes'] / 1_048_576:.1f} MB"
            )
    except Exception as exc:  # noqa: BLE001 - housekeeping must not block startup
        print(f"log prune skipped: {exc}")


def _kill_tree(pid: int) -> None:
    """Kill a process and everything it spawned.

    ``uv run`` launches the solver as a grandchild, so terminating only the
    direct child leaves the solver running; ``backend.procs`` knows the platform
    specific details (``taskkill /T`` on Windows, process groups on POSIX).
    """
    from backend import procs

    procs.kill_tree(pid)


def _build_argv(payload: dict) -> list[str]:
    """Translate a config payload into a ``uv run ctf-solve`` command line."""
    argv = ["uv", "run", "ctf-solve", "-v"]

    platform = str(payload.get("platform") or "auto")
    argv += ["--platform", platform]

    models = [str(m).strip() for m in (payload.get("models") or []) if str(m).strip()]
    for spec in models:
        argv += ["--models", spec]

    try:
        round_size = int(payload.get("round_size") or 0)
    except (TypeError, ValueError):
        round_size = 0
    if round_size > 0:
        argv += ["--round", str(round_size)]
    if payload.get("blitz_mode"):
        # Blitz is a round-mode feature: without --round the CLI starts the
        # coordinator, which would defeat "sweep the pool easy to hard".
        if round_size <= 0:
            argv += ["--round", "999"]
        argv.append("--blitz")
    picks = [str(p).strip() for p in (payload.get("pick") or []) if str(p).strip()]
    if picks:
        # Picking is round-mode only: the coordinator cannot be limited to a list.
        if round_size <= 0:
            argv += ["--round", str(len(picks))]
        for name in picks:
            argv += ["--pick", name]
    resume = str(payload.get("resume") or "").strip()
    if resume:
        argv += ["--resume", resume]

    try:
        concurrent = int(payload.get("max_concurrent") or 1)
    except (TypeError, ValueError):
        concurrent = 1
    argv += ["--max-challenges", str(max(1, concurrent))]

    try:
        timeout_min = float(payload.get("challenge_timeout_min") or 0)
    except (TypeError, ValueError):
        timeout_min = 0.0
    if timeout_min > 0:
        argv += ["--challenge-timeout", f"{timeout_min:g}"]

    try:
        extra_rounds = int(payload.get("challenge_extra_rounds") or 0)
    except (TypeError, ValueError):
        extra_rounds = 0
    if extra_rounds > 0:
        argv += ["--extra-rounds", str(extra_rounds)]

    categories = str(payload.get("categories") or "").strip()
    if categories:
        argv += ["--categories", categories]
    difficulty = str(payload.get("difficulty") or "").strip()
    if difficulty:
        argv += ["--difficulty", difficulty]

    order = str(payload.get("round_order") or payload.get("order") or "random").strip()
    argv += ["--order", order or "random"]
    if payload.get("writeup_enabled"):
        argv.append("--writeup")
    if not payload.get("think_chinese", True):
        argv.append("--no-think-chinese")
    if not payload.get("skip_solved_pull", True):
        argv.append("--no-skip-solved")
    if not payload.get("require_flag_evidence", True):
        argv.append("--no-require-evidence")
    if not payload.get("trace_mask", True):
        argv.append("--no-trace-mask")
    if payload.get("fresh_solve"):
        argv.append("--fresh")
    if not payload.get("skills_enabled", True):
        argv.append("--no-skills")
    fmt = str(payload.get("flag_format") or "").strip()
    if fmt:
        argv += ["--flag-format", fmt]
    argv += ["--flag-submit-mode", str(payload.get("flag_submit_mode") or "full")]
    if payload.get("include_solved"):
        argv.append("--include-solved")
    if payload.get("round_rotate"):
        argv.append("--rotate")
    try:
        rotate_batch = int(payload.get("rotate_batch") or 0)
    except (TypeError, ValueError):
        rotate_batch = 0
    if rotate_batch > 0:
        argv += ["--rotate-batch", str(rotate_batch)]
    try:
        max_env = int(payload.get("max_environments") or 0)
    except (TypeError, ValueError):
        max_env = 0
    argv += ["--max-env", str(max(0, max_env))]
    if payload.get("no_submit"):
        argv.append("--no-submit")

    only = str(payload.get("only") or "").strip()
    if only:
        for part in only.split(","):
            part = part.strip()
            if part:
                argv += ["--only", part]

    ground = str(payload.get("ctf2_ground") or "").strip()
    if platform == "ctf2" and ground:
        argv += ["--ctf2-ground", ground]
    return argv


RUN = RunManager()


_TRACE_CACHE: dict[str, tuple[float, int, dict]] = {}


def _parse_trace(path: Path, stat: os.stat_result | None = None) -> dict:
    """Return {"challenge", "model", "mtime", "events": [...]} for one trace."""
    try:
        st = stat or path.stat()
        size, mtime = st.st_size, st.st_mtime
        cached = _TRACE_CACHE.get(str(path))
        if cached and cached[0] == mtime and cached[1] == size:
            return cached[2]
        with path.open("rb") as f:
            f.seek(max(0, size - TAIL_BYTES))
            chunk = f.read().decode("utf-8", "replace").lstrip("\ufeff")
    except OSError:
        return {}

    events: list[dict] = []
    challenge = model = ""
    category = difficulty = ""
    value = 0
    finished = False
    started_at = 0.0
    for line in chunk.splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "start":
            challenge = ev.get("challenge") or challenge
            if not started_at and isinstance(ev.get("ts"), (int, float)):
                started_at = float(ev["ts"])
            model = ev.get("model") or model
            category = ev.get("category") or category
            difficulty = ev.get("difficulty") or difficulty
            try:
                value = int(ev.get("value") or value)
            except (TypeError, ValueError):
                logger.debug("suppressed exception", exc_info=True)
        elif ev.get("type") == "finish":
            finished = True
        events.append(ev)

    events = events[-60:]
    if not challenge:
        name = path.stem[len("trace-"):]
        parts = name.rsplit("-", 2)
        left = parts[0] if len(parts) == 3 else name
        if "-" in left:
            challenge, model = left.rsplit("-", 1)
        else:
            challenge = left
    data = {
        "challenge": challenge or path.stem,
        "model": model,
        "category": category,
        "value": value,
        "difficulty": difficulty,
        "mtime": mtime,
        "started_at": started_at or mtime,
        "active": (not finished) and (time.time() - mtime) < ACTIVE_WINDOW_S,
        "finished": finished,
        "since": time.strftime("%H:%M", time.localtime(started_at or mtime)),
        "file": path.name,
        "events": events,
    }
    _TRACE_CACHE[str(path)] = (mtime, size, data)
    return data


META_INDEX: dict = {"at": 0.0, "data": {}}
DIFFICULTY_TAGS = ("入门", "简单", "中等", "困难")


def _challenge_meta_index() -> dict[str, dict]:
    """challenge name (lower) -> {category, value, difficulty} from challenges/*/metadata.yml."""
    now = time.time()
    if META_INDEX["data"] and now - META_INDEX["at"] < 5.0:
        return META_INDEX["data"]
    index: dict[str, dict] = {}
    root = ROOT / "challenges"
    if root.exists():
        try:
            import yaml
        except ImportError:  # pragma: no cover
            yaml = None
        if yaml is not None:
            for meta_path in root.glob("*/metadata.yml"):
                try:
                    with open(meta_path, encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                except Exception:
                    continue
                name = str(data.get("name") or meta_path.parent.name).strip().lower()
                tags = [str(t) for t in (data.get("tags") or [])]
                index[name] = {
                    "category": str(data.get("category") or ""),
                    "value": int(data.get("value") or 0),
                    "difficulty": next((t for t in tags if t in DIFFICULTY_TAGS), ""),
                }
    META_INDEX["at"] = now
    META_INDEX["data"] = index
    return index


def collect(include_idle: bool = False) -> list[dict]:
    out = []
    if not TRACE_DIR.exists():
        return out
    meta_index = _challenge_meta_index()
    cutoff = WEBUI_STARTED_AT - 5
    for path in sorted(TRACE_DIR.glob("trace-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        # Cheap pre-filter first: parsing a 400 KB tail of every historical
        # trace on every 1.5 s poll cost seconds of disk IO once logs/ filled up.
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_mtime < cutoff:
            continue
        data = _parse_trace(path, st)
        if not data:
            continue
        # Ignore traces left over from before this dashboard (re)started — a
        # restart should not resurrect old smoke tests in the sidebar.
        begun = float(data.get("started_at") or data.get("mtime") or 0.0)
        if begun < WEBUI_STARTED_AT - 5:
            continue
        if not include_idle and not data["active"]:
            continue
        if not data.get("category") or not data.get("value"):
            meta = meta_index.get(str(data.get("challenge") or "").strip().lower())
            if meta:
                data["category"] = data.get("category") or meta["category"]
                data["value"] = data.get("value") or meta["value"]
                data["difficulty"] = data.get("difficulty") or meta["difficulty"]
        out.append(data)
        if len(out) >= 12:
            break
    # Keep a stable order: newest run first, and never reshuffle just because a
    # solver produced another event (that made rows jump up and down).
    out.sort(key=lambda d: (-float(d.get("started_at") or d.get("mtime") or 0), str(d.get("file") or "")))
    return out


# --------------------------------------------------------------------------
# Challenge board: every challenge of the current batch as a small square.
# Green = solved, blue ring = a solver is working on it right now.
# --------------------------------------------------------------------------
CATEGORY_ORDER = ["web", "pwn", "misc", "re", "crypto"]
CATEGORY_LABELS = {
    "web": "WEB",
    "pwn": "PWN",
    "misc": "MISC",
    "re": "RE",
    "crypto": "CRYPTO",
}


def canon_category(raw: str) -> str:
    """Fold the platform's free-form category onto our five board columns.

    Competitions spell directions however they like — "REVRESE" (sic), "逆向工程",
    "Binary Exploitation" — so group by what the direction *means* instead of by
    the literal string, otherwise a typo'd category opens a stray column (or, when
    the operator filters on "re", drops those challenges entirely).
    """
    text = str(raw or "").strip()
    if not text:
        return "misc"
    for cat in CATEGORY_ORDER:
        if matches_categories(text, [], (cat,)):
            return cat
    return text.lower()
_BOARD_LOCK = threading.Lock()
_BOARD_CACHE: dict = {"ts": 0.0, "data": {"scope": "batch", "total": 0, "solved": 0, "groups": []}}
_BOARD_BUSY = False


def _norm_category(raw: str) -> str:
    """Fold the many tag spellings into web/pwn/misc/re/crypto."""
    text = str(raw or "").strip().lower()
    if not text:
        return "misc"
    for key, names in (
        ("web", ("web", "渗透")),
        ("pwn", ("pwn", "二进制", "漏洞")),
        ("re", ("逆向", "reverse")),
        ("crypto", ("crypto", "密码")),
        ("misc", ("misc", "杂项", "取证", "隐写", "stego")),
    ):
        if any(name in text for name in names):
            return key
    return text


def _board_meta_items() -> list[dict]:
    """Challenges pulled into ``challenges/`` with their local metadata."""
    items = []
    root = ROOT / "challenges"
    if not root.exists():
        return items
    try:
        import yaml
    except ImportError:  # pragma: no cover
        return items
    for meta_path in root.glob("*/metadata.yml"):
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = yaml.safe_load(fh) or {}
            mtime = meta_path.stat().st_mtime
        except Exception:  # noqa: BLE001 - a broken file must not hide the rest
            continue
        if not isinstance(meta, dict):
            continue
        name = str(meta.get("name") or meta_path.parent.name).strip()
        if not name:
            continue
        items.append(
            {
                "name": name,
                "category": _norm_category(str(meta.get("category") or "misc")),
                "value": int(float(meta.get("value") or 0)),
                "difficulty": str(meta.get("difficulty") or "").strip(),
                "mtime": mtime,
            }
        )
    return items


async def _board_platform(settings) -> tuple[set[str], list[dict]]:
    """Solved names (and, when the round size is 0, the whole challenge list)."""
    client = make_platform(settings)
    solved: set[str] = set()
    items: list[dict] = []
    try:
        try:
            solved = {str(n) for n in await client.fetch_solved_names()}
        except Exception:  # noqa: BLE001 - fall back to local traces
            solved = set()
        if int(settings.round_size or 0) <= 0:
            for ch in await client.fetch_all_challenges():
                name = str(ch.get("name") or "").strip()
                if not name:
                    continue
                # Trust the list's own solved flag too: it comes from the
                # same authenticated call, so a missing/!failing
                # fetch_solved_names() cannot paint everything green.
                if ch.get("solved"):
                    solved.add(name)
                items.append(
                    {
                        "name": name,
                        "category": _norm_category(str(ch.get("category") or "misc")),
                        "value": int(float(ch.get("value") or 0)),
                        "difficulty": str(ch.get("difficulty") or "").strip(),
                    }
                )
    finally:
        try:
            closed = client.close()
            if inspect.isawaitable(closed):
                await closed
        except Exception:  # noqa: BLE001
            logger.debug("suppressed exception in _board_platform", exc_info=True)
    return solved, items


def _board_trace_solved(started: float) -> set[str]:
    """Challenges whose trace recorded a confirmed flag since the run started."""
    solved: set[str] = set()
    if not TRACE_DIR.exists():
        return solved
    for path in TRACE_DIR.glob("trace-*.jsonl"):
        try:
            if path.stat().st_mtime < started - 5:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if '"type": "flag_confirmed"' not in text and '"type":"flag_confirmed"' not in text:
            continue
        name = ""
        for line in text.splitlines():
            try:
                event = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if event.get("type") == "start":
                name = str(event.get("challenge") or "")
                break
        if not name:
            parts = path.stem.split("-")
            name = parts[1] if len(parts) > 1 else ""
        if name:
            solved.add(name)
    return solved


def _board_compute() -> dict:
    settings = Settings()
    run = RUN.status()
    started = float(run.get("started_at") or 0.0)
    round_size = int(settings.round_size or 0)
    # Round mode shows the batch pulled for this round; round size 0 means the
    # coordinator may touch everything, so show every challenge on the platform.
    batch_mode = round_size > 0

    platform_items: list[dict] = []
    solved: set[str] = set()
    error = ""
    try:
        solved, platform_items = asyncio.run(_board_platform(settings))
    except Exception as exc:  # noqa: BLE001 - dashboard must survive a dead platform
        error = f"平台接口失败：{exc}"

    local = _board_meta_items()
    if started:
        solved |= _board_trace_solved(started)

    if batch_mode:
        picked = [i for i in local if not started or i["mtime"] >= started - 30]
        if not picked:
            picked = local
        # Prefer the platform's own list; local challenge folders are only evidence
        # of what an actually running round pulled.
        items = platform_items or (picked if started else [])
        scope = "batch"
    else:
        # Only fall back to local challenge folders while a run is live; otherwise a
        # platform error would show challenges from some other competition as this one.
        items = platform_items or (local if started else [])
        scope = "all"

    active = {str(s.get("challenge") or "") for s in collect(False) if s.get("active")}

    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(canon_category(item["category"]), []).append(
            {
                "name": item["name"],
                "solved": item["name"] in solved,
                "active": item["name"] in active,
                "value": item.get("value") or 0,
                "difficulty": item.get("difficulty") or "",
            }
        )

    def cat_key(cat: str) -> tuple:
        return (CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else 99, cat)

    groups = [
        {"category": cat, "label": CATEGORY_LABELS.get(cat, cat.upper()), "items": sorted(v, key=lambda i: i["name"])}
        for cat, v in sorted(grouped.items(), key=lambda kv: cat_key(kv[0]))
    ]
    total = sum(len(g["items"]) for g in groups)
    return {
        "scope": scope,
        "total": total,
        "solved": sum(1 for g in groups for i in g["items"] if i["solved"]),
        "groups": groups,
        "error": error,
        "updated": time.time(),
    }


def _board_refresh() -> None:
    global _BOARD_BUSY
    try:
        data = _board_compute()
        with _BOARD_LOCK:
            _BOARD_CACHE["ts"] = time.time()
            _BOARD_CACHE["data"] = data
    except Exception:  # noqa: BLE001
        logger.exception("board refresh failed")
    finally:
        _BOARD_BUSY = False


def board_snapshot(max_age: float = 20.0) -> dict:
    global _BOARD_BUSY
    now = time.time()
    with _BOARD_LOCK:
        stale = now - float(_BOARD_CACHE["ts"] or 0.0) > max_age
        busy = _BOARD_BUSY
    if stale and not busy:
        _BOARD_BUSY = True
        threading.Thread(target=_board_refresh, name="board-refresh", daemon=True).start()
    with _BOARD_LOCK:
        return dict(_BOARD_CACHE["data"])


def board_invalidate() -> None:
    """Force a rebuild (config changed: platform, token, round size...)."""
    with _BOARD_LOCK:
        _BOARD_CACHE["ts"] = 0.0


def _kill_stale_solvers() -> None:
    """Kill *old* ctf-solve processes (a previous session), not a fresh run."""
    from backend import procs

    me = os.getpid()
    names = ("python.exe", "uv.exe", "ctf-solve.exe") if procs.WINDOWS else ("python", "uv", "ctf-solve")
    try:
        for pid, _name, cmdline in procs.list_processes(names, min_age_s=300):
            if pid == me or "ctf-solve" not in cmdline:
                continue
            procs.kill_tree(pid)
            print(f"killed stale solver pid {pid}")
    except Exception as exc:  # noqa: BLE001 - cleanup must never block startup
        print(f"stale solver cleanup skipped: {exc}")


try:  # `python scripts/webui.py` puts scripts/ on sys.path
    from webui_assets import HTML
except ImportError:  # imported as scripts.webui (pytest, tooling)
    from scripts.webui_assets import HTML



class Handler(BaseHTTPRequestHandler):
    server_version = "ctf-agent-webui/3.0"

    def log_message(self, fmt: str, *args) -> None:  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            self._json(200, {"solvers": collect(True)})
            return
        if path == "/api/board":
            self._json(200, board_snapshot())
            return
        if path == "/api/runs":
            from backend import snapshot

            self._json(200, {"runs": snapshot.list_runs(8)})
            return
        if path == "/api/balance":
            self._json(200, _deepseek_balance())
            return
        if path == "/api/config":
            self._json(200, _config_view())
            return
        if path == "/api/run":
            self._json(200, RUN.status())
            return
        if path in ("/", "/index.html"):
            self._send(200, HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/hint":
                payload = self._read_json()
                challenge = str(payload.get("challenge") or "").strip()
                text = str(payload.get("text") or "").strip()
                if not challenge or not text:
                    self._json(400, {"ok": False, "error": "challenge and text are required"})
                    return
                file = append_hint(challenge, text)
                self._json(200, {"ok": True, "file": str(file)})
                return
            if path == "/api/solver/skip":
                payload = self._read_json()
                challenge = str(payload.get("challenge") or "").strip()
                if not challenge:
                    self._json(400, {"ok": False, "error": "challenge is required"})
                    return
                pending = runtime.request_skip(challenge)
                self._json(200, {"ok": True, "pending": pending})
                return
                return
            if path == "/api/balance/reset":
                _BALANCE_CACHE.update(at=0.0, data=None)
                info = _deepseek_balance()
                if not info.get("ok") or info.get("total") is None:
                    self._json(400, {"ok": False, "error": info.get("error") or "余额不可用"})
                    return
                balance = quota.reset_baseline(float(info["total"]))
                self._json(200, {"ok": True, "baseline": balance.get("baseline")})
                return
            if path == "/api/config":
                payload = self._read_json()
                try:
                    save_config(payload)
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                    return
                for spec, limit in (payload.get("quotas") or {}).items():
                    try:
                        if isinstance(limit, dict):
                            quota.set_limit(
                                str(spec),
                                float(limit.get("limit") or 0),
                                str(limit.get("currency") or "USD"),
                            )
                        else:
                            currency = "CNY" if str(spec).startswith("deepseek/") else "USD"
                            quota.set_limit(str(spec), float(limit or 0), currency)
                    except (TypeError, ValueError):
                        continue
                try:
                    value = int(payload.get("max_concurrent") or 0)
                except (TypeError, ValueError):
                    value = 0
                if value >= 1:
                    runtime.set_concurrency(value)
                # Platform/token may have changed: rebuild the board immediately.
                board_invalidate()
                self._json(200, {"ok": True})
                return
            if path == "/api/providers":
                payload = self._read_json()
                try:
                    prov = upsert_provider(
                        str(payload.get("name") or ""),
                        str(payload.get("base_url") or ""),
                        str(payload.get("api_key") or ""),
                    )
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                    return
                # Never echo the API key back to the browser.
                self._json(200, {"ok": True, "name": prov.get("name"), "providers": _providers_view()})
                return
            if path == "/api/providers/delete":
                name = str(self._read_json().get("name") or "")
                self._json(200, {"ok": delete_provider(name), "providers": _providers_view()})
                return
            if path == "/api/providers/fetch":
                payload = self._read_json()
                name = str(payload.get("name") or "").strip().lower()
                base_url = str(payload.get("base_url") or "").strip()
                api_key = str(payload.get("api_key") or "").strip()
                if name:
                    existing = {p["name"]: p for p in _providers_view()}.get(name)
                    if existing and not base_url:
                        base_url = existing["base_url"]
                    if existing and not api_key:
                        api_key = ""
                    stored = next(
                        (p for p in load_store()["providers"] if p.get("name", "").lower() == name), None
                    )
                    if stored and not api_key:
                        api_key = str(stored.get("api_key") or "")
                try:
                    models = fetch_models(base_url, api_key)
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                    return
                if name:
                    try:
                        set_provider_models(name, models)
                    except ValueError:
                        logger.debug("suppressed exception", exc_info=True)
                self._json(200, {"ok": True, "models": models, "providers": _providers_view()})
                return
            if path == "/api/models":
                models = [str(m) for m in (self._read_json().get("models") or [])]
                self._json(200, {"ok": True, "models": add_extra_models(models)})
                return
            if path == "/api/run/start":
                try:
                    self._json(200, RUN.start(self._read_json()))
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc)})
                return
            if path == "/api/run/stop":
                self._json(200, RUN.stop())
                return
            if path == "/api/run/concurrency":
                payload = self._read_json()
                try:
                    value = int(payload.get("value") or 0)
                except (TypeError, ValueError):
                    value = 0
                if value < 1:
                    self._json(400, {"ok": False, "error": "并发数必须 ≥ 1"})
                    return
                value = runtime.set_concurrency(value)
                save_config({"max_concurrent": value})
                self._json(200, {"ok": True, "concurrency": value})
                return
            self._send(404, b"not found", "text/plain")
        except Exception as e:
            self._json(500, {"ok": False, "error": str(e)})


def _listener_pid(port: int) -> int | None:
    """Return the PID listening on ``port`` (netstat on Windows, lsof elsewhere)."""
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["netstat", "-ano"], capture_output=True, text=True, timeout=20
            ).stdout
            for line in out.splitlines():
                parts = line.split()
                if (
                    len(parts) >= 5
                    and parts[0].startswith("TCP")
                    and parts[1].endswith(f":{port}")
                    and parts[3].upper() == "LISTENING"
                    and parts[4].isdigit()
                ):
                    return int(parts[4])
            return None
        out = subprocess.run(
            ["lsof", "-nP", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                return int(line)
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("listener lookup on port %s failed: %s", port, exc)
    return None


class DashboardServer(ThreadingHTTPServer):
    """HTTP server that refuses to share its port.

    Windows' SO_REUSEADDR lets several processes bind the same port, and then
    connections land on an arbitrary (often stale) instance — which is exactly
    how old code kept serving after a "restart". Turning reuse off makes a
    second instance fail loudly so ``_bind_server`` can replace the old one.
    """

    allow_reuse_address = False
    allow_reuse_port = False
    daemon_threads = True


def _bind_server(host: str, port: int) -> ThreadingHTTPServer:
    """Bind the dashboard, replacing an older instance that still holds the port."""
    try:
        return DashboardServer((host, port), Handler)
    except OSError:
        old = _listener_pid(port)
        while old and old != os.getpid():
            print(f"port {port} held by pid {old} - replacing it")
            _kill_tree(old)
            time.sleep(1.5)
            old = _listener_pid(port)
        return DashboardServer((host, port), Handler)


def _kill_other_dashboards() -> None:
    """Make sure only one dashboard process survives.

    Older dashboards keep serving after a "restart" because they already hold
    the port; this stops every other ``webui.py`` process that has been running
    for a while. Freshly started ones are left alone.
    """
    from backend import procs

    me = os.getpid()
    names = ("python.exe", "python")
    try:
        for pid, _name, cmdline in procs.list_processes(names, min_age_s=30):
            if pid == me or "webui.py" not in cmdline:
                continue
            procs.kill_tree(pid)
            print(f"killed other dashboard pid {pid}")
    except Exception:  # noqa: BLE001 - best effort
        logger.debug("suppressed exception in _kill_other_dashboards", exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Local web control panel for ctf-agent")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--keep-solvers",
        action="store_true",
        help="do not kill ctf-solve processes started before this dashboard session",
    )
    args = parser.parse_args()

    if not args.keep_solvers:
        _kill_stale_solvers()
        _cleanup_containers()

    _prune_logs()
    _scrub_bogus_secrets()

    server = _bind_server(args.host, args.port)
    print(f"CTF Agent 控制台: http://{args.host}:{args.port}")
    print(f"配置文件: {ENV_FILE}")
    print(f"提示写入目录: {hint_file_for('EXAMPLE').parent}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        RUN.stop()


if __name__ == "__main__":
    main()
