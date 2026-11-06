"""Extract the dashboard's inline <script> and syntax-check it with node.

The HTML lives in ``scripts/webui_assets.py``; earlier hand edits once ate a
``${...}`` template literal, which killed the whole script. This catches that
class of bug before the page is reloaded.

Run with:  uv run python scripts/test_webui_js.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def script_blocks(html: str) -> list[str]:
    return re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("node not found - skipping JS syntax check")
        return 0

    sys.path.insert(0, str(ROOT / "scripts"))
    import webui_assets  # noqa: PLC0415

    blocks = script_blocks(webui_assets.HTML)
    assert blocks, "the dashboard HTML has no <script> block"

    with tempfile.TemporaryDirectory() as tmp:
        for index, body in enumerate(blocks):
            path = Path(tmp) / f"block{index}.js"
            path.write_text(body, encoding="utf-8")
            proc = subprocess.run(
                [node, "--check", str(path)], capture_output=True, text=True, check=False
            )
            if proc.returncode != 0:
                print(proc.stdout)
                print(proc.stderr)
                raise SystemExit(f"script block {index} has a syntax error")
    print(f"JS syntax ok: {len(blocks)} block(s), {sum(len(b) for b in blocks)} chars")
    print("ALL WEBUI-JS CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
