"""Per-model spending limits, persisted in ``config/model_quotas.json``.

Two accounting modes:

* ``deepseek/*`` models are billed in CNY by the official API, so their limit
  and spend follow the **official balance** (``GET /user/balance``): spend =
  baseline - current balance. The baseline is captured the first time a
  balance is seen (or when the user resets it), which makes the number in the
  dashboard match the DeepSeek website exactly.
* every other provider (custom OpenAI-compatible endpoints) is tracked in USD
  from the token usage we observe, because there is no balance API to query.

The CLI/round runner skip specs whose budget is exhausted.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

STORE = Path("config") / "model_quotas.json"
_LOCK = threading.Lock()
OFFICIAL_PREFIX = "deepseek/"
BALANCE_FRESH_S = 900.0


def _read() -> dict[str, Any]:
    try:
        raw = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    models = raw.get("models")
    if not isinstance(models, dict):
        # Migrate the old flat {spec: {...}} layout.
        models = {
            str(k): dict(v or {})
            for k, v in raw.items()
            if isinstance(v, dict) and k not in ("models", "balance")
        }
    balance = raw.get("balance") if isinstance(raw.get("balance"), dict) else {}
    return {"models": models, "balance": dict(balance)}


def _write(data: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load() -> dict[str, Any]:
    with _LOCK:
        return _read()


def record_balance(total_cny: float) -> dict[str, Any]:
    """Remember the latest official balance; capture and re-base on top-ups.

    ``carried`` accumulates what was spent before a recharge: a balance can go
    *up* (top-up) or be edited by the platform, and simply doing
    ``baseline - value`` would then report 0 (or a negative number).
    """
    value = float(total_cny)
    with _LOCK:
        data = _read()
        balance = dict(data["balance"])
        previous = balance.get("value")
        baseline = balance.get("baseline")
        if baseline is None or previous is None:
            balance["baseline"] = value
            balance["baseline_at"] = time.time()
            balance["carried"] = float(balance.get("carried") or 0.0)
        elif baseline is not None and float(value) > float(baseline) + 0.005 and "carried" not in balance:
            # Migration for stores written before top-up tracking: the balance
            # is already above the old baseline, so seed ``carried`` with the
            # token-cost estimate (~7.2 CNY per USD) and re-base.
            est_usd = sum(
                float(entry.get("spent_usd") or 0.0)
                for spec, entry in (data.get("models") or {}).items()
                if str(spec).startswith("deepseek/")
            )
            balance["carried"] = round(est_usd * 7.2, 6)
            balance["baseline"] = value
            balance["baseline_at"] = time.time()
        elif value > float(previous) + 0.005:
            # Balance went up: fold the spend since the last baseline into
            # ``carried`` and start a new baseline at the new balance.
            spent_since = max(0.0, float(baseline) - float(previous))
            balance["carried"] = round(float(balance.get("carried") or 0.0) + spent_since, 6)
            balance["baseline"] = value
            balance["baseline_at"] = time.time()
        balance["value"] = value
        balance["value_at"] = time.time()
        data["balance"] = balance
        _write(data)
    return dict(balance)


def reset_baseline(total_cny: float | None = None) -> dict[str, Any]:
    """Treat the current balance as "nothing spent yet"."""
    with _LOCK:
        data = _read()
        balance = dict(data["balance"])
        if total_cny is not None:
            balance["value"] = float(total_cny)
            balance["value_at"] = time.time()
            base = float(total_cny)
        else:
            base = float(balance.get("value") or 0.0)
        balance["baseline"] = base
        balance["baseline_at"] = time.time()
        data["balance"] = balance
        _write(data)
    return dict(balance)


def balance_info() -> dict[str, Any]:
    balance = load()["balance"]
    baseline = balance.get("baseline")
    value = balance.get("value")
    fresh = bool(value is not None) and time.time() - float(balance.get("value_at") or 0) < BALANCE_FRESH_S
    spent = None
    if baseline is not None and value is not None:
        carried = float(balance.get("carried") or 0.0)
        spent = round(carried + max(0.0, float(baseline) - float(value)), 6)
    return {
        "baseline": baseline,
        "value": value,
        "fresh": fresh,
        "spent_cny": spent,
        "at": balance.get("value_at"),
    }


def get(spec: str) -> dict[str, Any]:
    entry = dict(load()["models"].get(spec, {}))
    return {
        "limit_usd": float(entry.get("limit_usd") or 0.0),
        "spent_usd": float(entry.get("spent_usd") or 0.0),
        "limit_cny": float(entry.get("limit_cny") or 0.0),
    }


def set_limit(spec: str, limit: float, currency: str = "USD") -> dict[str, Any]:
    spec = str(spec or "").strip()
    if not spec:
        raise ValueError("model spec is required")
    value = max(0.0, float(limit or 0.0))
    key = "limit_cny" if str(currency).upper() == "CNY" else "limit_usd"
    with _LOCK:
        data = _read()
        entry = dict(data["models"].get(spec) or {})
        entry[key] = round(value, 6)
        entry.setdefault("spent_usd", 0.0)
        data["models"][spec] = entry
        _write(data)
    return {"spec": spec, key: value}


def add_spend(spec: str, usd: float) -> None:
    spec = str(spec or "").strip()
    if not spec or not usd or usd < 0:
        return
    with _LOCK:
        data = _read()
        entry = dict(data["models"].get(spec) or {})
        entry["spent_usd"] = round(float(entry.get("spent_usd") or 0.0) + float(usd), 6)
        data["models"][spec] = entry
        _write(data)


def reset_spend(spec: str) -> None:
    with _LOCK:
        data = _read()
        if spec in data["models"]:
            data["models"][spec]["spent_usd"] = 0.0
            _write(data)


def limit_of(spec: str) -> float:
    entry = get(spec)
    return entry["limit_cny"] if str(spec).startswith(OFFICIAL_PREFIX) else entry["limit_usd"]


def spent_of(spec: str) -> float:
    if str(spec).startswith(OFFICIAL_PREFIX):
        return float(balance_info().get("spent_cny") or 0.0)
    return get(spec)["spent_usd"]


def available(spec: str) -> bool:
    """True when the spec still has budget (no limit configured = unlimited)."""
    entry = get(spec)
    if str(spec).startswith(OFFICIAL_PREFIX):
        limit = entry["limit_cny"]
        if limit <= 0:
            return True
        info = balance_info()
        if info["spent_cny"] is not None and info["fresh"]:
            return float(info["spent_cny"]) < limit
        return entry["spent_usd"] < limit  # USD fallback (e.g. tiny limits)
    limit = entry["limit_usd"]
    if limit <= 0:
        return True
    return entry["spent_usd"] < limit


def view() -> dict[str, dict[str, Any]]:
    data = load()
    info = balance_info()
    out: dict[str, dict[str, Any]] = {}
    for spec, entry in data["models"].items():
        official = str(spec).startswith(OFFICIAL_PREFIX)
        limit = float(entry.get("limit_cny") or 0.0) if official else float(entry.get("limit_usd") or 0.0)
        spent = float(info.get("spent_cny") or 0.0) if official else float(entry.get("spent_usd") or 0.0)
        out[spec] = {
            "currency": "CNY" if official else "USD",
            "limit": limit,
            "spent": spent,
            "remaining": None if limit <= 0 else round(max(0.0, limit - spent), 6),
            "available": limit <= 0 or spent < limit,
        }
    return out

def refresh_balance(base_url: str, api_key: str, timeout: float = 10.0) -> float | None:
    """Pull the official balance once and remember it (used by the CLI)."""
    if not api_key:
        return None
    try:
        import urllib.request

        req = urllib.request.Request(
            str(base_url).rstrip("/") + "/user/balance",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        infos = body.get("balance_infos") or []
        total = float(infos[0].get("total_balance")) if infos else None
        if total is not None:
            record_balance(total)
        return total
    except Exception:  # noqa: BLE001 - quota check is best effort
        return None
