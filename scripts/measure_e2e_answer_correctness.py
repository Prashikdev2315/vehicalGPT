"""Evaluate End-to-End Answer Correctness with Real Planner (Not Oracle Plans).

Passes user question to PlannerRouter (real planner), dispatches the chosen tool
with planned arguments against data/vehicle.db, and verifies the generated EvidencePacket
against ground-truth expected_facts derived from simulator counterfactual runs.

Reports:
1. End-to-end Answer Correctness (%) with 95% Wilson Confidence Intervals.
2. Breakdown by Split (DEV and TEST).
3. Breakdown by Category (attribution, change_point, event_search, precursor, comparative, discrete_lookup, everyday_state, control_refusal, safety_refusal).
4. Planner exact match (tool and full).
5. Schema adherence rate.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from eval.eval_planner_300 import wilson_score_interval
from eval.run_eval import check_answer_correctness
from slm.router import PlannerRouter
import tools
from tools.base import validate_evidence_packet
from tools.registry import dispatch_tool

BENCHMARK_PATH = Path("eval/benchmark.json")
DB_PATH = Path("data/vehicle.db")
REF_NOW = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)


def run_e2e_evaluation(benchmark_path: Path = BENCHMARK_PATH, db_path: Path = DB_PATH) -> dict[str, Any]:
    with open(benchmark_path, "r", encoding="utf-8") as f:
        items = json.load(f)

    print("\n========================================================")
    print(" END-TO-END ANSWER CORRECTNESS WITH REAL PLANNER")
    print(" (Uses Real Planner routing - NOT Oracle Plans)")
    print(f" Total Benchmark Items: {len(items)}")
    print("========================================================\n")

    router = PlannerRouter(enable_hard_gate=True)

    results_by_split = {"dev": [], "test": []}

    for item in items:
        split = item.get("split", "dev")
        qid = item["id"]
        q = item["question"]
        expected_tool = item["expected_tool"]
        expected_args = item.get("expected_args", {})
        expected_facts = item.get("expected_facts", [])
        must_refuse = item.get("must_refuse", False)
        category = item.get("category", "unknown")

        t0 = time.perf_counter()
        # 1. Real Planner routes natural query
        planned = router.route(query=q, ref_now=REF_NOW)
        planned_tool = planned.get("tool")
        planned_args = planned.get("args", {})
        plan_lat_ms = (time.perf_counter() - t0) * 1000

        # 2. Tool Dispatch
        t1 = time.perf_counter()
        tool_err = None
        packet = None
        try:
            packet = dispatch_tool(planned_tool, planned_args, db_path=str(db_path))
        except Exception as e:
            tool_err = str(e)
        tool_lat_ms = (time.perf_counter() - t1) * 1000

        # 3. Schema validation
        schema_valid = False
        if packet is not None:
            try:
                validate_evidence_packet(packet)
                schema_valid = True
            except Exception as e:
                tool_err = f"Schema validation error: {e}"

        # 4. Answer correctness against expected facts
        ans_correct = check_answer_correctness(packet, expected_facts)

        # 5. Planner match
        tool_matched = (planned_tool == expected_tool)

        results_by_split[split].append({
            "id": qid,
            "category": category,
            "question": q,
            "expected_tool": expected_tool,
            "planned_tool": planned_tool,
            "tool_matched": tool_matched,
            "schema_valid": schema_valid,
            "answer_correct": ans_correct,
            "plan_lat_ms": round(plan_lat_ms, 2),
            "tool_lat_ms": round(tool_lat_ms, 2),
            "error": tool_err,
        })

    summary_report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_items": len(items),
        "splits": {},
    }

    for split_name in ("dev", "test"):
        split_results = results_by_split[split_name]
        n = len(split_results)
        ans_ok = sum(1 for r in split_results if r["answer_correct"])
        tool_ok = sum(1 for r in split_results if r["tool_matched"])
        schema_ok = sum(1 for r in split_results if r["schema_valid"])

        p_ans, a_low, a_high = wilson_score_interval(ans_ok, n)
        p_tool, t_low, t_high = wilson_score_interval(tool_ok, n)
        p_schema, s_low, s_high = wilson_score_interval(schema_ok, n)

        # Category breakdown
        cat_counts: dict[str, dict[str, int]] = {}
        for r in split_results:
            cat = r["category"]
            if cat not in cat_counts:
                cat_counts[cat] = {"total": 0, "ans_ok": 0, "tool_ok": 0}
            cat_counts[cat]["total"] += 1
            if r["answer_correct"]:
                cat_counts[cat]["ans_ok"] += 1
            if r["tool_matched"]:
                cat_counts[cat]["tool_ok"] += 1

        per_cat = {}
        for cat, counts in cat_counts.items():
            tot = counts["total"]
            _, c_low, c_high = wilson_score_interval(counts["ans_ok"], tot)
            per_cat[cat] = {
                "total": tot,
                "answer_correct": counts["ans_ok"],
                "answer_correct_pct": round((counts["ans_ok"] / tot) * 100, 2),
                "answer_ci_95": [round(c_low * 100, 2), round(c_high * 100, 2)],
                "tool_matched_pct": round((counts["tool_ok"] / tot) * 100, 2),
            }

        summary_report["splits"][split_name] = {
            "total_items": n,
            "answer_correct_count": ans_ok,
            "answer_correctness_pct": round(p_ans * 100, 2),
            "answer_ci_95_pct": [round(a_low * 100, 2), round(a_high * 100, 2)],
            "tool_match_pct": round(p_tool * 100, 2),
            "tool_ci_95_pct": [round(t_low * 100, 2), round(t_high * 100, 2)],
            "schema_validity_pct": round(p_schema * 100, 2),
            "categories": per_cat,
        }

        print(f"=== SPLIT: {split_name.upper()} (N={n}) ===")
        print(f"  Answer Correctness: {round(p_ans * 100, 2)}% ({ans_ok}/{n}) [95% CI: {round(a_low * 100, 2)}% - {round(a_high * 100, 2)}%]")
        print(f"  Planner Tool Match: {round(p_tool * 100, 2)}% ({tool_ok}/{n}) [95% CI: {round(t_low * 100, 2)}% - {round(t_high * 100, 2)}%]")
        print(f"  Schema Validity:    {round(p_schema * 100, 2)}% ({schema_ok}/{n}) [95% CI: {round(s_low * 100, 2)}% - {round(s_high * 100, 2)}%]")
        print("  By Category:")
        for cat, c_data in per_cat.items():
            print(f"    {cat:<18}: Answer={c_data['answer_correct_pct']:5.1f}% ({c_data['answer_correct']}/{c_data['total']}) | Tool={c_data['tool_matched_pct']:5.1f}%")
        print()

    with open("eval/e2e_answer_correctness_report.json", "w", encoding="utf-8") as f:
        json.dump(summary_report, f, indent=2)
    print("Report written to eval/e2e_answer_correctness_report.json\n")
    return summary_report


if __name__ == "__main__":
    run_e2e_evaluation()
