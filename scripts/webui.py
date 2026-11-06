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
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("ctf-webui")
sys.path.insert(0, str(ROOT))

from backend.config import Settings  # noqa: E402
from backend import quota, runtime  # noqa: E402
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
                pass
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

# Credentials are secrets: the API returns them masked and only rewrites a value
# when the form sends a non-empty replacement.
SECRET_FIELDS = (
    "deepseek_api_key",
    "ret2shell_token",
    "dasctf_access_key",
    "ctf2_token",
    "ctfplus_token",
    "ctfd_token",
)

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
        "round_rotate": s.round_rotate,
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


# Keys the form may write back into .env.
_ENV_KEYS = {
    "platform": "PLATFORM",
    "models": "DEFAULT_MODELS",
    "round_size": "ROUND_SIZE",
    "max_concurrent": "MAX_CONCURRENT_CHALLENGES",
    "challenge_timeout_min": "CHALLENGE_TIMEOUT_MIN",
    "challenge_extra_rounds": "CHALLENGE_EXTRA_ROUNDS",
    "max_environments": "MAX_ENVIRONMENTS",
    "categories": "CHALLENGE_CATEGORIES",
    "difficulty": "CHALLENGE_DIFFICULTY",
    "round_order": "ROUND_ORDER",
    "min_score": "ROUND_MIN_SCORE",
    "include_solved": "ROUND_INCLUDE_SOLVED",
    "writeup_enabled": "WRITEUP_ENABLED",
    "flag_format": "FLAG_FORMAT",
    "flag_submit_mode": "FLAG_SUBMIT_MODE",
    "think_chinese": "THINK_CHINESE",
    "require_flag_evidence": "REQUIRE_FLAG_EVIDENCE",
    "skip_solved_pull": "SKIP_SOLVED_PULL",
    "round_rotate": "ROUND_ROTATE",
    "rotate_batch": "ROTATE_BATCH",
    "ret2shell_url": "RET2SHELL_URL",
    "ret2shell_token": "RET2SHELL_TOKEN",
    "ret2shell_game": "RET2SHELL_GAME",
    "dasctf_url": "DASCTF_URL",
    "dasctf_access_key": "DASCTF_ACCESS_KEY",
    "ctf2_url": "CTF2_URL",
    "ctf2_token": "CTF2_AGENT_TOKEN",
    "ctf2_ground": "CTF2_GROUND",
    "ctfplus_url": "CTFPLUS_URL",
    "ctfplus_token": "CTFPLUS_TOKEN",
    "ctfd_url": "CTFD_URL",
    "ctfd_token": "CTFD_TOKEN",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "deepseek_base_url": "DEEPSEEK_BASE_URL",
}


def _render_env_value(key: str, value) -> str:
    if key == "models":
        return ",".join(str(m).strip() for m in (value or []) if str(m).strip())
    if key == "include_solved":
        return "1" if value else "0"
    if key == "writeup_enabled":
        return "1" if value else "0"
    if key in ("think_chinese", "require_flag_evidence"):
        return "1" if value else "0"
    if key == "skip_solved_pull":
        return "1" if value else "0"
    return "" if value is None else str(value)


