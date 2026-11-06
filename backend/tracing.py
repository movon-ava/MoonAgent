"""Per-tool-call JSONL event tracing — one file per solver, streamable via tail -f."""

from __future__ import annotations

import atexit
import json
import logging
import re
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Secrets that regularly show up in tool output (`cat .env`, `env`, JWT in
# localStorage) are masked before they hit the log, which otherwise keeps live
# credentials in plain text for as long as the trace is kept.
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}")
_SK_RE = re.compile(r"\bsk-[A-Za-z0-9_\-]{12,}")
_AK_RE = re.compile(r"\bak_[A-Za-z0-9_\-]{6,}")
_SESSION_RE = re.compile(r"SessionStore=[A-Za-z0-9_\-%.]{12,}")
_FLAG_RE = re.compile(r"([A-Za-z][A-Za-z0-9_+.\-]{0,15})\{([^\n{}]{4,200}?)\}")


def _mask_flag(match: re.Match[str]) -> str:
    prefix, body = match.group(1), match.group(2)
    kept = body[:2] if len(body) <= 6 else f"{body[:4]}…{body[-4:]}"
    return f"{prefix}{{{kept}}}"


def mask_secrets(text: str) -> str:
    """Mask flags, API keys and session tokens in one string."""
    if not text:
        return text
    text = _JWT_RE.sub("<jwt>", text)
    text = _SK_RE.sub("<api-key>", text)
    text = _AK_RE.sub("<access-key>", text)
    text = _SESSION_RE.sub("SessionStore=<token>", text)
    return _FLAG_RE.sub(_mask_flag, text)


def _mask_value(value):
    if isinstance(value, str):
        return mask_secrets(value)
    if isinstance(value, list):
        return [_mask_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _mask_value(item) for key, item in value.items()}
    return value


def _sanitize(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


class SolverTracer:
    """Append-only JSONL event tracer. Flushes every write for tail -f streaming."""

    def __init__(
        self,
        challenge_name: str,
        model_id: str,
        log_dir: str = "logs",
        mask: bool = True,
    ) -> None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.path = str(Path(log_dir) / f"trace-{_sanitize(challenge_name)}-{_sanitize(model_id)}-{ts}.jsonl")
        self.mask = mask
        self._fh = open(self.path, "a", encoding="utf-8", errors="replace")
        atexit.register(self._close)

    def close(self) -> None:
        """Explicitly close the trace file. Safe to call multiple times."""
        if not self._fh.closed:
            try:
                self._fh.close()
            except Exception:
                logger.debug("suppressed exception", exc_info=True)

    _close = close  # atexit compat

    def _write(self, event: dict) -> None:
        if self._fh.closed:
            return
        try:
            payload = {"ts": time.time(), **event}
            if self.mask:
                payload = _mask_value(payload)
            self._fh.write(json.dumps(payload) + "\n")
            self._fh.flush()
        except Exception:
            logger.debug("suppressed exception", exc_info=True)

    def tool_call(self, tool_name: str, args: dict | str, step: int) -> None:
        args_str = args if isinstance(args, str) else json.dumps(args)
        self._write({"type": "tool_call", "tool": tool_name, "args": args_str[:2000], "step": step})

    def tool_result(self, tool_name: str, result: str, step: int) -> None:
        self._write({"type": "tool_result", "tool": tool_name, "result": result[:2000], "step": step})

    def model_response(self, text: str, step: int, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self._write({"type": "model_response", "text": text[:1000], "step": step,
                      "input_tokens": input_tokens, "output_tokens": output_tokens})

    def thinking(self, text: str) -> None:
        """Model reasoning snippet (DeepSeek thinking) — useful for later review."""
        self._write({"type": "thinking", "text": text[:2000]})

    def message(self, text: str) -> None:
        """Model narration (assistant text part)."""
        self._write({"type": "message", "text": text[:2000]})

    def usage(self, input_tokens: int, output_tokens: int, cache_read: int, cost_usd: float) -> None:
        self._write({"type": "usage", "input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_read_tokens": cache_read, "cost_usd": round(cost_usd, 6)})

    def event(self, kind: str, **kwargs) -> None:
        self._write({"type": kind, **kwargs})
