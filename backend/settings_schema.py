"""The single source of truth for user-facing settings.

Every knob the dashboard can write needs four names: the :class:`Settings` field,
the ``.env`` key, the CLI flag, and the form control id (which equals the field
name). Keeping those four in sync by hand is how the panel silently stopped
saving ``trace_mask`` for a while, so they live here in one table.

``scripts/webui.py`` derives its ``.env`` mapping from :data:`SETTINGS`, and
``scripts/test_settings_schema.py`` fails when this table drifts away from
``backend/config.py``, ``.env.example`` or ``backend/cli.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_STR = "str"
KIND_INT = "int"
KIND_FLOAT = "float"
KIND_BOOL = "bool"
KIND_LIST = "list"  # comma separated in .env
KIND_ADDR = "addr"  # host/URL, never a secret


@dataclass(frozen=True)
class Setting:
    """One configurable knob.

    Args:
        field: attribute name on :class:`backend.config.Settings`.
        env: key written to ``.env``; also the environment variable read at startup.
        kind: one of the ``KIND_*`` constants; decides how a value is serialised.
        cli: the click flag that overrides it, ``None`` when CLI-only or absent.
    """

    field: str
    env: str
    kind: str = KIND_STR
    cli: str | None = None


SETTINGS: tuple[Setting, ...] = (
    # platform + credentials
    Setting("platform", "PLATFORM", KIND_STR, "--platform"),
    Setting("ret2shell_url", "RET2SHELL_URL", KIND_ADDR, "--ret2shell-url"),
    Setting("ret2shell_token", "RET2SHELL_TOKEN", KIND_STR, "--ret2shell-token"),
    Setting("ret2shell_game", "RET2SHELL_GAME", KIND_STR, "--game"),
    Setting("dasctf_url", "DASCTF_URL", KIND_ADDR, "--dasctf-url"),
    Setting("dasctf_access_key", "DASCTF_ACCESS_KEY", KIND_STR, "--access-key"),
    Setting("ctf2_url", "CTF2_URL", KIND_ADDR, "--ctf2-url"),
    Setting("ctf2_token", "CTF2_AGENT_TOKEN", KIND_STR, "--ctf2-token"),
    Setting("ctf2_ground", "CTF2_GROUND", KIND_STR, "--ctf2-ground"),
    Setting("ctfplus_url", "CTFPLUS_URL", KIND_ADDR, "--ctfplus-url"),
    Setting("ctfplus_token", "CTFPLUS_TOKEN", KIND_STR),
    Setting("ctfd_url", "CTFD_URL", KIND_ADDR, "--ctfd-url"),
    Setting("ctfd_token", "CTFD_TOKEN", KIND_STR, "--ctfd-token"),
    # models
    Setting("default_models", "DEFAULT_MODELS", KIND_LIST, "--models"),
    Setting("deepseek_api_key", "DEEPSEEK_API_KEY", KIND_STR),
    Setting("deepseek_base_url", "DEEPSEEK_BASE_URL", KIND_ADDR),
    Setting("role_models", "ROLE_MODELS", KIND_STR),
    # what to solve
    Setting("challenge_categories", "CHALLENGE_CATEGORIES", KIND_LIST, "--categories"),
    Setting("challenge_difficulty", "CHALLENGE_DIFFICULTY", KIND_LIST, "--difficulty"),
    Setting("round_size", "ROUND_SIZE", KIND_INT, "--round"),
    Setting("round_only", "ROUND_ONLY", KIND_STR, "--only"),
    Setting("round_order", "ROUND_ORDER", KIND_STR, "--order"),
    Setting("round_min_score", "ROUND_MIN_SCORE", KIND_INT, "--min-score"),
    Setting("round_include_solved", "ROUND_INCLUDE_SOLVED", KIND_BOOL, "--include-solved"),
    Setting("round_cooldown_hours", "ROUND_COOLDOWN_HOURS", KIND_FLOAT),
    Setting("round_rotate", "ROUND_ROTATE", KIND_BOOL, "--rotate/--no-rotate"),
    Setting("rotate_batch", "ROTATE_BATCH", KIND_INT, "--rotate-batch"),
    # limits
    Setting("max_concurrent_challenges", "MAX_CONCURRENT_CHALLENGES", KIND_INT, "--max-challenges"),
    Setting("max_environments", "MAX_ENVIRONMENTS", KIND_INT, "--max-env"),
    Setting("max_attachment_workers", "MAX_ATTACHMENT_WORKERS", KIND_INT),
    Setting("max_target_workers", "MAX_TARGET_WORKERS", KIND_INT),
    Setting("challenge_timeout_min", "CHALLENGE_TIMEOUT_MIN", KIND_FLOAT, "--challenge-timeout"),
    Setting("challenge_extra_rounds", "CHALLENGE_EXTRA_ROUNDS", KIND_INT, "--extra-rounds"),
    Setting("max_attempts_per_challenge", "MAX_ATTEMPTS_PER_CHALLENGE", KIND_INT),
    # behaviour
    Setting("writeup_enabled", "WRITEUP_ENABLED", KIND_BOOL, "--writeup/--no-writeup"),
    Setting("writeup_dir", "WRITEUP_DIR", KIND_STR),
    Setting("flag_format", "FLAG_FORMAT", KIND_STR, "--flag-format"),
    Setting("flag_submit_mode", "FLAG_SUBMIT_MODE", KIND_STR, "--flag-submit-mode"),
    Setting("think_chinese", "THINK_CHINESE", KIND_BOOL, "--think-chinese/--no-think-chinese"),
    Setting("skip_solved_pull", "SKIP_SOLVED_PULL", KIND_BOOL, "--skip-solved/--no-skip-solved"),
    Setting(
        "require_flag_evidence",
        "REQUIRE_FLAG_EVIDENCE",
        KIND_BOOL,
        "--require-evidence/--no-require-evidence",
    ),
    Setting("knowledge_enabled", "KNOWLEDGE_ENABLED", KIND_BOOL, "--knowledge/--no-knowledge"),
    Setting("trace_mask", "TRACE_MASK", KIND_BOOL, "--trace-mask/--no-trace-mask"),
    Setting("context_limit_chars", "CONTEXT_LIMIT_CHARS", KIND_INT),
    # sandbox
    Setting("sandbox_image", "SANDBOX_IMAGE", KIND_STR, "--image"),
    Setting("container_memory_limit", "CONTAINER_MEMORY_LIMIT", KIND_STR),
)

BY_FIELD: dict[str, Setting] = {s.field: s for s in SETTINGS}
BY_ENV: dict[str, Setting] = {s.env: s for s in SETTINGS}

# Fields the dashboard form owns (the rest are edited by hand, e.g. role_models).
# Names are ``Settings`` attributes; the form control id may be a short alias,
# see :data:`FORM_ALIASES`.
PANEL_FIELDS: tuple[str, ...] = (
    "platform",
    "default_models",
    "round_size",
    "max_concurrent_challenges",
    "challenge_timeout_min",
    "challenge_extra_rounds",
    "max_environments",
    "challenge_categories",
    "challenge_difficulty",
    "round_order",
    "round_include_solved",
    "round_rotate",
    "rotate_batch",
    "writeup_enabled",
    "flag_format",
    "flag_submit_mode",
    "think_chinese",
    "skip_solved_pull",
    "require_flag_evidence",
    "trace_mask",
    "ret2shell_url",
    "ret2shell_token",
    "ret2shell_game",
    "dasctf_url",
    "dasctf_access_key",
    "ctf2_url",
    "ctf2_token",
    "ctf2_ground",
    "ctfplus_url",
    "ctfplus_token",
    "ctfd_url",
    "ctfd_token",
    "deepseek_api_key",
    "deepseek_base_url",
)

# Short form ids that predate the schema (the HTML inputs keep these ids).
# ``min_score`` is intentionally absent: it is no longer a form control, so the
# panel never writes ROUND_MIN_SCORE (edit .env or use --min-score).
FORM_ALIASES: dict[str, str] = {
    "models": "default_models",
    "categories": "challenge_categories",
    "difficulty": "challenge_difficulty",
    "include_solved": "round_include_solved",
    "max_concurrent": "max_concurrent_challenges",
}

SECRET_FIELDS: frozenset[str] = frozenset(
    {
        "ret2shell_token",
        "dasctf_access_key",
        "ctf2_token",
        "ctfplus_token",
        "ctfd_token",
        "deepseek_api_key",
    }
)


# Fields whose form control is a checkbox group or computed input instead of a
# single ``id="<field>"`` element. Value = a snippet that must exist in the HTML.
CUSTOM_CONTROLS: dict[str, str] = {
    "challenge_categories": 'id="cat-box"',
    "challenge_difficulty": 'id="diff-box"',
}


def render_env_value(setting: Setting, value: object) -> str:
    """Serialise a form value the way ``.env`` expects it."""
    if setting.kind == KIND_LIST:
        if isinstance(value, str):
            return value
        return ",".join(str(item).strip() for item in (value or []) if str(item).strip())
    if setting.kind == KIND_BOOL:
        return "1" if value else "0"
    if value is None:
        return ""
    return str(value)


def form_env_keys() -> dict[str, str]:
    """``{form id: ENV_KEY}`` for the fields the panel may write."""
    keys: dict[str, str] = {}
    for field in PANEL_FIELDS:
        form_id = next((alias for alias, target in FORM_ALIASES.items() if target == field), field)
        keys[form_id] = BY_FIELD[field].env
    return keys


def setting_for(key: str) -> Setting | None:
    """Look a setting up by form id or ``Settings`` attribute name."""
    return BY_FIELD.get(FORM_ALIASES.get(key, key))


def cli_flags() -> list[str]:
    """Every click flag declared in the table (first alias only)."""
    flags: list[str] = []
    for setting in SETTINGS:
        if not setting.cli:
            continue
        flags.append(setting.cli.split("/")[0].strip())
    return flags
