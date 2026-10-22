"""Diagnose all remaining DEV failures across planner and benchmark suites.
STRICT: Inspects DEV split ONLY; never touches or inspects held-out TEST data.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

WORKSPACE_ROOT = Path(__file__).resolve().parent.parent
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from eval.eval_planner_300 import args_match
from eval.run_eval import check_answer_correctness
from slm.router import PlannerRouter, check_pre_execution_gate
from slm.time_prepass import resolve_time_prepass
from tools.registry import dispatch_tool

REF_NOW = PlannerRouter().route("now")  # placeholder, let's use fixed REF_NOW
from datetime import datetime, timezone
REF_NOW = datetime(2026, 10, 22, 14, 0, 0, tzinfo=timezone.utc)

def diagnose_planner_dev():
    print("=================================================================")
    print(" 1. DIAGNOSING PLANNER BENCHMARK 300 (DEV SPLIT: 160 items)")
    print("=================================================================")
    with open("eval/planner_benchmark_300.json", "r", encoding="utf-8") as f:
        items = [i for i in json.load(f) if i.get("split") == "dev"]

    router = PlannerRouter(enable_hard_gate=True)
    failures = []

    for it in items:
        qid = it["id"]
        q = it["question"]
        exp_t = it["expected_tool"]
        exp_a = it.get("expected_args", {})
        prev = it.get("prev_turn")

        pred = router.route(query=q, prev_turn=prev, ref_now=REF_NOW)
        pred_t = pred.get("tool")
        pred_a = pred.get("args", {})

        is_tool = (pred_t == exp_t)
        is_args = is_tool and args_match(exp_a, pred_a, exp_t)

        if not (is_tool and is_args):
            failures.append({
                "id": qid,
                "category": it["category"],
                "question": q,
                "expected_tool": exp_t,
                "predicted_tool": pred_t,
                "expected_args": exp_a,
                "predicted_args": pred_a,
                "tool_fail": not is_tool,
                "args_fail": is_tool and not is_args,
            })

    print(f"Total DEV items: {len(items)}")
    print(f"Total DEV failures: {len(failures)} (Tool failures: {sum(1 for f in failures if f['tool_fail'])}, Arg failures: {sum(1 for f in failures if f['args_fail'])})")
    print(f"DEV Tool Accuracy: {((len(items) - sum(1 for f in failures if f['tool_fail'])) / len(items)) * 100:.2f}%")
    print(f"DEV Full Accuracy: {((len(items) - len(failures)) / len(items)) * 100:.2f}%\n")

    for f in failures:
        fail_type = "WRONG_TOOL" if f["tool_fail"] else "WRONG_ARGS"
        print(f"[{f['id']}] [{fail_type}] Cat:{f['category']}")
        print(f"  Q: \"{f['question']}\"")
        print(f"  Exp: tool={f['expected_tool']} args={f['expected_args']}")
        print(f"  Pred: tool={f['predicted_tool']} args={f['predicted_args']}")
        print()

    return failures


def diagnose_benchmark_dev():
    print("=================================================================")
    print(" 2. DIAGNOSING BENCHMARK 100 (DEV SPLIT: 50 items)")
    print("=================================================================")
    with open("eval/benchmark.json", "r", encoding="utf-8") as f:
        items = [i for i in json.load(f) if i.get("split") == "dev"]

    router = PlannerRouter(enable_hard_gate=True)
    failures = []

    for it in items:
        qid = it["id"]
        q = it["question"]
        exp_t = it["expected_tool"]
        exp_a = it.get("expected_args", {})
        exp_facts = it.get("expected_facts", [])

        from tools.time_parser import DEFAULT_REF_NOW
        pred = router.route(query=q, ref_now=DEFAULT_REF_NOW)
        pred_t = pred.get("tool")
        pred_a = pred.get("args", {})

        # Tool execution
        packet = None
        err = None
        try:
            packet = dispatch_tool(pred_t, pred_a, db_path="data/vehicle.db")
        except Exception as e:
            err = str(e)

        ans_ok = check_answer_correctness(packet, exp_facts)
        tool_ok = (pred_t == exp_t)

        if not (ans_ok and tool_ok):
            failures.append({
                "id": qid,
                "category": it["category"],
                "question": q,
                "expected_tool": exp_t,
                "predicted_tool": pred_t,
                "expected_args": exp_a,
                "predicted_args": pred_a,
                "expected_facts": exp_facts,
                "tool_ok": tool_ok,
                "ans_ok": ans_ok,
                "error": err,
            })

    print(f"Total DEV items: {len(items)}")
    print(f"Total DEV failures: {len(failures)} (Tool failures: {sum(1 for f in failures if not f['tool_ok'])}, Ans failures: {sum(1 for f in failures if not f['ans_ok'])})")
    print(f"DEV Tool Match: {((len(items) - sum(1 for f in failures if not f['tool_ok'])) / len(items)) * 100:.2f}%")
    print(f"DEV Ans Correct: {((len(items) - sum(1 for f in failures if not f['ans_ok'])) / len(items)) * 100:.2f}%\n")

    for f in failures:
        print(f"[{f['id']}] Cat:{f['category']} | ToolMatch={f['tool_ok']} AnsCorrect={f['ans_ok']}")
        print(f"  Q: \"{f['question']}\"")
        print(f"  Exp: tool={f['expected_tool']} args={f['expected_args']}")
        print(f"  Pred: tool={f['predicted_tool']} args={f['predicted_args']}")
        print(f"  Expected Facts: {f['expected_facts']}")
        if f["error"]:
            print(f"  Error: {f['error']}")
        print()

    return failures


if __name__ == "__main__":
    diagnose_planner_dev()
    diagnose_benchmark_dev()
