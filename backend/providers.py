"""Custom OpenAI-compatible model providers.

DeepSeek, Bedrock, Azure and Google have first-class support in
``backend.models``. Everything else — OpenRouter, Moonshot, SiliconFlow, a local
vLLM/Ollama gateway, any ``/v1/chat/completions`` endpoint — is registered here:

    {"providers": [{"name": "openrouter",
                    "base_url": "https://openrouter.ai/api/v1",
                    "api_key": "sk-or-...",
                    "models": ["qwen/qwen3-235b", "moonshotai/kimi-k2"]}],
     "extra_models": ["openrouter/qwen/qwen3-235b"]}

Model specs stay ``provider/model-id``, so ``resolve_model("openrouter/…")``
works exactly like the built-in providers. The file is gitignored because it
holds API keys.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "config" / "providers.json"

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")


def _empty_store() -> dict[str, Any]:
    return {"providers": [], "extra_models": []}


def load_store() -> dict[str, Any]:
    """Read the provider registry, tolerating a missing or broken file."""
    if not STORE.exists():
        return _empty_store()
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_store()
    if not isinstance(data, dict):
        return _empty_store()
    data.setdefault("providers", [])
    data.setdefault("extra_models", [])
    if not isinstance(data["providers"], list):
        data["providers"] = []
    if not isinstance(data["extra_models"], list):
        data["extra_models"] = []
    return data


def save_store(data: dict[str, Any]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_provider(name: str) -> dict[str, Any] | None:
    """Return one registered provider by name (case-insensitive)."""
    name = (name or "").strip().lower()
    for prov in load_store()["providers"]:
        if str(prov.get("name", "")).lower() == name:
            return prov
    return None


def upsert_provider(name: str, base_url: str = "", api_key: str = "") -> dict[str, Any]:
    """Create or update a provider; an empty api_key keeps the stored one."""
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise ValueError("供应商名称只能用字母、数字、点、下划线或连字符（1-40 字符）")
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise ValueError("Base URL 必须以 http:// 或 https:// 开头")

    data = load_store()
    for prov in data["providers"]:
        if str(prov.get("name", "")).lower() == name:
            prov["base_url"] = base_url
            if (api_key or "").strip():
                prov["api_key"] = api_key.strip()
            save_store(data)
            return prov
    prov = {"name": name, "base_url": base_url, "api_key": (api_key or "").strip(), "models": []}
    data["providers"].append(prov)
    save_store(data)
    return prov


def delete_provider(name: str) -> bool:
    name = (name or "").strip().lower()
    data = load_store()
    before = len(data["providers"])
    data["providers"] = [p for p in data["providers"] if str(p.get("name", "")).lower() != name]
    if len(data["providers"]) == before:
        return False
    prefix = f"{name}/"
    data["extra_models"] = [m for m in data["extra_models"] if not str(m).startswith(prefix)]
    save_store(data)
    return True


def set_provider_models(name: str, models: list[str]) -> None:
    """Remember the model ids discovered for a provider."""
    name = (name or "").strip().lower()
    data = load_store()
    for prov in data["providers"]:
        if str(prov.get("name", "")).lower() == name:
            prov["models"] = [str(m).strip() for m in models if str(m).strip()]
            save_store(data)
            return
    raise ValueError(f"没有这个供应商: {name}")


def add_extra_models(models: list[str]) -> list[str]:
    """Remember manual model specs so they stay in the picker."""
    data = load_store()
    current = [str(m) for m in data["extra_models"]]
    for spec in models:
        spec = str(spec).strip()
        if spec and spec not in current:
            current.append(spec)
    data["extra_models"] = current
    save_store(data)
    return current


def known_model_specs() -> list[str]:
    """Every model spec the registry knows about (provider models + manual)."""
    data = load_store()
    out: list[str] = [str(m) for m in data["extra_models"]]
    for prov in data["providers"]:
        name = str(prov.get("name", "")).strip()
        for model in prov.get("models", []) or []:
            out.append(f"{name}/{model}")
    return out


def fetch_models(base_url: str, api_key: str = "", timeout: float = 20.0) -> list[str]:
    """GET ``{base_url}/models`` and return the ids it advertises.

    Most OpenAI-compatible servers answer ``{"data": [{"id": ...}]}``; a bare
    list is accepted too. Raises ValueError with a readable message on failure.
    """
    base_url = (base_url or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("缺少 Base URL")
    url = f"{base_url}/models"
    headers = {"Accept": "application/json"}
    if (api_key or "").strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"
    try:
        resp = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise ValueError(f"连接失败: {exc}") from exc
    if resp.status_code >= 400:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise ValueError("返回的不是 JSON（可能不是 OpenAI 兼容接口）") from exc

    rows: list[Any] = []
    if isinstance(payload, dict):
        rows = payload.get("data") or payload.get("models") or []
    elif isinstance(payload, list):
        rows = payload

    ids: list[str] = []
    for row in rows:
        if isinstance(row, str):
            ids.append(row)
        elif isinstance(row, dict):
            value = row.get("id") or row.get("name") or row.get("model")
            if value:
                ids.append(str(value))
    return sorted(dict.fromkeys(ids))
