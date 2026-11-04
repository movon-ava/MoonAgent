"""Sanity check: random picking should mix every difficulty tier evenly."""

import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.round_runner import _pick

pool = (
    [{"name": f"easy{i}", "value": 1, "difficulty": "简单"} for i in range(40)]
    + [{"name": f"med{i}", "value": 1, "difficulty": "中等"} for i in range(20)]
    + [{"name": f"hard{i}", "value": 1, "difficulty": "困难"} for i in range(10)]
    + [{"name": f"intro{i}", "value": 1, "difficulty": "入门"} for i in range(10)]
)

seen = Counter()
for _ in range(400):
    for ch in _pick(pool, 8):
        seen[ch["difficulty"]] += 1
print("random picks:", dict(seen))

# Every tier must show up, and the huge 简单 bucket must not dominate.
for tier in ("入门", "简单", "中等", "困难"):
    assert seen[tier] > 0, seen
total = sum(seen.values())
assert seen["简单"] / total < 0.45, seen

seen2 = Counter()
for _ in range(50):
    for ch in _pick(pool, 6, order="hard"):
        seen2[ch["difficulty"]] += 1
print("hard picks  :", dict(seen2))
# order="hard" still covers every tier (one-per-tier seeding) but fills the
# rest with the hardest remaining challenges.
assert seen2["困难"] >= seen2["中等"], seen2
assert seen2["困难"] >= seen2["简单"], seen2
assert seen2["简单"] > 0, seen2
print("PICK WEIGHTING OK")
