"""Model resolution — Bedrock, Azure OpenAI, Zen, DeepSeek, Google AI Studio."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import boto3
import httpx
from pydantic_ai.models import Model
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models.openai import OpenAIModel, OpenAIModelSettings
from pydantic_ai.profiles.openai import OpenAIModelProfile
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai.providers.google import GoogleProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

if TYPE_CHECKING:
    from backend.config import Settings

logger = logging.getLogger(__name__)

# base_url -> is the provider reachable without a proxy?
_DIRECT_CACHE: dict[str, bool] = {}


def _direct_reachable(base_url: str) -> bool:
    """Probe the provider directly (ignoring HTTP(S)_PROXY) once per process.

    A local proxy that is not running (the common case: the user closed their
    VPN) makes every model call fail with "Connection error" even though the
    API is reachable directly. The probe lets us bypass a dead proxy instead of
    failing every solver at step 0.
    """
    if base_url in _DIRECT_CACHE:
        return _DIRECT_CACHE[base_url]
    ok = False
    try:
        with httpx.Client(trust_env=False, timeout=httpx.Timeout(3.0, connect=2.0)) as client:
            ok = client.get(base_url, follow_redirects=True).status_code < 500
    except Exception as exc:  # noqa: BLE001 - a probe failure just means "not direct"
        logger.debug("direct probe of %s failed: %s", base_url, exc)
    _DIRECT_CACHE[base_url] = ok
    logger.info("model endpoint %s: direct reachable=%s", base_url, ok)
    return ok


def _provider_http_client(base_url: str, mode: str = "") -> httpx.AsyncClient:
    """httpx client for the model provider, with a sane proxy policy.

    ``LLM_TRUST_ENV=1`` always honours HTTP(S)_PROXY, ``=0`` never does. Unset
    (default) probes the endpoint directly and only falls back to the proxy when
    a direct connection is impossible.
    """
    mode = str(mode or os.environ.get("LLM_TRUST_ENV", "") or "").strip().lower()
    if mode in ("1", "true", "yes", "on"):
        trust_env = True
    elif mode in ("0", "false", "no", "off"):
        trust_env = False
    else:
        trust_env = not _direct_reachable(base_url)
    return httpx.AsyncClient(
        trust_env=trust_env,
        timeout=httpx.Timeout(300.0, connect=15.0),
    )


def _trust_mode(settings: object) -> str:
    """LLM_TRUST_ENV from Settings (.env) so the dashboard can steer proxies."""
    return str(getattr(settings, "llm_trust_env", "") or "").strip()


def _openai_provider(base_url: str, api_key: str, mode: str = "") -> OpenAIProvider:
    return OpenAIProvider(
        base_url=base_url,
        api_key=api_key,
        http_client=_provider_http_client(base_url, mode),
    )

# Default model specs — claude-sdk and codex providers use the new solver backends
DEFAULT_MODELS: list[str] = [
    "claude-sdk/claude-opus-4-6/medium",
    "claude-sdk/claude-opus-4-6/max",
    "codex/gpt-5.4",
    "codex/gpt-5.4-mini",
    "codex/gpt-5.3-codex",
]

# DeepSeek serves an OpenAI-compatible API, with a few quirks the profile has to
# describe:
# - thinking mode is on by default and REJECTS forced tool_choice ("required"),
#   so tools must always be selected with tool_choice="auto";
# - reasoning text arrives as `reasoning_content` and must not be sent back;
# - strict tool schemas / JSON-schema structured output are not supported.
DEEPSEEK_PROFILE = OpenAIModelProfile(
    supports_tools=True,
    supports_thinking=True,
    openai_chat_thinking_field="reasoning_content",
    openai_chat_send_back_thinking_parts=False,
    openai_supports_tool_choice_required=False,
    supports_json_schema_output=False,
    openai_supports_strict_tool_definition=False,
)

# DeepSeek only accepts these reasoning effort levels ("medium" is not valid)
_DEEPSEEK_EFFORT: dict[str, str] = {"low": "low", "medium": "high", "high": "high", "max": "max"}

# Context window sizes (tokens)
CONTEXT_WINDOWS: dict[str, int] = {
    "us.anthropic.claude-opus-4-6-v1": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "gpt-5.4": 1_000_000,
    "gpt-5.4-mini": 400_000,
    "gpt-5.3-codex": 1_000_000,
    "gpt-5.3-codex-spark": 128_000,
    "gemini-3-flash-preview": 1_000_000,
    "deepseek-flash": 1_048_576,
    "deepseek-v4-pro": 1_048_576,
    "deepseek-chat": 1_048_576,
}

# Models that support vision
VISION_MODELS: set[str] = {
    "us.anthropic.claude-opus-4-6-v1",
    "claude-opus-4-6",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gemini-3-flash-preview",
    "deepseek-flash",
}


def resolve_model(spec: str, settings: Settings) -> Model:
    """Resolve a 'provider/model_id' spec to a Pydantic AI Model."""
    provider = provider_from_spec(spec)
    model_id = model_id_from_spec(spec)
    match provider:
        case "bedrock":
            if settings.aws_bearer_token:
                return BedrockConverseModel(
                    model_id,
                    provider=BedrockProvider(
                        api_key=settings.aws_bearer_token,
                        region_name=settings.aws_region,
                    ),
                )
            else:
                session = boto3.Session()
                client = session.client("bedrock-runtime", region_name=settings.aws_region)
                return BedrockConverseModel(
                    model_id,
                    provider=BedrockProvider(bedrock_client=client),
                )
        case "azure":
            return OpenAIModel(
                model_id,
                provider=_openai_provider(
                    settings.azure_openai_endpoint,
                    settings.azure_openai_api_key,
                    _trust_mode(settings),
                ),
            )
        case "zen":
            return OpenAIModel(
                model_id,
                provider=_openai_provider(
                    "https://opencode.ai/zen/v1",
                    settings.opencode_zen_api_key,
                    _trust_mode(settings),
                ),
            )
        case "deepseek":
            if not settings.deepseek_api_key:
                raise ValueError(
                    "DeepSeek provider requires DEEPSEEK_API_KEY — add it to F:\\ctf_agent\\.env"
                )
            return OpenAIModel(
                model_id,
                provider=_openai_provider(
                    (settings.deepseek_base_url or "https://api.deepseek.com").rstrip("/"),
                    settings.deepseek_api_key,
                    _trust_mode(settings),
                ),
                profile=DEEPSEEK_PROFILE,
            )
        case "google":
            return GoogleModel(
                model_id,
                provider=GoogleProvider(api_key=settings.gemini_api_key),
            )
        case "claude-sdk" | "codex":
            raise ValueError(
                f"Provider '{provider}' uses its own solver backend, not Pydantic AI. "
                f"resolve_model() should not be called for {spec}."
            )
        case _:
            from backend.providers import get_provider

            custom = get_provider(provider)
            if custom is None:
                raise ValueError(f"Unknown provider: {provider}")
            if not str(custom.get("api_key") or "").strip():
                raise ValueError(
                    f"Provider '{provider}' has no API key — add one in 配置 → 模型配置 → 供应商"
                )
            return OpenAIModel(
                model_id,
                provider=_openai_provider(
                    str(custom["base_url"]).rstrip("/"),
                    str(custom["api_key"]),
                    _trust_mode(settings),
                ),
            )


def resolve_model_settings(spec: str) -> ModelSettings:
    """Get provider-specific model settings with caching enabled."""
    provider = spec.split("/", 1)[0]
    match provider:
        case "bedrock":
            return BedrockModelSettings(
                max_tokens=128_000,
                bedrock_cache_instructions=True,
                bedrock_cache_tool_definitions=True,
                bedrock_cache_messages=True,
            )
        case "azure" | "zen":
            # Azure/Zen use OpenAI chat completions — server-side prompt caching
            # is automatic, no explicit config needed. Set max_tokens to avoid
            # reserving the full context window.
            return OpenAIModelSettings(
                max_tokens=128_000,
            )
        case "google":
            return GoogleModelSettings(
                max_tokens=64_000,
                google_thinking_config={
                    "thinking_level": "high",
                    "include_thoughts": True,
                },
            )
        case "deepseek":
            # Thinking mode bills its reasoning as output tokens, so keep the
            # effort configurable per spec: deepseek/deepseek-flash/low|high|max
            effort = _DEEPSEEK_EFFORT.get(effort_from_spec(spec) or "high", "high")
            return OpenAIModelSettings(
                max_tokens=64_000,
                openai_reasoning_effort=effort,
                timeout=600,
            )
        case _:
            return ModelSettings(max_tokens=128_000)


def model_id_from_spec(spec: str) -> str:
    """Extract the model ID from a spec.

    Only DeepSeek uses a trailing effort suffix (``deepseek/deepseek-flash/max``),
    so everything after the first ``/`` is the model id elsewhere — custom
    providers route ids like ``openrouter/qwen/qwen3-235b``.
    """
    provider = provider_from_spec(spec)
    if "/" not in spec:
        return spec
    model_id = spec.split("/", 1)[1]
    if provider == "deepseek":
        effort = effort_from_spec(spec)
        if effort:
            model_id = model_id.rsplit("/", 1)[0]
    return model_id


def provider_from_spec(spec: str) -> str:
    """Extract the provider from a spec."""
    return spec.split("/", 1)[0]


def effort_from_spec(spec: str) -> str | None:
    """Extract effort level from a spec like 'claude-sdk/claude-opus-4-6/max'."""
    parts = spec.split("/")
    if len(parts) >= 3 and parts[2] in ("low", "medium", "high", "max"):
        return parts[2]
    return None


def supports_vision(spec: str) -> bool:
    """Check if a model spec supports vision."""
    return model_id_from_spec(spec) in VISION_MODELS


def context_window(spec: str) -> int:
    """Get context window size for a model spec."""
    return CONTEXT_WINDOWS.get(model_id_from_spec(spec), 200_000)


def default_model_specs(settings: Settings | None = None) -> list[str]:
    """Model specs to race when --models is not given.

    Set DEFAULT_MODELS in .env (comma separated) to override the built-in list,
    e.g. ``DEFAULT_MODELS=deepseek/deepseek-flash``.
    """
    raw = getattr(settings, "default_models", "") if settings is not None else ""
    specs = [s.strip() for s in raw.split(",") if s.strip()]
    return specs or list(DEFAULT_MODELS)
