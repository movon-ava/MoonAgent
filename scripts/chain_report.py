"""Show what the chain library has accumulated, and how often it was used.

    uv run python scripts/chain_report.py            # human table
    uv run python scripts/chain_report.py --json     # machine-readable

Counts come from the traces we already write: every ``use_chain`` tool call is
matched back to the challenge it belonged to, and the run snapshots tell us
whether that challenge was solved.  That gives the three numbers that matter:

* how many chains / stages exist (the size of the library),
* how many times a chain was actually loaded (is it reachable/findable?),
* how often a challenge was solved after loading one (is it useful?).
"""

from __future__ import annotations

import json
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import chains  # noqa: E402

LOGS = ROOT / "logs"
RUNS = LOGS / "runs"
DIRECTIONS = ("web", "pwn", "misc", "re", "crypto")


def _tool_args(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def chain_hits() -> tuple[Counter, dict[str, set[str]]]:
    """Count ``use_chain`` calls per chain and per challenge."""
    counts: Counter = Counter()
    by_challenge: dict[str, set[str]] = defaultdict(set)
    for path in sorted(LOGS.glob("trace-*.jsonl")):
        challenge = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "start":
                challenge = str(event.get("challenge") or "")
            elif kind == "tool_call" and event.get("tool") == "use_chain":
                name = str(_tool_args(event.get("args")).get("name") or "").strip()
                if not name:
                    continue
                counts[name] += 1
                if challenge:
                    by_challenge[name].add(challenge)
    return counts, by_challenge


def solved_status() -> dict[str, str]:
    """challenge name -> best-known status across every run snapshot."""
    status: dict[str, str] = {}
    rank = {"solved": 3, "flag_found": 3, "running": 2, "failed": 1, "timeout": 1}
    for path in sorted(RUNS.glob("*/state.json")):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for name, item in (state.get("challenges") or {}).items():
            new = str((item or {}).get("status") or "")
            old = status.get(name, "")
            if rank.get(new, 0) >= rank.get(old, 0):
                status[name] = new or old
    return status


def _direction(chain: chains.Chain) -> str:
    for tag in chain.categories:
        low = tag.lower()
        for direction in DIRECTIONS:
            if low.startswith(direction) or direction.startswith(low):
                return direction
    return "other"


def build_report() -> dict:
    catalog = chains.catalog()
    hits, by_challenge = chain_hits()
    solved = solved_status()
    drafts_dir = chains.resolve_dir() / "_drafts"
    drafts = sorted(drafts_dir.glob("*.md")) if drafts_dir.is_dir() else []

    rows = []
    for chain in catalog:
        direction = _direction(chain)
        challenges = sorted(by_challenge.get(chain.name, set()))
        good = [name for name in challenges if solved.get(name) in ("solved", "flag_found")]
        rows.append(
            {
                "name": chain.name,
                "direction": direction,
                "stages": len(chain.stages),
                "stage_names": list(chain.stages),
                "hits": int(hits.get(chain.name, 0)),
                "challenges": challenges,
                "solved_after_load": len(good),
                "source": chain.source,
            }
        )

    per_direction: dict[str, dict[str, int]] = {}
    for direction in DIRECTIONS + ("other",):
        subset = [row for row in rows if row["direction"] == direction]
        per_direction[direction] = {
            "chains": len(subset),
            "stages": sum(row["stages"] for row in subset),
            "hits": sum(row["hits"] for row in subset),
            "solved_after_load": sum(row["solved_after_load"] for row in subset),
        }

    return {
        "library": str(chains.resolve_dir()),
        "chains": len(rows),
        "stages": sum(row["stages"] for row in rows),
        "hits": sum(row["hits"] for row in rows),
        "solved_after_load": sum(row["solved_after_load"] for row in rows),
        "per_direction": per_direction,
        "rows": rows,
        "drafts": [path.name for path in drafts],
        "empty_directions": [d for d in DIRECTIONS if per_direction[d]["chains"] == 0],
    }


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _cell(text: object, width: int, right: bool = False) -> str:
    body = str(text)
    fill = " " * max(0, width - _width(body))
    return fill + body if right else body + fill


def render(report: dict) -> str:
    out = [f"链库: {report['library']}", ""]
    out += [_cell("方向", 8) + _cell("链数", 6, True) + _cell("阶段", 6, True)
            + _cell("加载", 6, True) + _cell("加载后解出", 12, True), "-" * 38]
    for direction, stats in report["per_direction"].items():
        if direction == "other" and stats["chains"] == 0:
            continue
        out.append(
            _cell(direction, 8)
            + _cell(stats["chains"], 6, True)
            + _cell(stats["stages"], 6, True)
            + _cell(stats["hits"], 6, True)
            + _cell(stats["solved_after_load"], 12, True)
        )
    out.append("-" * 38)
    out.append(
        _cell("合计", 8)
        + _cell(report["chains"], 6, True)
        + _cell(report["stages"], 6, True)
        + _cell(report["hits"], 6, True)
        + _cell(report["solved_after_load"], 12, True)
    )
    out.append("")
    out.append("链清单:")
    for row in report["rows"]:
        stages = " → ".join(row["stage_names"]) if row["stage_names"] else "(无阶段)"
        out.append(f"  {row['name']:<28}{row['stages']} 阶段  {stages}")
        extra = f"      加载 {row['hits']} 次"
        if row["challenges"]:
            extra += f"（{'、'.join(row['challenges'])}）"
        if row["solved_after_load"]:
            extra += f"，其中 {row['solved_after_load']} 道解出"
        out.append(extra)
    if report["drafts"]:
        out += ["", f"待整理草稿 {len(report['drafts'])} 条（chains/_drafts/）: " + "、".join(report["drafts"])]
    if report["empty_directions"]:
        out += [
            "",
            "还没积累的方向: " + "、".join(report["empty_directions"]),
            "  → 用 scripts/harvest_chain.py 从这些方向的难题 trace 里拉一份草稿，补完判据后移出 _drafts/。",
        ]
    return "\n".join(out)


def main() -> int:
    report = build_report()
    if "--json" in sys.argv:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