def save_config(payload: dict) -> None:
    """Merge the form payload into ``.env`` (create it if missing).

    Secret fields are left untouched when the payload sends an empty string, so
    a masked value is never written back over the real one.
    """
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
                return {"ok": False, "error": "已有一个解题进程在运行，请先停止"}
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
                pass
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
        pass


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
        pass


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
    direct child leaves the solver running. On Windows ``taskkill /T`` removes
    the whole tree; elsewhere fall back to the process group.
    """
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        pass


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


def _parse_trace(path: Path, stat: "os.stat_result | None" = None) -> dict:
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
                pass
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
            try:
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
            except Exception:  # noqa: BLE001
                items = []
    finally:
        try:
            closed = client.close()
            if inspect.isawaitable(closed):
                await closed
        except Exception:  # noqa: BLE001
            pass
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
        items = picked
        scope = "batch"
    else:
        items = platform_items or local
        scope = "all"

    active = {str(s.get("challenge") or "") for s in collect(False) if s.get("active")}

    grouped: dict[str, list[dict]] = {}
    for item in items:
        grouped.setdefault(item["category"] or "misc", []).append(
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
    if os.name != "nt":
        return
    try:
        ps = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                # Only processes started more than 5 minutes ago are treated as
                # leftovers: a run started by a healthy dashboard (or by hand a
                # moment ago) must survive a panel restart.
                "Get-CimInstance Win32_Process | Where-Object { "
                "$_.Name -in @('python.exe','uv.exe','ctf-solve.exe') "
                "-and $_.CommandLine -like '*ctf-solve*' "
                "-and $_.CreationDate -lt (Get-Date).AddMinutes(-5) } "
                "| Select-Object -ExpandProperty ProcessId",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        for line in (ps.stdout or "").splitlines():
            pid = line.strip()
            if pid.isdigit():
                subprocess.run(["taskkill", "/F", "/T", "/PID", pid], capture_output=True)
                print(f"killed stale solver pid {pid}")
    except Exception as exc:  # noqa: BLE001 - cleanup must never block startup
        print(f"stale solver cleanup skipped: {exc}")


HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>CTF Agent 控制台</title>
<style>
:root{--bg:#0f1115;--panel:#171a21;--panel2:#1c2029;--line:#262b36;--fg:#d7dce5;--dim:#7d8798;
--cyan:#4cc2ff;--green:#5ddb8f;--mag:#c792ea;--yellow:#ffd479;--red:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:13px/1.5 Consolas,"Cascadia Mono","Microsoft YaHei",monospace}
header{display:flex;gap:14px;align-items:center;padding:9px 16px;border-bottom:1px solid var(--line);background:#12151b;position:sticky;top:0;z-index:9}
header h1{font-size:15px;margin:0;font-weight:600}
nav{display:flex;gap:4px}
nav button{background:transparent;color:var(--dim);border:1px solid transparent;border-radius:7px;padding:5px 12px;cursor:pointer;font:inherit}
nav button.on{background:#222836;color:var(--fg);border-color:#31384a}
.spacer{flex:1}
.chip{color:var(--dim);font-size:12px}
.chip b{font-weight:600}
.chip .on{color:var(--green)}
.page{padding:14px;display:none}
.page.on{display:block}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:12px;align-items:start;max-width:1400px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:13px}
.card h2{font-size:13px;margin:0 0 4px;display:flex;gap:8px;align-items:center}
.card .sub{color:var(--dim);font-size:11px;margin-bottom:10px}
#page-config .cards{max-width:1600px;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:14px}
#page-config .card{padding:16px 18px}
#page-config .card:first-child{grid-column:1/-1}
#page-config .card h2{font-size:14px;padding-bottom:6px;border-bottom:1px solid var(--line);margin-bottom:8px}
#page-config .f{margin-bottom:9px}
#page-config .f label{font-size:12px;color:var(--dim);margin-bottom:4px}
#page-config .f input,#page-config .f select{height:32px;padding:0 9px;border-radius:7px;background:#0f1219;border:1px solid var(--line);color:var(--fg);font:inherit;font-size:13px;width:100%}
#page-config .f input:focus,#page-config .f select:focus{outline:none;border-color:#3d6fd4;box-shadow:0 0 0 2px rgba(61,111,212,.18)}
#page-config .chks{display:flex;flex-wrap:wrap;gap:6px}
#page-config .chks label{display:inline-flex;align-items:center;gap:5px;padding:4px 10px;border:1px solid var(--line);border-radius:999px;background:#12161f;cursor:pointer;font-size:12px}
#page-config .chks label:has(input:checked){border-color:#3d6fd4;background:#18203a;color:#cfe0ff}
#page-config .hint{font-size:11px;color:var(--dim);margin-top:3px}
#page-config .pbox{border:1px dashed var(--line);border-radius:9px;padding:10px 12px;margin-top:8px}
#page-config .pbox:empty{display:none}
.savebar{position:sticky;bottom:0;z-index:40;display:flex;gap:10px;align-items:center;max-width:1600px;margin:4px auto 0;padding:10px 4px;background:linear-gradient(180deg,rgba(11,13,18,0),var(--bg) 45%);border-top:1px solid var(--line)}
.cfg-tabs{display:flex;gap:6px;max-width:1600px;margin:2px auto 10px}
.cfg-tabs button{background:#12161f;color:var(--dim);border:1px solid var(--line);border-radius:8px;padding:7px 14px;cursor:pointer;font:inherit;font-size:13px}
.cfg-tabs button.on{background:#1b2740;color:#cfe0ff;border-color:#3d6fd4}
#page-config .cards{grid-template-columns:1fr}
#page-config .card{display:none}
#page-config .card.on{display:block}
.savebar .msg{font-size:12px;color:var(--dim)}
.savebar button{padding:8px 16px}
.f{display:flex;flex-direction:column;gap:3px;margin-bottom:9px}
.f label{color:var(--dim);font-size:11px}
.f input,.f select{background:#0d1015;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:6px 8px;font:inherit;width:100%}
.f .hint{color:var(--dim);font-size:11px;margin-top:2px}
.models{border:1px solid var(--line);border-radius:6px;background:#0d1015;max-height:150px;overflow:auto;padding:6px 8px}
.models label{display:flex;gap:7px;align-items:center;padding:2px 0;color:var(--fg);font-size:12px;cursor:pointer}
.pgroup{margin:8px 0;padding:8px;border:1px solid var(--line);border-radius:10px;background:#11151d}
.phead{display:flex;align-items:center;gap:8px;margin-bottom:6px;font-size:13px}
.phead .dim{color:var(--dim);font-size:12px}
.mrow{display:grid;grid-template-columns:18px minmax(0,1fr) auto 92px 78px;align-items:center;gap:8px;padding:5px 6px;border-radius:8px}
.mrow.on{background:#18203a}
.mrow .mname{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:ui-monospace,Consolas,monospace;font-size:12px}
.mrow .mspent{color:var(--dim);font-size:12px;white-space:nowrap}
.mrow .mlimit{width:92px;padding:3px 6px;font-size:12px}
.mrow .mrem{color:var(--dim);font-size:12px;white-space:nowrap;text-align:right}
.mrow .mrem.out{color:var(--red)}
.mini{padding:2px 8px;font-size:11px;border-radius:6px;background:#1c2230;border:1px solid var(--line);color:var(--fg);cursor:pointer}
.prov{border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin-bottom:8px;background:#141821}
.prov-head{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.prov-head .hint{font-size:11px}
.checks{display:flex;gap:16px;margin:2px 0 10px;color:var(--dim)}
.chks{display:flex;flex-wrap:wrap;gap:8px 16px;padding:5px 0;font-size:12.5px}
.chks label{display:flex;align-items:center;gap:5px;cursor:pointer;color:var(--fg)}
.chks input{accent-color:#3d6fd4;margin:0}
.checks label{display:flex;gap:6px;align-items:center;cursor:pointer}
.btns{display:flex;gap:8px;flex-wrap:wrap}
button{border:0;border-radius:6px;padding:7px 14px;cursor:pointer;font:inherit;color:#fff}
.primary{background:#1f6feb}.primary:hover{background:#2b7ff5}
.danger{background:#a33}.danger:hover{background:#c44}
.ghost{background:#2a2f3a}.ghost:hover{background:#343b49}
.msg{margin-top:10px;font-size:12px;white-space:pre-wrap;word-break:break-word;color:var(--dim)}
.msg.err{color:var(--red)} .msg.ok{color:var(--green)}
/* main page */
.main{display:flex;align-items:stretch;gap:0;padding:14px;height:calc(100vh - 52px)}
@media(max-width:900px){.main{grid-template-columns:1fr;height:auto}}
.rail{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:10px;overflow:auto;flex:0 0 var(--rail-w,330px);min-width:200px}
.splitter{flex:0 0 12px;display:flex;align-items:center;justify-content:center;cursor:col-resize}
.splitter i{width:3px;height:100%;background:var(--line);border-radius:2px;transition:background .15s}
.splitter:hover i{background:#3d6fd4}
.sitem .col{display:flex;flex-direction:column;gap:1px;min-width:0;flex:1}
.sitem .col .nm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.rail h2{font-size:12px;margin:0;color:var(--dim);font-weight:600;letter-spacing:.05em}
.runbox{display:flex;gap:6px}
.runbox button{flex:1;padding:7px 8px}
.runstate{font-size:12px;color:var(--dim);white-space:pre-wrap;word-break:break-word}
.runstate .on{color:var(--green)}
.slist{display:flex;flex-direction:column;gap:4px}
.sitem{display:flex;gap:8px;align-items:center;padding:7px 9px;border:1px solid transparent;border-radius:8px;cursor:pointer;background:#141821}
.sitem:hover{background:#1a1f2a}
.sitem.on{border-color:#3d6fd4;background:#18203a}
.sitem.fin{opacity:.55}
.sitem .dot{width:8px;height:8px;border-radius:50%;background:var(--dim);flex:0 0 auto}
.sitem .dot.on{background:var(--green);box-shadow:0 0 8px var(--green)}
.sitem .nm{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sitem .md{color:var(--dim);font-size:11px}
.pane{background:var(--panel);border:1px solid var(--line);border-radius:10px;display:flex;flex-direction:column;min-height:320px;max-height:100%;overflow:hidden;flex:1 1 0;min-width:0}
.pane h3{margin:0;padding:10px 13px;border-bottom:1px solid var(--line);font-size:13px;display:flex;gap:8px;align-items:center}
.pane h3 .md{color:var(--dim);font-weight:400}
.phead-bar{display:flex;align-items:center;border-bottom:1px solid var(--line)}
.phead-bar h3{border-bottom:0;flex:1;min-width:0}
.phead-bar button{margin:0 11px;flex:0 0 auto}
.log{overflow:auto;padding:9px 13px;flex:1;font-size:12.5px}
.board{flex:0 0 288px;display:flex;flex-direction:column;border-left:1px solid var(--line);background:#0b0f16;min-height:0}
.bhead{display:flex;justify-content:space-between;align-items:center;gap:8px;padding:9px 11px;border-bottom:1px solid var(--line);font-size:12.5px;color:var(--dim);font-weight:600}
.board-body{overflow:auto;padding:9px 11px}
.bgroup{margin-bottom:12px}
.gtitle{display:flex;justify-content:space-between;font-size:11px;letter-spacing:.06em;color:var(--dim);margin:2px 0 6px;text-transform:uppercase}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(38px,1fr));gap:6px}
.sq{height:38px;border-radius:7px;border:1px solid #232b39;background:#141a24;color:#7c8798;font-size:10px;display:flex;align-items:center;justify-content:center;overflow:hidden;white-space:nowrap;padding:0 2px}
.sq.solved{background:#12351f;border-color:#2ea043;color:#8ff0b7;font-weight:600}
.sq.active{outline:2px solid #3d6fd4;outline-offset:1px}
#tip{position:fixed;z-index:80;max-width:340px;padding:6px 9px;border-radius:7px;border:1px solid #2b3446;background:#1b2130;color:#e6edf3;font-size:12px;line-height:1.45;white-space:pre-wrap;pointer-events:none;opacity:0;transition:opacity .08s;box-shadow:0 8px 24px rgba(0,0,0,.5)}
.ev{margin:2px 0;white-space:pre-wrap;word-break:break-word}
.think{color:var(--mag)} .tool{color:var(--cyan)} .result{color:var(--dim)}
.flag{color:var(--yellow);font-weight:700} .hintx{color:var(--green)}
.hints{display:flex;gap:6px;padding:9px 11px;border-top:1px solid var(--line)}
.hints input{flex:1;background:#0d1015;border:1px solid var(--line);color:var(--fg);border-radius:6px;padding:7px 10px;font:inherit}
.empty{color:var(--dim);padding:30px;text-align:center}
</style></head>
<body>
<header>
  <h1>CTF Agent 控制台</h1>
  <nav>
    <button id="tab-main" class="on" data-page="main">解题观察</button>
    <button id="tab-config" data-page="config">配置</button>
  </nav>
  <span class="spacer"></span>
  <span class="chip" id="chip-run">未运行</span>
  <span class="chip" id="chip-plat"></span>
  <span class="chip" id="chip-solvers">0 个 solver</span>
  <span class="chip" id="chip-bal" title="DeepSeek 官方余额"></span>
</header>

<div class="page on" id="page-main">
  <div class="main">
    <aside class="rail">
      <h2>运行控制</h2>
      <div class="runbox">
        <button class="primary" id="start">开始解题</button>
        <button class="danger" id="stop">停止</button>
      </div>
      <button class="ghost mini" id="resume-last" style="margin:6px 0">继续上次未完成的轮次</button>
      <div class="runstate" id="resume-hint"></div>
      <div class="runstate" id="runstate">状态：未运行</div>
      <div class="runstate" id="summary"></div>
      <div class="f"><label>并发数（运行中可改）</label>
        <div class="runbox"><input id="conc" type="number" min="1" value="1"><button id="conc-apply">应用</button></div>
      </div>
      <h2>并发中的题目</h2>
      <div class="slist" id="slist"><div class="empty">还没有 solver</div></div>
            <button class="ghost" id="toolist">查看题目清单</button>
    </aside>
    <div class="splitter" id="splitter" title="拖动调整宽度，双击恢复"><i></i></div>
    <section class="pane">
      <div class="phead-bar"><h3 id="pane-title">选择一个题目观察</h3>
        <button class="ghost mini" id="skip" disabled title="让这道题立刻停止，把并发位让给下一题">跳过此题</button></div>
      <div class="log" id="log"><div class="empty">点击左侧题目查看思考与操作</div></div>
      <div class="hints">
        <input id="hint-input" placeholder="给当前题目发提示，回车发送（选中题目后可输入）" disabled>
        <button id="hint-send">发送</button>
      </div>
    </section>
    <aside class="board">
      <div class="bhead"><span>题目总览</span><span class="hint" id="bscope"></span></div>
      <div class="board-body" id="board"><div class="empty">加载中…</div></div>
    </aside>
  </div>
</div>

<div class="page" id="page-config">
  <div class="cfg-tabs" id="cfg-tabs">
    <button class="on" data-cfg="model">模型配置</button>
    <button data-cfg="platform">平台配置</button>
    <button data-cfg="solve">解题配置</button>
  </div>
  <div class="cards">
    <section class="card on" data-cfg="model">
      <h2>模型配置</h2>
      <div class="sub">解题用的模型。可多选，多个模型会并发跑同一道题。DeepSeek 的「已用」按官网余额差计算（与官网一致）。</div>
      <div class="f" style="display:flex;gap:8px;align-items:center">
        <button class="mini" id="bal-reset" title="把当前官网余额当作“已用 0”，用于重新开始计量">已用额度清零</button>
        <span class="dim" id="bal-hint" style="font-size:12px"></span>
      </div>
      <div class="f"><label>已选模型</label><div class="models" id="models"></div></div>
      <div class="f"><label>添加模型（spec 格式：供应商/模型名）</label>
        <div style="display:flex;gap:6px">
          <input id="newmodel" placeholder="例如 openrouter/qwen/qwen3-235b">
          <button class="ghost" id="addmodel">添加</button>
        </div>
        <div class="hint" id="hint-newmodel"></div></div>

      <h2 style="margin-top:16px">供应商</h2>
      <div class="sub">DeepSeek 已内置。其他 OpenAI 兼容服务（OpenRouter、Moonshot、SiliconFlow、本地 vLLM 等）在这里添加，然后拉取模型。</div>
      <div id="providers"></div>
      <div class="f" style="margin-top:10px"><label>供应商名称</label>
        <input id="prov-name" placeholder="openrouter"></div>
      <div class="f"><label>Base URL（到 /v1 为止）</label>
        <input id="prov-url" placeholder="https://openrouter.ai/api/v1"></div>
      <div class="f"><label>API Key</label>
        <input id="prov-key" type="password" placeholder="sk-..."></div>
      <div class="btns">
        <button class="ghost" id="addprov">添加供应商</button>
        <button class="ghost" id="fetchprov">拉取模型</button>
      </div>
      <div class="msg" id="provmsg"></div>

      <div class="f" style="margin-top:14px"><label>DeepSeek API Key</label>
        <input id="deepseek_api_key" type="password" placeholder="">
        <div class="hint" id="hint-ds"></div></div>
      <div class="f"><label>DeepSeek Base URL</label><input id="deepseek_base_url"></div>
    </section>

    <section class="card" data-cfg="platform">
      <h2>平台配置</h2>
      <div class="sub">选择要打哪个平台。选定后只拉该平台的题目。</div>
      <div class="f"><label>平台</label>
        <select id="platform">
          <option value="dasctf">DASCTF / 羊城杯</option>
          <option value="ctf2">CTF² Agent Arena</option>
        <option value="ctfplus">CTF+ / 极客挑战赛</option>
          <option value="ret2shell">Ret2Shell / 西电 MoeCTF</option>
          <option value="ctfd">CTFd</option>
        </select></div>

      <div class="f"><label>允许同时开启的容器数（0 = 按平台配额）</label>
        <input id="max_environments" type="number" min="0" value="0" placeholder="例如 2">
        <div class="hint">平台每个账号能同时开几个靶机；容器题超过这个数会排队等待，不会去扫端口。</div></div>

      <div class="f"><label>Flag 格式（如 moectf{} / SYC{}）</label>
        <input id="flag_format" placeholder="moectf{}">
        <div class="hint">只作为提示写进 solver 的提示词，并按前缀做一次软校验（不匹配只记日志）。</div></div>
      <div class="f"><label>提交格式</label>
        <select id="flag_submit_mode">
          <option value="full">完整 flag（含前缀和花括号）</option>
          <option value="inner">仅花括号内内容</option>
        </select>
        <div class="hint">选「仅内容」时，客户端提交前会自动去掉 PREFIX{...} 外壳（DASCTF / 羊城杯常用）。</div></div>

      <div id="box-dasctf" class="pbox">
        <div class="f"><label>SERVER HOST</label><input id="dasctf_url" placeholder="https://pro.dasctf.com"></div>
        <div class="f"><label>ACCESSKEY</label><input id="dasctf_access_key" type="password">
          <div class="hint" id="hint-dasctf"></div></div>
      </div>

      <div id="box-ret2shell" class="pbox">
        <div class="f"><label>站点地址</label><input id="ret2shell_url" placeholder="https://ctf.xidian.edu.cn"></div>
        <div class="f"><label>登录 Token（localStorage.account.token）</label>
          <input id="ret2shell_token" type="password"><div class="hint" id="hint-r2s"></div></div>
        <div class="f"><label>比赛 ID（留空 = 当前比赛）</label><input id="ret2shell_game" placeholder="37"></div>
      </div>

      <div id="box-ctfplus" class="pbox">
        <div class="f"><label>站点地址</label><input id="ctfplus_url" placeholder="https://geek2026.play.ctfplus.cn"></div>
        <div class="f"><label>SessionStore Cookie（CTFPLUS_TOKEN）</label>
          <input id="ctfplus_token" type="password"><div class="hint" id="hint-ctfplus"></div></div>
      </div>
      <div id="box-ctf2" class="pbox">
        <div class="f"><label>站点地址</label><input id="ctf2_url" placeholder="https://ctf2.dasctf.com"></div>
        <div class="f"><label>Agent Token（CTF2_AGENT_TOKEN）</label>
          <input id="ctf2_token" type="password"><div class="hint" id="hint-ctf2"></div></div>
        <div class="f"><label>练习题场（ID / 名字，留空 = 全部）</label><input id="ctf2_ground" placeholder="b9bbb32f-… 或直接粘贴练习场页面 URL"></div>
      </div>

      <div id="box-ctfd" class="pbox">
        <div class="f"><label>站点地址</label><input id="ctfd_url" placeholder="https://ctf.example.com"></div>
        <div class="f"><label>API Token</label><input id="ctfd_token" type="password">
          <div class="hint" id="hint-ctfd"></div></div>
      </div>
    </section>

    <section class="card" data-cfg="solve">
      <h2>解题配置</h2>
      <div class="sub">一轮解多少题、怎么挑题。</div>
      <div class="f"><label>本轮题数（0 = 不限，用协调器持续跑）</label>
        <input id="round_size" type="number" min="0" value="1"></div>
      <div class="f"><label>并发数（同时解几道）</label>
        <input id="max_concurrent" type="number" min="1" value="1"></div>
      <div class="f"><label>单题超时（分钟，0 = 不限）</label>
        <input id="challenge_timeout_min" type="number" min="0" step="0.5" value="0"></div>
      <div class="f"><label>额外轮数（0 = 不重试；一题没解出来时再多跑几轮）</label>
        <input id="challenge_extra_rounds" type="number" min="0" step="1" value="0">
        <div class="hint">超时不会重试；“放弃/没做出”会带着新的上下文重新开一轮</div></div>
      <div class="f"><label>方向（不勾 = 不限）</label>
        <div class="chks" id="cat-box"></div></div>
      <div class="f"><label>难度（不勾 = 不限）</label>
        <div class="chks" id="diff-box"></div></div>
      <div class="f"><label>选题顺序</label>
        <select id="round_order">
          <option value="random">随机（难题加权）</option>
          <option value="hard">难度优先（难→易）</option>
          <option value="score">分数从低到高</option>
          <option value="name">按名称</option>
        </select></div>
      <div class="f"><label>只做名称包含（逗号分隔，可空）</label>
        <input id="only" placeholder="例如 PWN"></div>
      <div class="f"><label>刷题模式（一批一个方向，批大小默认 = 并发数）</label>
        <div class="checks" style="margin-bottom:6px"><label><input type="checkbox" id="round_rotate"> 开启方向轮换（misc → re → crypto …）</label></div>
        <input id="rotate_batch" type="number" min="0" value="0" placeholder="批大小，0 = 并发数"></div>
      <div class="checks">
        <label><input type="checkbox" id="include_solved"> 含已解题</label>
      <label><input type="checkbox" id="writeup_enabled"> 写 Writeup</label>
      <label><input type="checkbox" id="think_chinese"> 中文思考</label>
          <label><input type="checkbox" id="require_flag_evidence"> 提交需带证据</label>
      <label><input type="checkbox" id="skip_solved_pull"> 拉题跳过已解</label>
        <label><input type="checkbox" id="no_submit"> 不提交（演练）</label>
      </div>
    </section>
  </div>
  <div class="savebar">
    <button class="primary" id="save">保存配置</button>
    <button class="ghost" id="save-start">保存并开始</button>
    <div class="msg" id="cfgmsg"></div>
  </div>
</div>

<div id="tip"></div>
<script>
const esc = s => (s??'').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const TEXT_FIELDS = ["deepseek_base_url","dasctf_url","ctf2_url","ctf2_ground","ctfplus_url","ret2shell_url","ret2shell_game","ctfd_url",
  "round_order","only"];
const CATEGORY_CHOICES = ["web","misc","pwn","re","crypto"];
const DIFFICULTY_CHOICES = ["入门","简单","中等","困难"];
const SECRETS = ["deepseek_api_key","dasctf_access_key","ctf2_token","ctfplus_token","ret2shell_token","ctfd_token"];
const PLAT_LABELS = {dasctf:"DASCTF / 羊城杯", ctf2:"CTF² Agent Arena", ctfplus:"CTF+ / 极客挑战赛", ret2shell:"Ret2Shell / 西电 MoeCTF", ctfd:"CTFd", auto:"自动"};

let CFG = null, SOLVERS = [], SELECTED = null, PAGE = "main", FORCE_BOTTOM = false;

function showPage(name){
  PAGE = name;
  try { localStorage.setItem("ctf-tab", name); } catch(e){}
  document.querySelectorAll(".page").forEach(p=>p.classList.toggle("on", p.id==="page-"+name));
  document.querySelectorAll("nav button").forEach(b=>b.classList.toggle("on", b.dataset.page===name));
  if(name==="config") loadConfig();
  if(name==="main") refresh();
}
document.querySelectorAll("nav button").forEach(b=>b.onclick=()=>showPage(b.dataset.page));

function showCfgTab(name){
  document.querySelectorAll("#page-config .card").forEach(c=>c.classList.toggle("on", c.dataset.cfg===name));
  document.querySelectorAll("#cfg-tabs button").forEach(b=>b.classList.toggle("on", b.dataset.cfg===name));
  try { localStorage.setItem("ctf-cfgtab", name); } catch(e){}
}
document.querySelectorAll("#cfg-tabs button").forEach(b=>b.onclick=()=>showCfgTab(b.dataset.cfg));
try { const ct = localStorage.getItem("ctf-cfgtab"); if (ct) showCfgTab(ct); } catch(e){}
try { const saved = localStorage.getItem("ctf-tab"); if (saved === "config") showPage("config"); } catch(e){}

function renderChecks(){
  document.getElementById("cat-box").innerHTML = CATEGORY_CHOICES.map(v=>
    `<label><input type="checkbox" value="${v}"> ${v}</label>`).join("");
  document.getElementById("diff-box").innerHTML = DIFFICULTY_CHOICES.map(v=>
    `<label><input type="checkbox" value="${v}"> ${v}</label>`).join("");
}
function setChecks(box, value){
  const wanted = (value||"").split(",").map(s=>s.trim().toLowerCase()).filter(Boolean);
  const all = !wanted.length || wanted.includes("all");
  document.querySelectorAll("#"+box+" input").forEach(i=>{
    i.checked = !all && wanted.includes(i.value.toLowerCase());
  });
}
function getChecks(box){
  return [...document.querySelectorAll("#"+box+" input:checked")].map(i=>i.value);
}

function collectForm(){
  const p = {};
  for(const id of TEXT_FIELDS){ const el=document.getElementById(id); if(el) p[id]=el.value.trim(); }
  p.categories = getChecks("cat-box").join(",");
  p.difficulty = getChecks("diff-box").join(",");
  p.platform = document.getElementById("platform").value;
  p.round_size = parseInt(document.getElementById("round_size").value||"0",10)||0;
  p.max_concurrent = parseInt(document.getElementById("max_concurrent").value||"1",10)||1;
  p.challenge_timeout_min = parseFloat(document.getElementById("challenge_timeout_min").value||"0")||0;
  p.challenge_extra_rounds = parseInt(document.getElementById("challenge_extra_rounds").value||"0",10)||0;
  p.include_solved = document.getElementById("include_solved").checked;
  p.writeup_enabled = document.getElementById("writeup_enabled").checked;
  p.flag_format = document.getElementById("flag_format").value.trim();
  p.flag_submit_mode = document.getElementById("flag_submit_mode").value;
  p.think_chinese = document.getElementById("think_chinese").checked;
  p.require_flag_evidence = document.getElementById("require_flag_evidence").checked;
  p.skip_solved_pull = document.getElementById("skip_solved_pull").checked;
  p.round_rotate = document.getElementById("round_rotate").checked;
  p.rotate_batch = parseInt(document.getElementById("rotate_batch").value||"0",10)||0;
  p.max_environments = parseInt(document.getElementById("max_environments").value||"0",10)||0;
  p.no_submit = document.getElementById("no_submit").checked;
  p.models = [...document.querySelectorAll("#models input[type=checkbox]:checked")].map(i=>i.value);
  p.quotas = {};
  document.querySelectorAll("#models .mrow").forEach(row=>{
    const spec = row.querySelector("input[type=checkbox]").value;
    const limit = parseFloat(row.querySelector(".mlimit").value||"0") || 0;
    if(limit > 0) p.quotas[spec] = limit; else p.quotas[spec] = 0;
  });
  for(const id of SECRETS){ const v=document.getElementById(id).value.trim(); if(v) p[id]=v; }
  return p;
}

function providerName(spec, c){
  const prov = spec.split("/")[0];
  if(prov === "deepseek") return "DeepSeek";
  const hit = (c.providers||[]).find(p=>p.name===prov);
  return hit ? hit.name : prov;
}

function renderModelList(c){
  const quotas = c.quotas || {};
  const chosen = c.models || [];
  const choices = c.model_choices || [];
  if(!choices.length){
    document.getElementById("models").innerHTML = '<div class="empty">还没有可选模型</div>';
    return;
  }
  const groups = {};
  for(const spec of choices){
    const prov = spec.split("/")[0];
    (groups[prov] = groups[prov] || []).push(spec);
  }
  const html = Object.keys(groups).map(prov=>{
    const rows = groups[prov].map(spec=>{
      const q = quotas[spec] || {currency:"USD", limit:0, spent:0, remaining:null, available:true};
      const on = chosen.includes(spec);
      const sym = (q.currency||"USD")==="CNY" ? "¥" : "$";
      const rem = q.limit > 0 ? `剩余 ${sym}${(q.remaining ?? 0).toFixed(2)}` : "不限";
      const warn = q.limit > 0 && q.available === false ? ' class="mrem out"' : ' class="mrem"';
      const src = (q.currency||"USD")==="CNY" ? "（官方）" : "";
      return `<div class="mrow${on?" on":""}">
        <label class="chk"><input type="checkbox" value="${esc(spec)}" ${on?"checked":""}></label>
        <span class="mname">${esc(spec)}</span>
        <span class="mspent">已用 ${sym}${(q.spent||0).toFixed(2)}${src}</span>
        <input class="mlimit" type="number" min="0" step="1" value="${q.limit>0?q.limit:""}" placeholder="上限 ${sym}">
        <span${warn}>${rem}</span>
      </div>`;
    }).join("");
    const n = groups[prov].filter(x=>chosen.includes(x)).length;
    return `<div class="pgroup">
      <div class="phead"><b>${esc(providerName(groups[prov][0], c))}</b>
        <span class="dim">${groups[prov].length} 个模型 · 已选 ${n}</span>
        <span class="spacer"></span>
        <button class="mini" data-prov="${esc(prov)}" data-act="all">全选</button>
        <button class="mini" data-prov="${esc(prov)}" data-act="none">清空</button>
      </div>${rows}</div>`;
  }).join("");
  document.getElementById("models").innerHTML = html;
  document.querySelectorAll("#models .phead button").forEach(btn=>{
    btn.onclick = ()=>{
      const prov = btn.dataset.prov, act = btn.dataset.act;
      document.querySelectorAll("#models .mrow").forEach(row=>{
        const box = row.querySelector("input[type=checkbox]");
        if(box.value.split("/")[0] !== prov) return;
        box.checked = (act === "all");
        row.classList.toggle("on", box.checked);
      });
    };
  });
  document.querySelectorAll("#models input[type=checkbox]").forEach(box=>{
    box.onchange = ()=>box.closest(".mrow").classList.toggle("on", box.checked);
  });
}

function fillForm(c){
  CFG = c;
  document.getElementById("platform").value = (c.platform==="auto") ? "dasctf" : c.platform;
  document.getElementById("round_size").value = c.round_size ?? 1;
  document.getElementById("max_concurrent").value = c.max_concurrent ?? 1;
  document.getElementById("challenge_timeout_min").value = c.challenge_timeout_min ?? 0;
  document.getElementById("challenge_extra_rounds").value = c.challenge_extra_rounds ?? 0;
  setChecks("cat-box", c.categories || "");
  setChecks("diff-box", c.difficulty || "");
  document.getElementById("round_order").value = c.round_order || "random";
  document.getElementById("only").value = c.round_only || "";
  document.getElementById("include_solved").checked = !!c.include_solved;
  document.getElementById("writeup_enabled").checked = !!c.writeup_enabled;
  document.getElementById("flag_format").value = c.flag_format || "";
  document.getElementById("flag_submit_mode").value = c.flag_submit_mode || "full";
  document.getElementById("think_chinese").checked = c.think_chinese !== false;
  document.getElementById("require_flag_evidence").checked = c.require_flag_evidence !== false;
  document.getElementById("skip_solved_pull").checked = c.skip_solved_pull !== false;
  document.getElementById("round_rotate").checked = !!c.round_rotate;
  document.getElementById("rotate_batch").value = c.rotate_batch || 0;
  document.getElementById("max_environments").value = c.max_environments || 0;
  document.getElementById("deepseek_base_url").value = c.deepseek_base_url || "";
  document.getElementById("dasctf_url").value = c.dasctf_url || "";
  document.getElementById("ctf2_url").value = c.ctf2_url || "";
  document.getElementById("ctf2_ground").value = c.ctf2_ground || "";
  document.getElementById("ctfplus_url").value = c.ctfplus_url || "";
  document.getElementById("ret2shell_url").value = c.ret2shell_url || "";
  document.getElementById("ret2shell_game").value = c.ret2shell_game || "";
  document.getElementById("ctfd_url").value = c.ctfd_url || "";
  renderModelList(c);
  for(const id of SECRETS){
    const el=document.getElementById(id); el.value="";
    el.placeholder = c[id+"_set"] ? ("已设置 "+(c[id+"_masked"]||"")) : "未设置";
  }
  renderProviders(c.providers||[]);
  updatePlatformBoxes();
}
function updatePlatformBoxes(){
  const p = document.getElementById("platform").value;
  for(const k of ["dasctf","ctf2","ctfplus","ret2shell","ctfd"]){
    document.getElementById("box-"+k).style.display = (p===k) ? "block" : "none";
  }
  document.getElementById("chip-plat").textContent = "平台：" + (PLAT_LABELS[p]||p);
}
document.getElementById("platform").onchange = updatePlatformBoxes;

function renderProviders(list){
  const box = document.getElementById("providers");
  if(!list || !list.length){ box.innerHTML = '<div class="hint">还没有自定义供应商</div>'; return; }
  box.innerHTML = list.map(p=>`<div class="prov">
      <div class="prov-head">
        <b>${esc(p.name)}</b>
        <span class="hint">${esc(p.base_url)}</span>
      </div>
      <div class="hint">Key: ${p.api_key_set ? "已设置 "+esc(p.api_key_masked) : "未设置"} · 模型 ${p.models.length} 个</div>
      <div class="btns" style="margin-top:6px">
        <button class="ghost" data-refetch="${esc(p.name)}">拉取模型</button>
        <button class="ghost" data-del="${esc(p.name)}">删除</button>
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-refetch]").forEach(b=>b.onclick=()=>fetchProviderModels(b.dataset.refetch));
  box.querySelectorAll("[data-del]").forEach(b=>b.onclick=async ()=>{
    if(!confirm("删除供应商 "+b.dataset.del+" ?")) return;
    const r=await fetch("/api/providers/delete",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({name:b.dataset.del})});
    const j=await r.json(); renderProviders(j.providers); provMsg("已删除","ok"); loadConfig();
  });
}
function provMsg(t, cls){ const m=document.getElementById("provmsg"); m.textContent=t; m.className="msg "+(cls||""); }

async function addProvider(){
  const name=document.getElementById("prov-name").value.trim();
  const base_url=document.getElementById("prov-url").value.trim();
  const api_key=document.getElementById("prov-key").value.trim();
  if(!name||!base_url){ provMsg("名称和 Base URL 必填","err"); return false; }
  const r=await fetch("/api/providers",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name,base_url,api_key})});
  const j=await r.json();
  if(!j.ok){ provMsg(j.error||"添加失败","err"); return false; }
  renderProviders(j.providers); provMsg("供应商已保存，可以点「拉取模型」","ok");
  loadConfig(); return true;
}
async function fetchProviderModels(name){
  const base_url=document.getElementById("prov-url").value.trim();
  const api_key=document.getElementById("prov-key").value.trim();
  provMsg("正在拉取 "+name+" 的模型…");
  const r=await fetch("/api/providers/fetch",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({name, base_url: name? base_url : "", api_key})});
  const j=await r.json();
  if(!j.ok){ provMsg("拉取失败: "+(j.error||""),"err"); return; }
  renderProviders(j.providers);
  provMsg(`拉到 ${j.models.length} 个模型，已加入模型列表（在上面勾选要用的）`, "ok");
  loadConfig();
}
document.getElementById("addprov").onclick = addProvider;
document.getElementById("fetchprov").onclick = async () => {
  const name = document.getElementById("prov-name").value.trim();
  if(!name){ provMsg("先填供应商名称","err"); return; }
  if(await addProvider()) await fetchProviderModels(name);
};

async function addModel(){
  const spec = document.getElementById("newmodel").value.trim();
  if(!spec){ return; }
  await fetch("/api/models",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify({models:[spec]})});
  document.getElementById("newmodel").value = "";
  document.getElementById("hint-newmodel").textContent = "已加入："+spec;
  loadConfig();
}
document.getElementById("addmodel").onclick = addModel;
document.getElementById("newmodel").onkeydown = e => { if(e.key==="Enter") addModel(); };

async function loadConfig(){
  try{ fillForm(await (await fetch("/api/config")).json()); }
  catch(e){ document.getElementById("cfgmsg").textContent = "读取配置失败: "+e; }
  try{
    const b = await (await fetch("/api/balance")).json();
    const hint = document.getElementById("bal-hint");
    if(b.ok && b.total!=null){
      hint.textContent = `官网余额 ${b.currency==="CNY"?"¥":"$"}${b.total}` +
        (b.spent!=null ? ` · 已用 ¥${Number(b.spent).toFixed(2)}（按余额差）` : "");
    }else{ hint.textContent = b.error || ""; }
  }catch(e){}
}
document.getElementById("bal-reset").onclick = async ()=>{
  try{
    const r = await fetch("/api/balance/reset",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
    const j = await r.json();
    if(j.ok){ cfgMsg("已把当前余额设为基准（已用归零）","ok"); loadConfig(); }
    else cfgMsg(j.error||"重置失败","err");
  }catch(e){ cfgMsg("重置失败: "+e,"err"); }
};
function cfgMsg(text, cls){ const m=document.getElementById("cfgmsg"); m.textContent=text; m.className="msg "+(cls||""); }

async function saveOnly(){
  const r = await fetch("/api/config",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(collectForm())});
  const j = await r.json();
  if(j.ok){ cfgMsg("已保存到 .env", "ok"); loadConfig(); }
  else cfgMsg("保存失败: "+(j.error||""), "err");
}
async function startRun(){
  const r = await fetch("/api/run/start",{method:"POST",headers:{"Content-Type":"application/json"},
    body:JSON.stringify(collectForm())});
  const j = await r.json();
  if(!j.ok){ cfgMsg(j.error||"启动失败", "err"); document.getElementById("chip-run").textContent="启动失败"; return false; }
  cfgMsg("已启动 pid "+j.pid, "ok");
  showPage("main"); pollRun();
  return true;
}
document.getElementById("save").onclick = saveOnly;
document.getElementById("save-start").onclick = startRun;
document.getElementById("start").onclick = startRun;
document.getElementById("resume-last").onclick = async () => {
  const form = collectForm();
  form.resume = "latest";
  const r = await fetch("/api/run/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});
  const j = await r.json();
  if(!j.ok){ cfgMsg(j.error||"启动失败", "err"); return; }
  cfgMsg("已从上次未完成的轮次继续，pid "+j.pid, "ok");
  showPage("main"); pollRun();
};
async function pollRuns(){
  try{
    const j = await (await fetch("/api/runs")).json();
    const runs = j.runs || [];
    const open = runs.filter(r=>!r.finished);
    const hint = document.getElementById("resume-hint");
    if(!hint) return;
    hint.textContent = open.length ? 上次未完成：（/ 已解） : "没有未完成的轮次";
  }catch(e){}
}
pollRuns(); setInterval(pollRuns, 15000);
document.getElementById("stop").onclick = async () => {
  await fetch("/api/run/stop",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});
  pollRun();
};
document.getElementById("toolist").onclick = () => {
  const plat = (CFG && CFG.platform) ? CFG.platform : "auto";
  alert("题目清单在命令行查看：\\n\\nuv run python scripts\\\\list_" + (plat==="ret2shell"?"ret2shell":"dasctf") + ".py\\n\\n它会以只读方式列出平台的题目、分值、难度和是否已解。");
};

async function pollRun(){
  try{
    const j = await (await fetch("/api/run")).json();
    const chip = document.getElementById("chip-run");
    const st = document.getElementById("runstate");
    if(j.concurrency && document.activeElement !== document.getElementById("conc")){
      document.getElementById("conc").value = j.concurrency;
    }
    if(j.running){
      const mins = Math.floor((Date.now()/1000 - j.started_at)/60);
      chip.innerHTML = '<b class="on">● 运行中</b>';
      st.innerHTML = `<span class="on">● 运行中</span> pid ${j.pid} · ${mins} 分钟 · 并发 ${j.concurrency||1}`;
    }else if(j.exit_code!=null){
      chip.textContent = "已结束";
      st.textContent = "○ 已结束，退出码 " + j.exit_code + "（日志 logs/" + j.log + "）";
    }else{
      chip.textContent = "未运行";
      st.textContent = "状态：未运行";
    }
  }catch(e){}
}

async function applyConcurrency(){
  const v = parseInt(document.getElementById("conc").value||"1",10)||1;
  try{
    const r = await fetch("/api/run/concurrency",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({value:v})});
    const j = await r.json();
    if(j.ok){ cfgMsg("并发数已设为 "+j.concurrency+"（运行中立即生效）","ok"); }
    else { cfgMsg(j.error||"设置失败","err"); }
  }catch(e){ cfgMsg("设置失败: "+e,"err"); }
}
document.getElementById("conc-apply").onclick = applyConcurrency;

async function pollBalance(){
  const el = document.getElementById("chip-bal");
  try{
    const j = await (await fetch("/api/balance")).json();
    if(j.ok && j.total!=null){
      const sym = (j.currency||"CNY").toUpperCase()==="CNY" ? "¥" : "$";
      el.textContent = "余额 " + sym + j.total;
      el.title = "DeepSeek 官方余额（" + (j.currency||"") + "）";
    }else{
      el.textContent = "";
      el.title = j.error || "";
    }
  }catch(e){ el.textContent = ""; }
}

function renderEvent(ev){
  const t = ev.type;
  if(t==='thinking') return `<div class="ev think">💭 ${esc((ev.text||'').slice(0,900))}</div>`;
  if(t==='tool_call') return `<div class="ev tool">› ${esc(ev.tool||'')} ${esc((ev.args||'').slice(0,400))}</div>`;
  if(t==='tool_result') return `<div class="ev result">‹ ${esc((ev.result||'').slice(0,600))}</div>`;
  if(t==='message') return `<div class="ev">${esc((ev.text||'').slice(0,600))}</div>`;
  if(t==='hint_injected') return `<div class="ev hintx">↵ 注入提示 x${ev.count||1}</div>`;
  if(t==='flag_confirmed') return `<div class="ev flag">✔ 提交成功</div>`;
  if(t==='start') return `<div class="ev result">—— 开始 ${esc(ev.challenge||'')} / ${esc(ev.model||'')}</div>`;
  return '';
}

function metaText(s){
  const bits=[];
  if(s.category) bits.push(s.category);
  if(s.value) bits.push(s.value+" 分");
  if(s.difficulty) bits.push(s.difficulty);
  return bits.join(" · ");
}

function renderSolvers(){
  const list = document.getElementById("slist");
  document.getElementById("chip-solvers").textContent = SOLVERS.length + " 个 solver";  if(!SOLVERS.length){ list.innerHTML = '<div class="empty">还没有 solver<br><small>到「配置」页点保存并开始</small></div>'; return; }
  if(!SELECTED || !SOLVERS.some(s=>s.key===SELECTED)) SELECTED = SOLVERS[0].key;
  list.innerHTML = SOLVERS.map(s=>`<div class="sitem ${s.key===SELECTED?"on":""} ${s.finished?"fin":""}" data-key="${esc(s.key)}" title="${esc(s.challenge)}">
      <span class="dot ${s.active?"on":""}"></span>
      <span class="col">
        <span class="nm" data-tip="${esc(s.challenge)}">${esc(s.challenge)}</span>
        <span class="md">${esc(metaText(s))}${metaText(s)?" · ":""}${esc(s.model||"")}${s.since?" · "+esc(s.since):""}</span>
      </span>
    </div>`).join("");
  list.querySelectorAll(".sitem").forEach(el=>el.onclick=()=>{ SELECTED = el.dataset.key; FORCE_BOTTOM = true; renderSolvers(); renderLog(); });
}

function renderLog(){
  const cur = SOLVERS.find(s=>s.key===SELECTED);
  const log = document.getElementById("log");
  const input = document.getElementById("hint-input");
  if(!cur){
    document.getElementById("pane-title").textContent = "选择一个题目观察";
    log.innerHTML = '<div class="empty">点击左侧题目查看思考与操作</div>';
    input.disabled = true; return;
  }
  const mt = metaText(cur);
  document.getElementById("pane-title").innerHTML = `${esc(cur.challenge)} ${mt?`<span class="md">${esc(mt)}</span>`:""} <span class="md">${esc(cur.model||"")}${cur.since?" · "+esc(cur.since):""}</span>`;
  const prevTop = log.scrollTop;
  const atBottom = FORCE_BOTTOM || log.scrollHeight - log.scrollTop - log.clientHeight < 60;
  FORCE_BOTTOM = false;
  log.innerHTML = (cur.events||[]).map(renderEvent).join('') || '<div class="empty">等待输出…</div>';
  // innerHTML resets scrollTop to 0 — restore it so reading does not jump.
  log.scrollTop = atBottom ? log.scrollHeight : prevTop;
  input.disabled = false;
  input.placeholder = `给 ${cur.challenge} 发提示，回车发送`;
  const skip = document.getElementById("skip");
  skip.disabled = !cur.active;
  skip.textContent = cur.active ? "跳过此题" : "已结束";
}

async function skipChallenge(){
  const cur = SOLVERS.find(s=>s.key===SELECTED);
  if(!cur) return;
  if(!confirm(`跳过「${cur.challenge}」？这道题会立刻停止，并发位让给下一题。`)) return;
  try{
    const r = await fetch('/api/solver/skip',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({challenge: cur.challenge})});
    const j = await r.json();
    if(j.ok){ cfgMsg("已请求跳过 "+cur.challenge,"ok"); }
    else { cfgMsg(j.error||"跳过失败","err"); }
  }catch(e){ cfgMsg("跳过失败: "+e,"err"); }
}

async function refresh(){
  if(PAGE!=="main") return;
  const all = '?all=1';
  try{
    const j = await (await fetch('/api/state'+all)).json();
    SOLVERS = (j.solvers||[]).map(s=>({...s, key: s.file || s.challenge}));
    renderSolvers(); renderLog();
  }catch(e){}
}

async function sendHint(){
  const cur = SOLVERS.find(s=>s.key===SELECTED);
  const input = document.getElementById("hint-input");
  const text = input.value.trim();
  if(!cur || !text) return;
  await fetch('/api/hint',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({challenge: cur.challenge, text})});
  input.value = '';
}
document.getElementById("hint-send").onclick = sendHint;
document.getElementById("hint-input").onkeydown = e => { if(e.key==='Enter') sendHint(); };

// 左侧题目栏宽度可拖动，双击恢复默认；宽度记在 localStorage
document.getElementById("skip").onclick = skipChallenge;

(function(){
  const KEY = "ctf-rail-w";
  const saved = localStorage.getItem(KEY);
  if(saved) document.documentElement.style.setProperty("--rail-w", saved);
  const sp = document.getElementById("splitter");
  let dragging = false;
  sp.addEventListener("mousedown", e => { dragging = true; e.preventDefault(); document.body.style.userSelect = "none"; });
  window.addEventListener("mousemove", e => {
    if(!dragging) return;
    const w = Math.max(200, Math.min(e.clientX - 14, window.innerWidth - 380));
    document.documentElement.style.setProperty("--rail-w", w + "px");
  });
  window.addEventListener("mouseup", () => {
    if(!dragging) return;
    dragging = false; document.body.style.userSelect = "";
    localStorage.setItem(KEY, getComputedStyle(document.documentElement).getPropertyValue("--rail-w").trim());
  });
  sp.addEventListener("dblclick", () => {
    document.documentElement.style.setProperty("--rail-w", "330px");
    localStorage.setItem(KEY, "330px");
  });
})();

setInterval(refresh, 1500);
setInterval(pollRun, 3000);
setInterval(pollBalance, 60000);
setInterval(pollBoard, 5000);

async function pollBoard(){
  try{
    const j = await (await fetch("/api/board")).json();
    renderBoard(j);
  }catch(e){}
}

function renderBoard(j){
  const box = document.getElementById("board");
  const scope = document.getElementById("bscope");
  const groups = (j && j.groups) || [];
  if(scope) scope.textContent = (j.scope === "all" ? "全部" : "本批") + (j.total ? ` · ${j.solved}/${j.total}` : "") + (j.error ? ` · ${j.error}` : "");
  if(scope) scope.title = j.error || "";
  if(!groups.length){ box.innerHTML = '<div class="empty">还没有题目</div>'; return; }
  box.innerHTML = groups.map(g=>{
    const done = g.items.filter(i=>i.solved).length;
    return `<div class="bgroup"><div class="gtitle"><span>${esc(g.label||g.category)}</span><span>${done}/${g.items.length}</span></div>
      <div class="grid">${g.items.map(i=>{
        const cls = "sq" + (i.solved?" solved":"") + (i.active?" active":"");
        const tip = [i.name, i.difficulty, i.value?i.value+" 分":""].filter(Boolean).join(" · ");
        return `<div class="${cls}" data-tip="${esc(tip)}">${esc((i.name||"?").slice(0,2))}</div>`;
      }).join("")}</div></div>`;
  }).join("");
}

renderChecks();
refresh(); pollRun(); pollBalance(); pollBoard(); loadConfig();

// Instant tooltip: native title has a ~1s delay and clips long names.
const TIP = document.getElementById("tip");
function tipPlace(x, y){
  const pad = 14;
  let left = x + pad, top = y + pad;
  const r = TIP.getBoundingClientRect();
  if(left + r.width > window.innerWidth - 8) left = Math.max(8, x - r.width - pad);
  if(top + r.height > window.innerHeight - 8) top = Math.max(8, y - r.height - pad);
  TIP.style.left = left + "px";
  TIP.style.top = top + "px";
}
document.addEventListener("mouseover", e => {
  const el = e.target.closest && e.target.closest("[data-tip]");
  if(!el) return;
  TIP.textContent = el.getAttribute("data-tip") || "";
  TIP.style.opacity = "1";
  tipPlace(e.clientX, e.clientY);
});
document.addEventListener("mousemove", e => {
  if(TIP.style.opacity === "1") tipPlace(e.clientX, e.clientY);
});
document.addEventListener("mouseout", e => {
  if(e.target.closest && e.target.closest("[data-tip]")) TIP.style.opacity = "0";
});
window.addEventListener("scroll", () => { TIP.style.opacity = "0"; }, true);
</script></body></html>
"""


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
                save_config(payload)
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
                        pass
                self._json(200, {"ok": True, "models": models, "providers": _providers_view()})
                return
            if path == "/api/models":
                models = [str(m) for m in (self._read_json().get("models") or [])]
                self._json(200, {"ok": True, "models": add_extra_models(models)})
                return
            if path == "/api/run/start":
                self._json(200, RUN.start(self._read_json()))
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
    """Return the PID listening on ``port`` (Windows only)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=20
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].startswith("TCP") and parts[1].endswith(f":{port}"):
            if parts[3].upper() == "LISTENING" and parts[4].isdigit():
                return int(parts[4])
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
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(old)], capture_output=True)
            time.sleep(1.5)
            old = _listener_pid(port)
        return DashboardServer((host, port), Handler)


def _kill_other_dashboards() -> None:
    """Make sure only one dashboard process survives (Windows keeps them around)."""
    if os.name != "nt":
        return
    try:
        me = os.getpid()
        script = (
            "Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and "
            f"$_.CommandLine -like '*webui.py*' -and $_.ProcessId -ne {me} }} | "
            "ForEach-Object { taskkill /F /T /PID $_.ProcessId }"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=20,
        )
    except Exception:  # noqa: BLE001 - best effort
        pass


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
