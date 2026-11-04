"""Pydantic Settings — credentials from .env file + environment variables."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # CTFd
    ctfd_url: str = "http://localhost:8000"
    ctfd_user: str = "admin"
    ctfd_pass: str = "admin"
    ctfd_token: str = ""

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Provider-specific (optional, for Bedrock/Azure/Zen fallback)
    aws_region: str = "us-east-1"
    aws_bearer_token: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    opencode_zen_api_key: str = ""

    # DeepSeek (OpenAI-compatible API)
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"

    # Model specs used when --models is not passed (comma separated),
    # e.g. "deepseek/deepseek-flash,deepseek/deepseek-v4-pro"
    default_models: str = ""

    # Platform: "auto" | "ctfd" | "ret2shell" | "dasctf" | "ctf2"
    # (auto = ret2shell when a ret2shell token is set, dasctf when a DASCTF
    # access key is set, ctf2 when an agent token is set, otherwise ctfd)
    platform: str = "auto"

    # CTF² Agent Arena (ctf2.dasctf.com) — agent PAT from the connect page.
    ctf2_url: str = "https://ctf2.dasctf.com"
    ctf2_token: str = Field(
        "",
        validation_alias=AliasChoices("CTF2_AGENT_TOKEN", "CTF2_TOKEN"),
    )
    # Optional practice ground id/slug; empty = every practice ground.
    ctf2_ground: str = ""

    # CTF+ (ctfplus) sites such as geek2026.play.ctfplus.cn.
    # The token is the browser's `SessionStore` cookie value.
    ctfplus_url: str = "https://geek2026.play.ctfplus.cn"
    ctfplus_token: str = Field(
        "",
        validation_alias=AliasChoices("CTFPLUS_TOKEN", "CTFPLUS_SESSION"),
    )

    # DASCTF (羊城杯 / DASCTF online matches, AI Agent API)
    dasctf_url: str = "https://pro.dasctf.com"
    # Per-stage access key from the player console's 平台接入凭证 panel.
    dasctf_access_key: str = ""

    # Ret2Shell (西电 CTF 终端 / MoeCTF)
    ret2shell_url: str = "https://ctf.xidian.edu.cn"
    # Session token from localStorage.account.token (browser devtools).
    ret2shell_token: str = ""
    # Game id ("37"), game name ("MoeCTF 2026"), or "" for the active game.
    ret2shell_game: str = ""
    # Directions to pull (comma separated): web, misc, pwn, re, crypto.
    # "all" (or empty) disables the filter and pulls every category.
    challenge_categories: str = "web,misc,pwn,re,crypto"
    # Difficulty levels to pull (comma separated): 入门, 简单, 中等, 困难
    # (English aliases easy/medium/hard work too). Empty = all difficulties.
    challenge_difficulty: str = ""

    # Round mode: solve N unsolved challenges then exit (0 = disabled).
    round_size: int = 0
    # Round mode: skip challenges worth less than this (drops 0-point
    # "participation" tasks no solver can flag); 0 = keep everything.
    round_min_score: int = 1
    # Round mode: only solve challenges whose name contains one of these
    # substrings (comma separated, empty = no filter).
    round_only: str = ""
    # Round mode: how to pick challenges — "random" (default), "score" (cheapest
    # first) or "name" (alphabetical).
    round_order: str = "random"
    # Round mode: skip challenges attempted within this many hours so repeated
    # rounds explore the pool instead of re-picking the same ones (0 = disabled).
    round_cooldown_hours: float = 6.0
    # Round mode: also allow challenges already solved on the platform
    # (they compete with the unsolved ones; --only is the usual way to pick one).
    round_include_solved: bool = False
    # Round mode: attempt history file (also used by --retry bookkeeping).
    round_history_file: str = "logs/round-history.json"

    # Editable prompt file with flag format + submission rules (injected into
    # the solver system prompt). Relative to the working directory.
    instructions_file: str = "INSTRUCTIONS.md"

    # Infra
    sandbox_image: str = "ctf-sandbox"
    max_concurrent_challenges: int = 10
    # 0 = use the platform's own quota (CTF² reports max_environments).
    max_environments: int = 0
    # Per-challenge wall-clock budget in minutes; 0 disables the timeout.
    challenge_timeout_min: float = 0.0
    # Extra swarm rounds for a challenge that came back unsolved (0 = none).
    challenge_extra_rounds: int = 0
    # After a challenge is solved, write a Chinese writeup into writeup_dir.
    writeup_enabled: bool = False
    writeup_dir: str = "writeups"
    # Renew live challenge targets every N seconds so they do not expire
    # mid-solve (0 disables the heartbeat).
    env_heartbeat_s: float = 300.0
    # Minimum gap between two platform API requests (seconds). The DASCTF/CTF²
    # APIs rate-limit bursts; 0.8s is the reference agent's floor.
    platform_request_interval: float = 0.8
    # Worker pools: attachment-only challenges vs challenges that need a target.
    max_attachment_workers: int = 4
    max_target_workers: int = 0  # 0 = platform quota (CTF2 max_environments)
    # Drill mode: solve one direction per batch (misc -> re -> crypto -> ...).
    round_rotate: bool = False
    # Batch size for drill mode; 0 = concurrency.
    rotate_batch: int = 0
    max_attempts_per_challenge: int = 3
    container_memory_limit: str = "16g"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }
