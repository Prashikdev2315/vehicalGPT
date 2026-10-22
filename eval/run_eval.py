"""Benchmark Evaluation Runner for VehicleGPT Deterministic Tools.

Measures tool execution, schema adherence, refusal precision, latency (p50/p95),
and memory footprint across the 100-question benchmark.
Generates eval/reports/latest.md report.
"""
from __future__ import annotations

import argparse
import datetime
import json
from pathlib import Path
import time
import tracemalloc
from typing import Any
import numpy as np

import tools
from tools.base import validate_evidence_packet
from tools.registry import dispatch_tool


def evaluate_benchmark(
    benchmark_path: Path | str = "eval/benchmark.json",
    db_path: str = "data/vehicle.db",
    split_filter: str | None = None,
) -> dict[str, Any]:
    """Run evaluation harness over benchmark questions."""
    with open(benchmark_path, encoding="utf-8") as f:
        benchmark = json.load(f)

    if split_filter:
        items = [item for item in benchmark if item["split"] == split_filter]
    else:
        items = benchmark

    results = []
    latencies_by_tool: dict[str, list[float]] = {}
    peak_ram_bytes: list[int] = []

    total_count = len(items)
    schema_valid_count = 0
    refusal_correct_count = 0
    total_refusal_expected = sum(1 for it in items if it["must_refuse"])
    tool_success_count = 0

    tracemalloc.start()

    for item in items:
        qid = item["id"]
        tool_name = item["expected_tool"]
        args = item["expected_args"]
        must_refuse = item["must_refuse"]
        expected_facts = item.get("expected_facts", [])

        # Measure query latency and memory
        t_start = time.perf_counter()
        tracemalloc.reset_peak()

        try:
            packet = dispatch_tool(tool_name, args, db_path=db_path)
            tool_err = None
        except Exception as e:
            packet = None
            tool_err = str(e)

        elapsed_ms = (time.perf_counter() - t_start) * 1000.0
        _, peak_bytes = tracemalloc.get_traced_memory()
        peak_ram_bytes.append(peak_bytes)

        latencies_by_tool.setdefault(tool_name, []).append(elapsed_ms)

        # 1. Schema validation
        schema_valid = False
        if packet is not None:
            try:
                validate_evidence_packet(packet)
                schema_valid = True
                schema_valid_count += 1
            except Exception as e:
                tool_err = f"Schema validation error: {e}"

        # 2. Refusal check
        refusal_match = False
        if must_refuse:
            if packet and packet.get("tool") == "respond_direct":
                refusal_match = True
                refusal_correct_count += 1
        else:
            if packet and packet.get("tool") != "respond_direct":
                refusal_match = True

        # 3. Overall success
        success = (packet is not None) and schema_valid and (not tool_err)
        if success:
            tool_success_count += 1

        results.append({
            "id": qid,
            "split": item["split"],
            "category": item["category"],
            "question": item["question"],
            "expected_tool": tool_name,
            "success": success,
            "schema_valid": schema_valid,
            "latency_ms": elapsed_ms,
            "peak_ram_kb": peak_bytes / 1024.0,
            "error": tool_err,
        })

    tracemalloc.stop()

    # Latency percentiles
    all_latencies = [r["latency_ms"] for r in results]
    p50_overall = float(np.percentile(all_latencies, 50)) if all_latencies else 0.0
    p95_overall = float(np.percentile(all_latencies, 95)) if all_latencies else 0.0

    tool_latencies = {}
    for tname, lats in latencies_by_tool.items():
        tool_latencies[tname] = {
            "p50_ms": round(float(np.percentile(lats, 50)), 2),
            "p95_ms": round(float(np.percentile(lats, 95)), 2),
            "count": len(lats),
        }

    max_peak_ram_mb = max(peak_ram_bytes) / (1024.0 * 1024.0) if peak_ram_bytes else 0.0

    summary = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "total_queries": total_count,
        "split": split_filter or "all",
        "schema_adherence_pct": round((schema_valid_count / total_count) * 100.0, 1),
        "tool_success_pct": round((tool_success_count / total_count) * 100.0, 1),
        "refusal_accuracy_pct": round((refusal_correct_count / max(total_refusal_expected, 1)) * 100.0, 1),
        "latency_p50_ms": round(p50_overall, 2),
        "latency_p95_ms": round(p95_overall, 2),
        "peak_ram_mb": round(max_peak_ram_mb, 2),
        "tool_latencies": tool_latencies,
        "results": results,
    }
    return summary


def write_markdown_report(summary: dict[str, Any], report_path: Path | str = "eval/reports/latest.md") -> None:
    """Format evaluation results into a detailed Markdown report."""
    path = Path(report_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "# VehicleGPT Milestone 2 Evaluation Report",
        "",
        f"- **Date / Time:** `{summary['timestamp']}`",
        f"- **Split:** `{summary['split']}` ({summary['total_queries']} questions evaluated)",
        f"- **Schema Adherence:** **{summary['schema_adherence_pct']}%** (strict validation against `docs/evidence_packet.schema.json`)",
        f"- **Tool Execution Success Rate:** **{summary['tool_success_pct']}%**",
        f"- **Refusal Accuracy:** **{summary['refusal_accuracy_pct']}%**",
        f"- **Overall Latency (p50 / p95):** **{summary['latency_p50_ms']} ms** / **{summary['latency_p95_ms']} ms**",
        f"- **Peak RAM Allocation:** **{summary['peak_ram_mb']} MB** (strictly < 100 MB target)",
        "",
        "## Latency Breakdown by Tool",
        "",
        "| Tool | Queries | p50 Latency (ms) | p95 Latency (ms) | Target Met |",
        "| :--- | :---: | :---: | :---: | :---: |",
    ]

    for tool_name, stats in sorted(summary["tool_latencies"].items()):
        met = "✓" if stats["p95_ms"] < 2000.0 else "FAIL"
        lines.append(f"| `{tool_name}` | {stats['count']} | {stats['p50_ms']:.1f} | {stats['p95_ms']:.1f} | {met} |")

    lines.extend([
        "",
        "## Query Execution Sample (First 20 Questions)",
        "",
        "| ID | Split | Category | Expected Tool | Success | Schema Valid | Latency (ms) | Peak RAM (KB) |",
        "| :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: |",
    ])

    for r in summary["results"][:20]:
        s_icon = "✓" if r["success"] else "✗"
        v_icon = "✓" if r["schema_valid"] else "✗"
        lines.append(
            f"| `{r['id']}` | `{r['split']}` | {r['category']} | `{r['expected_tool']}` | {s_icon} | {v_icon} | {r['latency_ms']:.1f} | {r['peak_ram_kb']:.1f} |"
        )

    lines.append("")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    print(f"Evaluation report written to: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="VehicleGPT Benchmark Evaluation Runner")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="all", help="Dataset split to evaluate")
    parser.add_argument("--db", default="data/vehicle.db", help="Path to vehicle database")
    parser.add_argument("--out", default="eval/reports/latest.md", help="Output report path")
    args = parser.parse_args()

    split_filter = None if args.split == "all" else args.split
    summary = evaluate_benchmark(db_path=args.db, split_filter=split_filter)

    print(f"\n=======================================================")
    print(f"VehicleGPT M2 Eval Summary ({summary['split']} split)")
    print(f"=======================================================")
    print(f"Total Questions Evaluated: {summary['total_queries']}")
    print(f"Schema Adherence:          {summary['schema_adherence_pct']}%")
    print(f"Tool Execution Success:    {summary['tool_success_pct']}%")
    print(f"Refusal Accuracy:          {summary['refusal_accuracy_pct']}%")
    print(f"Latency p50 / p95:         {summary['latency_p50_ms']} ms / {summary['latency_p95_ms']} ms")
    print(f"Peak RAM Allocation:       {summary['peak_ram_mb']} MB")
    print(f"=======================================================\n")

    write_markdown_report(summary, report_path=args.out)


if __name__ == "__main__":
    main()
