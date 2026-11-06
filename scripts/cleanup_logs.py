"""Delete old trace files and run snapshots.

    uv run python scripts/cleanup_logs.py             # default: 14 days / keep 200
    uv run python scripts/cleanup_logs.py --dry-run   # show what would go
    uv run python scripts/cleanup_logs.py --days 3 --keep-traces 50
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.maintenance import prune_logs


def main() -> None:
    parser = argparse.ArgumentParser(description="Prune ctf-agent logs")
    parser.add_argument("--days", type=float, default=14.0, help="keep traces newer than this")
    parser.add_argument("--keep-traces", type=int, default=200, help="always keep the newest N")
    parser.add_argument("--keep-run-days", type=float, default=30.0, help="keep run snapshots this long")
    parser.add_argument("--dry-run", action="store_true", help="report only, delete nothing")
    args = parser.parse_args()

    removed = prune_logs(
        days=args.days,
        keep_traces=args.keep_traces,
        keep_run_days=args.keep_run_days,
        dry_run=args.dry_run,
    )
    verb = "would remove" if args.dry_run else "removed"
    print(
        f"{verb} {removed['traces']} trace(s), {removed['runs']} run dir(s), "
        f"{removed['bytes'] / 1_048_576:.1f} MB"
    )


if __name__ == "__main__":
    main()
