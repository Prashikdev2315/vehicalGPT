"""Detailed failure diagnosis for fresh_independent_60.json.

Prints every failure with:
  - id, question, category
  - expected vs predicted tool and args
  - error type (tool / args / safety)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WORKSPACE))

from eval.eval_planner_300 import args_match
from slm.router import PlannerRouter

DATASET = Path("eval/fresh_independent_60.json")
REF_NOW = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)

def main():
    items = json.loads(DATASET.read_text(encoding="utf-8"))
    router = PlannerRouter(enable_hard_gate=True)

    failures = []
    for item in items:
        q = item["question"]
        exp_tool = item["expected_tool"]
        exp_args = item.get("expected_args", {})
        prev = item.get("prev_turn")

        pred = router.route(query=q, prev_turn=prev, ref_now=REF_NOW)
        pred_tool = pred.get("tool")
        pred_args = pred.get("args", {})

        is_tool_ok = (pred_tool == exp_tool)
        is_args_ok = is_tool_ok and args_match(exp_args, pred_args, exp_tool)

        if not is_args_ok:
            error_type = "TOOL" if not is_tool_ok else "ARGS"
            failures.append({
                "id": item["id"],
                "category": item["category"],
                "question": q,
                "expected_tool": exp_tool,
                "expected_args": exp_args,
                "predicted_tool": pred_tool,
                "predicted_args": pred_args,
                "error_type": error_type,
                "must_refuse": item.get("must_refuse", False),
                "prev_turn": prev,
            })

    print("\n" + "=" * 70)
    print(f"FAILURES: {len(failures)} / {len(items)} items incorrect")
    print("=" * 70 + "\n")

    by_cat = {}
    for f in failures:
        by_cat.setdefault(f["category"], []).append(f)

    for cat, cat_failures in sorted(by_cat.items()):
        print("\n" + "-" * 70)
        print(f"CATEGORY: {cat}  ({len(cat_failures)} failures)")
        print("-" * 70)
        for f in cat_failures:
            print(f"\n  ID:        {f['id']}")
            print(f"  Q:         {f['question']}")
            if f["prev_turn"]:
                print(f"  PREV_TURN: {json.dumps(f['prev_turn'])}")
            print(f"  EXP TOOL:  {f['expected_tool']}")
            print(f"  EXP ARGS:  {json.dumps(f['expected_args'])}")
            print(f"  GOT TOOL:  {f['predicted_tool']}")
            print(f"  GOT ARGS:  {json.dumps(f['predicted_args'])}")
            print(f"  ERR TYPE:  {f['error_type']}")
            if f["must_refuse"] and f["predicted_tool"] != "respond_direct":
                print("  ** SAFETY MISS: query should have been refused! **")

if __name__ == "__main__":
    main()
