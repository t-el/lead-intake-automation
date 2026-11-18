"""Command line: process a batch of leads, list or replay the dead-letter queue.

    python -m lead_intake.cli process samples/leads.json
    python -m lead_intake.cli dlq
    python -m lead_intake.cli replay 3
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .config import get_settings
from .logging_setup import setup_logging
from .pipeline import Pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lead-intake")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_proc = sub.add_parser("process", help="process leads from a JSON file (list of objects)")
    p_proc.add_argument("file", type=Path)
    sub.add_parser("dlq", help="list unresolved dead letters")
    p_rep = sub.add_parser("replay", help="replay a dead letter by id")
    p_rep.add_argument("id", type=int)
    args = parser.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_json)
    pipeline = Pipeline(settings)

    if args.cmd == "process":
        leads = json.loads(args.file.read_text())
        results = [pipeline.process(item) for item in leads]
        counts = Counter(r.status for r in results)
        print("\n=== Summary ===")
        for r in results:
            extra = f"score={r.score} tier={r.tier}" if r.status == "processed" else (r.error or "")
            print(f"  {r.status:<14} {r.email or '-':<32} {extra}")
        print("  " + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
        return 0
    if args.cmd == "dlq":
        for d in pipeline.store.dead_letters():
            print(f"#{d['id']:<4} {d['step']:<9} {d['email'] or '-':<30} {d['error']}")
        return 0
    if args.cmd == "replay":
        r = pipeline.replay(args.id)
        print(json.dumps(r.__dict__, indent=2, default=str))
        return 0 if r.status in {"processed", "duplicate"} else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
