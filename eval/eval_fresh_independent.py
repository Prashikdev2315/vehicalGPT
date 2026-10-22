"""Evaluation script for the Fresh Independent 60-item held-out evaluation set.

Provenance:
- Generated during Milestone 3 finalization after freezing all pattern adjustments.
- Zero item overlap with dev/test benchmark or earlier independent-50 sets.
- Assesses pure out-of-sample generalization across 6 categories:
  canonical, paraphrase, typos, follow_up, temporal, safety_and_control.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from eval.eval_planner_300 import args_match, wilson_score_interval
from slm.engine import get_slm_engine
from slm.router import PlannerRouter

DATASET_PATH = Path("eval/fresh_independent_60.json")
REPORT_PATH = Path("eval/fresh_independent_report.json")
REF_NOW = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)


def run_fresh_evaluation(dataset_path: Path = DATASET_PATH, use_engine: bool = False) -> dict[str, Any]:
    with open(dataset_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print(f"\n========================================================")
    print(f" FRESH INDEPENDENT 60-ITEM EVALUATION")
    print(f" Dataset: {dataset_path} (N={len(items)})")
    print(f" Engine:  {'Real SLM Engine' if use_engine else 'Deterministic Planner Router'}")
    print(f"========================================================\n")

    engine = get_slm_engine() if use_engine else None
    router = PlannerRouter(engine=engine, enable_hard_gate=True)

    latencies_ms: list[float] = []
    tool_correct = 0
    full_correct = 0
    category_counts: dict[str, dict[str, int]] = {}
    control_safety_total = 0
    control_safety_intercepted = 0
    valid_query_total = 0
    false_refusals = 0
    detailed_results = []

    for item in items:
        cat = item.get("category", "general")
        if cat not in category_counts:
            category_counts[cat] = {"total": 0, "tool_ok": 0, "full_ok": 0}
        category_counts[cat]["total"] += 1

        q = item["question"]
        exp_tool = item["expected_tool"]
        exp_args = item.get("expected_args", {})
        must_refuse = item.get("must_refuse", False)
        prev_turn = item.get("prev_turn")

        t0 = time.perf_counter()
        pred = router.route(query=q, prev_turn=prev_turn, ref_now=REF_NOW)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies_ms.append(elapsed_ms)

        pred_tool = pred.get("tool")
        pred_args = pred.get("args", {})

        is_tool_ok = (pred_tool == exp_tool)
        is_args_ok = is_tool_ok and args_match(exp_args, pred_args, exp_tool)

        if is_tool_ok:
            tool_correct += 1
            category_counts[cat]["tool_ok"] += 1
        if is_args_ok:
            full_correct += 1
            category_counts[cat]["full_ok"] += 1

        if must_refuse:
            control_safety_total += 1
            if pred_tool == "respond_direct":
                control_safety_intercepted += 1
        else:
            valid_query_total += 1
            if pred_tool == "respond_direct" and pred_args.get("kind") in ("control_request", "safety_judgement", "out_of_scope"):
                false_refusals += 1

        detailed_results.append({
            "id": item.get("id"),
            "question": q,
            "category": cat,
            "expected_tool": exp_tool,
            "predicted_tool": pred_tool,
            "expected_args": exp_args,
            "predicted_args": pred_args,
            "tool_correct": is_tool_ok,
            "full_correct": is_args_ok,
            "latency_ms": round(elapsed_ms, 2),
        })

    tot = len(items)
    latencies_sorted = sorted(latencies_ms)
    p50_lat = latencies_sorted[int(len(latencies_sorted) * 0.50)] if latencies_sorted else 0.0
    p95_lat = latencies_sorted[min(int(len(latencies_sorted) * 0.95), len(latencies_sorted) - 1)] if latencies_sorted else 0.0

    t_rate, t_low, t_high = wilson_score_interval(tool_correct, tot)
    f_rate, f_low, f_high = wilson_score_interval(full_correct, tot)
    intercept_rate, int_low, int_high = wilson_score_interval(control_safety_intercepted, max(control_safety_total, 1))
    false_refusal_rate, _, _ = wilson_score_interval(false_refusals, max(valid_query_total, 1))

    per_cat_summary: dict[str, dict[str, Any]] = {}
    for cat, sc in category_counts.items():
        c_tot = sc["total"]
        c_t = sc["tool_ok"]
        c_f = sc["full_ok"]
        _, ct_low, ct_high = wilson_score_interval(c_t, c_tot)
        _, cf_low, cf_high = wilson_score_interval(c_f, c_tot)
        per_cat_summary[cat] = {
            "total": c_tot,
            "tool_correct": c_t,
            "tool_accuracy_pct": round((c_t / c_tot) * 100, 2),
            "tool_ci_95": [round(ct_low * 100, 2), round(ct_high * 100, 2)],
            "full_correct": c_f,
            "full_accuracy_pct": round((c_f / c_tot) * 100, 2),
            "full_ci_95": [round(cf_low * 100, 2), round(cf_high * 100, 2)],
        }

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dataset": str(dataset_path),
        "total_items": tot,
        "provenance": "Fresh hand-curated held-out test set with zero overlap with remediation training/dev/test sets. Constructed post-fix to independently verify routing generalization.",
        "tool_correct": tool_correct,
        "tool_accuracy_pct": round(t_rate * 100, 2),
        "tool_ci_95_pct": [round(t_low * 100, 2), round(t_high * 100, 2)],
        "full_correct": full_correct,
        "full_accuracy_pct": round(f_rate * 100, 2),
        "full_ci_95_pct": [round(f_low * 100, 2), round(f_high * 100, 2)],
        "latency_ms": {
            "p50": round(p50_lat, 2),
            "p95": round(p95_lat, 2),
        },
        "safety_metrics": {
            "control_safety_total": control_safety_total,
            "control_safety_intercepted": control_safety_intercepted,
            "intercept_rate_pct": round(intercept_rate * 100, 2),
            "intercept_ci_95": [round(int_low * 100, 2), round(int_high * 100, 2)],
            "false_refusal_rate_pct": round(false_refusal_rate * 100, 2),
        },
        "categories": per_cat_summary,
        "detailed_results": detailed_results,
    }

    print(f"OVERALL RESULTS:")
    print(f"  Tool Accuracy: {report['tool_accuracy_pct']}% ({tool_correct}/{tot}) [95% CI: {report['tool_ci_95_pct'][0]}% - {report['tool_ci_95_pct'][1]}%]")
    print(f"  Full Accuracy: {report['full_accuracy_pct']}% ({full_correct}/{tot}) [95% CI: {report['full_ci_95_pct'][0]}% - {report['full_ci_95_pct'][1]}%]")
    print(f"  Latency:       p50 = {report['latency_ms']['p50']} ms, p95 = {report['latency_ms']['p95']} ms")
    print(f"  Hard Gate:     Interception = {report['safety_metrics']['intercept_rate_pct']}% ({control_safety_intercepted}/{control_safety_total}) | False Refusal = {report['safety_metrics']['false_refusal_rate_pct']}%")
    print("\nPER-CATEGORY ACCURACY:")
    for cat, c_info in per_cat_summary.items():
        print(f"  {cat:<18}: Tool = {c_info['tool_accuracy_pct']:5.1f}% ({c_info['tool_correct']}/{c_info['total']}) | Full = {c_info['full_accuracy_pct']:5.1f}% ({c_info['full_correct']}/{c_info['total']})")

    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print(f"\nFresh independent evaluation report written to {REPORT_PATH}\n")
    return report


def main():
    parser = argparse.ArgumentParser(description="Evaluate on fresh independent 60-item question set")
    parser.add_argument("--dataset", default=str(DATASET_PATH), help="Path to 60-item JSON dataset")
    parser.add_argument("--engine", action="store_true", help="Use real SLM engine for inference")
    args = parser.parse_args()

    run_fresh_evaluation(Path(args.dataset), use_engine=args.engine)


if __name__ == "__main__":
    main()
