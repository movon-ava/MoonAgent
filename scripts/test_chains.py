"""Self-check for the chain library (chains/*.md) and its wiring."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import chains  # noqa: E402

EXPECTED = {"re/upx-garble-go", "pwn/ret2text-rop", "misc/encoding-layers"}


def check_library() -> None:
    catalog = chains.catalog()
    assert len(catalog) >= 3, f"expected >=3 chains, got {len(catalog)}"
    names = {chain.name for chain in catalog}
    missing = EXPECTED - names
    assert not missing, f"missing chains: {missing}"
    assert len(names) == len(catalog), "duplicate chain names"
    for chain in catalog:
        assert chain.description, f"{chain.name} has no description"
        assert chain.when_to_use, f"{chain.name} has no when_to_use"
        assert len(chain.stages) >= 3, f"{chain.name} has only {len(chain.stages)} stages"
        assert "判据" in chain.body, f"{chain.name} never states 判据"
        assert "失败分支" in chain.body, f"{chain.name} never states 失败分支"
        for index in range(1, len(chain.stages) + 1):
            assert f"## {index}." in chain.body, f"{chain.name} misses section {index}"
    print(f"library ok: {len(catalog)} chains, {sum(len(c.stages) for c in catalog)} stages")


def check_index_and_match() -> None:
    text = chains.index_text("re", limit=1200)
    assert text, "index is empty"
    assert "→" in text, "index does not show the stage skeleton"
    assert len(text) <= 1200, "index exceeds the prompt budget"
    hits = chains.match("REVRESE", "cefsimple.exe 附件 upx garble go", limit=2)
    assert hits, "match() found nothing for a RE/UPX challenge"
    assert hits[0].name == "re/upx-garble-go", f"expected the UPX chain first, got {hits[0].name}"
    assert not chains.match("crypto", "totally unrelated words", limit=2), "unrelated text matched"
    print("index/match ok")


def check_body_and_tool() -> None:
    text = chains.body("pwn/ret2text-rop")
    assert text and "阶段：" in text and "checksec" in text
    assert chains.body("does/not-exist") is None

    from backend.tools.chain_tool import use_chain

    class FakeCtx:
        class deps:  # noqa: N801 - tiny stub
            class settings:  # noqa: N801
                chains_dir = "chains"

    loaded = asyncio.run(use_chain(FakeCtx(), "misc/encoding-layers"))
    assert "逐层解码" in loaded
    unknown = asyncio.run(use_chain(FakeCtx(), "nope"))
    assert unknown.startswith("Unknown chain"), unknown
    print("body/tool ok")


def check_drafts_are_hidden() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "re").mkdir()
        (root / "re" / "real.md").write_text(
            "---\nname: re/real\ndescription: d\nwhen_to_use: w\ncategories: [re]\nstages: [a, b, c]\n---\n## 1. a\n判据：x\n",
            encoding="utf-8",
        )
        (root / "_drafts").mkdir()
        (root / "_drafts" / "draft.md").write_text(
            "---\nname: draft/x\ndescription: d\nwhen_to_use: w\ncategories: [re]\nstages: [a]\n---\nbody\n",
            encoding="utf-8",
        )
        found = chains.catalog(root)
        assert [chain.name for chain in found] == ["re/real"], [c.name for c in found]
    print("drafts hidden ok")


def check_report() -> None:
    from scripts import chain_report

    report = chain_report.build_report()
    assert report["chains"] >= 3, report
    assert report["stages"] >= 9, report
    assert "re" in report["per_direction"]
    assert report["per_direction"]["re"]["chains"] >= 1
    print(f"report ok: {report['chains']} chains / {report['stages']} stages / hits {report['hits']}")


def check_harvester() -> None:
    from scripts import harvest_chain

    with tempfile.TemporaryDirectory() as tmp:
        trace = Path(tmp) / "trace-Demo-deepseek-flash-1.jsonl"
        events = [
            {"type": "start", "challenge": "Demo", "category": "REVRESE"},
            {"type": "tool_call", "tool": "bash", "args": json.dumps({"command": "ls -la /challenge/distfiles"})},
            {"type": "tool_call", "tool": "bash", "args": json.dumps({"command": "strings -n 8 ./chal"})},
            {"type": "tool_call", "tool": "bash", "args": json.dumps({"command": "objdump -d ./chal | head"})},
            {"type": "tool_call", "tool": "bash", "args": json.dumps({"command": "python3 solve.py"})},
            {"type": "tool_call", "tool": "submit_flag", "args": json.dumps({"flag": "DASCTF{x}", "evidence": "y"})},
        ]
        trace.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in events), encoding="utf-8")
        meta, calls = harvest_chain.parse_trace(trace)
        assert meta["challenge"] == "Demo" and len(calls) == 5
        stages = harvest_chain.build_stages(calls)
        titles = [stage.title for stage in stages]
        assert titles[0] == "侦察", titles
        assert "静态分析" in titles and "验证与提交" in titles, titles
        text = harvest_chain.render(meta, trace.name, stages)
        assert "stages: [1. 侦察" in text and "判据：TODO" in text
    print("harvester ok")


def check_wiring() -> None:
    solver = (ROOT / "backend" / "agents" / "solver.py").read_text(encoding="utf-8")
    prompts = (ROOT / "backend" / "prompts.py").read_text(encoding="utf-8")
    schema = (ROOT / "backend" / "settings_schema.py").read_text(encoding="utf-8")
    assets = (ROOT / "scripts" / "webui_assets.py").read_text(encoding="utf-8")
    webui = (ROOT / "scripts" / "webui.py").read_text(encoding="utf-8")
    assert "tools.append(use_chain)" in solver
    assert "chains_index=chains.index_text" in solver
    assert "chains_reco=chains_reco" in solver
    assert "use_chain(\\\"<上面的名字>\\\")" in prompts or "use_chain(" in prompts
    assert "这个方向已有的解题链" in prompts
    assert 'Setting("chains_enabled", "CHAINS_ENABLED"' in schema
    assert 'id="chains_enabled"' in assets
    assert 'argv.append("--no-chains")' in webui
    print("wiring ok")


def main() -> int:
    check_library()
    check_index_and_match()
    check_body_and_tool()
    check_drafts_are_hidden()
    check_report()
    check_harvester()
    check_wiring()
    print("ALL CHAIN CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
