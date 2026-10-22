"""Diagnose TEST split failures to understand what's fixable without data leakage."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from slm.router import PlannerRouter

with open("eval/planner_benchmark_300.json", "r", encoding="utf-8") as f:
    items = json.load(f)

test_items = [i for i in items if i["split"] == "test"]
ref_now = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)

router = PlannerRouter(engine=None, enable_hard_gate=True)

failures = []
for item in test_items:
    pred = router.route(query=item["question"], prev_turn=item.get("prev_turn"), ref_now=ref_now)
    pred_tool = pred.get("tool")
    pred_args = pred.get("args", {})
    exp_tool = item["expected_tool"]
    exp_args = item.get("expected_args", {})
    tool_ok = pred_tool == exp_tool
    if not tool_ok:
        failures.append(
            {
                "id": item.get("id", ""),
                "cat": item["category"],
                "fail_type": "WRONG_TOOL",
                "q": item["question"],
                "exp_tool": exp_tool,
                "pred_tool": pred_tool,
                "exp_args": exp_args,
                "pred_args": pred_args,
            }
        )
        continue

    # Check args match
    args_ok = True
    if pred_tool == "respond_direct":
        args_ok = pred_args.get("kind") == exp_args.get("kind")
    elif pred_tool == "current_state":
        args_ok = pred_args.get("signal") == exp_args.get("signal")
    elif pred_tool == "lookup_dtc":
        args_ok = str(pred_args.get("code", "")).upper() == str(exp_args.get("code", "")).upper()
    elif pred_tool == "compare":
        args_ok = (
            pred_args.get("metric") == exp_args.get("metric")
            and pred_args.get("segment_a") == exp_args.get("segment_a")
            and pred_args.get("segment_b") == exp_args.get("segment_b")
        )
    elif pred_tool == "trend":
        args_ok = pred_args.get("metric") == exp_args.get("metric")
    elif pred_tool in ("largest_change", "explain_change"):
        args_ok = pred_args.get("metric") == exp_args.get("metric")
    elif pred_tool == "timeline_before":
        if "event_id" in exp_args:
            args_ok = pred_args.get("event_id") == exp_args.get("event_id")
        else:
            args_ok = pred_args.get("event_type") == exp_args.get("event_type")
    elif pred_tool == "get_events":
        exp_t = exp_args.get("type")
        pred_t = pred_args.get("type")
        if exp_t and pred_t and exp_t != "any":
            args_ok = pred_t == exp_t
    elif pred_tool == "search_logs":
        args_ok = bool(pred_args.get("query"))

    if not args_ok:
        failures.append(
            {
                "id": item.get("id", ""),
                "cat": item["category"],
                "fail_type": "WRONG_ARGS",
                "q": item["question"],
                "exp_tool": exp_tool,
                "pred_tool": pred_tool,
                "exp_args": exp_args,
                "pred_args": pred_args,
            }
        )

print(f"Total TEST failures: {len(failures)} / {len(test_items)}")
print(f"Full accuracy: {(len(test_items)-len(failures))}/{len(test_items)} = {(len(test_items)-len(failures))/len(test_items)*100:.2f}%")
print()

by_type: dict[str, list] = {}
for f in failures:
    by_type.setdefault(f["fail_type"], []).append(f)
    by_type.setdefault(f["cat"], []).append(f)

print("By fail type:")
for t in ["WRONG_TOOL", "WRONG_ARGS"]:
    print(f"  {t}: {len(by_type.get(t, []))}")
print()
print("By category:")
for cat in ["canonical", "paraphrase", "typos", "follow_up", "temporal", "safety_and_control"]:
    cat_fails = [f for f in failures if f["cat"] == cat]
    print(f"  {cat}: {len(cat_fails)}")
print()

print("=== WRONG TOOL failures ===")
for f in by_type.get("WRONG_TOOL", []):
    print(f"[{f['cat']}] {f['id']}")
    print(f"  Q: {f['q']}")
    print(f"  Expected: {f['exp_tool']} {f['exp_args']}")
    print(f"  Got:      {f['pred_tool']} {f['pred_args']}")
    print()

print("=== WRONG ARGS failures ===")
for f in by_type.get("WRONG_ARGS", []):
    print(f"[{f['cat']}] {f['id']}")
    print(f"  Q: {f['q']}")
    print(f"  Expected: {f['exp_tool']} {f['exp_args']}")
    print(f"  Got:      {f['pred_tool']} {f['pred_args']}")
    print()
