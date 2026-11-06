"""Guard the settings table against drift.

``backend/settings_schema.py`` claims to be the single source of truth for the
knobs the dashboard can edit. This script checks that claim:

* every field exists on ``Settings`` and has a matching type;
* every ``.env`` key is documented in ``.env.example``;
* every panel field still has a control in the HTML;
* every CLI flag in the table exists in ``backend/cli.py``;
* ``scripts/webui.py`` derives its ``.env`` mapping from the table.

Run with:  uv run python scripts/test_settings_schema.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import settings_schema as schema  # noqa: E402
from backend.config import Settings  # noqa: E402

KIND_TO_TYPE = {
    schema.KIND_STR: str,
    schema.KIND_ADDR: str,
    schema.KIND_LIST: str,
    schema.KIND_INT: int,
    schema.KIND_FLOAT: float,
    schema.KIND_BOOL: bool,
}


def check_fields_exist() -> None:
    settings = Settings()
    for setting in schema.SETTINGS:
        assert hasattr(settings, setting.field), f"{setting.field} is not a Settings field"
        value = getattr(settings, setting.field)
        expected = KIND_TO_TYPE[setting.kind]
        assert isinstance(value, expected), (
            f"{setting.field}: kind {setting.kind} expects {expected.__name__}, "
            f"got {type(value).__name__}"
        )
    print(f"fields ok: {len(schema.SETTINGS)} settings")


def check_uniqueness() -> None:
    fields = [s.field for s in schema.SETTINGS]
    envs = [s.env for s in schema.SETTINGS]
    assert len(fields) == len(set(fields)), "duplicate field in SETTINGS"
    assert len(envs) == len(set(envs)), "duplicate env key in SETTINGS"
    for field in schema.PANEL_FIELDS:
        assert field in schema.BY_FIELD, f"panel field {field} is missing from SETTINGS"
    for field in schema.SECRET_FIELDS:
        assert field in schema.BY_FIELD, f"secret field {field} is missing from SETTINGS"
        assert schema.BY_FIELD[field].kind in (schema.KIND_STR, schema.KIND_ADDR)
    print("uniqueness ok")


def check_env_example() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    declared = {
        line.split("=", 1)[0].strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    missing = [s.env for s in schema.SETTINGS if s.env not in declared]
    assert not missing, f".env.example is missing: {missing}"
    print(f".env.example ok: {len(declared)} keys")


def check_panel_controls() -> None:
    html = (ROOT / "scripts" / "webui_assets.py").read_text(encoding="utf-8")
    missing = []
    for form_id in schema.form_env_keys():
        field = schema.FORM_ALIASES.get(form_id, form_id)
        snippet = schema.CUSTOM_CONTROLS.get(field)
        if snippet is None:
            snippet = f'id="{form_id}"'
        if snippet not in html:
            missing.append(f"{form_id} ({snippet})")
    assert not missing, f"no control in the dashboard HTML for: {missing}"
    print(f"panel controls ok: {len(schema.form_env_keys())} fields")


def check_cli_flags() -> None:
    cli = (ROOT / "backend" / "cli.py").read_text(encoding="utf-8")
    missing = [flag for flag in schema.cli_flags() if f'"{flag}' not in cli]
    assert not missing, f"backend/cli.py does not declare: {missing}"
    print(f"cli flags ok: {len(schema.cli_flags())} flags")


def check_webui_derives() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import webui  # noqa: PLC0415 - the import must happen after sys.path is set

    assert schema.form_env_keys() == webui._ENV_KEYS, "webui._ENV_KEYS drifted from the schema"
    assert set(webui.SECRET_FIELDS) == set(schema.SECRET_FIELDS), "secret list drifted"
    assert webui._render_env_value("models", ["a/b", " "]) == "a/b"
    assert webui._render_env_value("think_chinese", True) == "1"
    assert webui._render_env_value("think_chinese", False) == "0"
    assert webui._render_env_value("round_size", 0) == "0"
    assert webui._render_env_value("flag_format", None) == ""
    print("webui mapping ok")


def check_render() -> None:
    assert schema.render_env_value(schema.BY_FIELD["think_chinese"], True) == "1"
    assert schema.render_env_value(schema.BY_FIELD["default_models"], ["x/y", " z/w "]) == "x/y,z/w"
    assert schema.render_env_value(schema.BY_FIELD["round_size"], 3) == "3"
    print("render ok")


def main() -> int:
    check_fields_exist()
    check_uniqueness()
    check_env_example()
    check_panel_controls()
    check_cli_flags()
    check_webui_derives()
    check_render()
    print("ALL SETTINGS-SCHEMA CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
