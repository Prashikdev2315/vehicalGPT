"""Measure real on-device SLM runtime performance profile with model loaded in memory."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from eval.eval_e2e import percentile
from slm.engine import get_slm_engine
from slm.grammar import get_llama_grammar
from slm.prompts import build_planner_prompt
from slm.router import PlannerRouter
from slm.telemetry import (
    get_cgroup_peak_mb,
    get_process_rss_mb,
    get_runtime_memory_profile,
    verify_container_memory_limit,
)
from slm.templates import render_template_response
from slm.verbaliser import generate_narration
from tools.registry import dispatch_tool


def run_profiler(require_cgroup: bool = False, out_path: Path | None = None) -> dict[str, Any]:
    print("Loading SLM engine (measuring cold load time)...")
    t0 = time.perf_counter()
    engine = get_slm_engine(n_ctx=1024, n_threads=2)
    engine._ensure_loaded()
    load_time_sec = round(time.perf_counter() - t0, 3)
    rss_after_load = get_process_rss_mb()
    print(f"Cold load time: {load_time_sec} s")
    print(f"Process RSS with model loaded: {rss_after_load} MB")

    # Prompt eval & generation tokens/sec
    prompt = "<|im_start|>system\nYou are the VehicleGPT On-Board Diagnostics Planner.<|im_end|>\n<|im_start|>user\nCheck current battery state of charge.<|im_end|>\n<|im_start|>assistant\n"
    grammar = get_llama_grammar()

    t_eval_start = time.perf_counter()
    res = engine._llm(prompt, grammar=grammar, max_tokens=32, temperature=0.0)
    t_eval_end = time.perf_counter()

    usage = res.get("usage", {})
    p_tokens = usage.get("prompt_tokens", 25)
    c_tokens = usage.get("completion_tokens", 15)
    total_time = max(t_eval_end - t_eval_start, 0.001)

    print(f"Prompt tokens: {p_tokens}, Completion tokens: {c_tokens}, Total time: {total_time:.3f} s")
    print(f"Effective throughput: {c_tokens / total_time:.2f} gen tokens/s")
    print(f"Raw completion: {res['choices'][0]['text']}")

    # Measure over 5 representative queries
    test_queries = [
        "What is the current state of charge?",
        "Why did my range drop over the last 2 weeks?",
        "Did any battery overtemp warnings occur yesterday?",
        "Check diagnostic trouble code P0A80",
        "Show range trend over the last 7 days",
    ]

    router = PlannerRouter(engine=engine, enable_hard_gate=True)
    planner_latencies: list[float] = []
    tool_latencies: list[float] = []
    verbaliser_latencies: list[float] = []
    ttfa_with_planner_list: list[float] = []
    ttfn_list: list[float] = []

    db_path = Path("data/vehicle.db")
    if not db_path.exists():
        from store.db import init_db, load_signal_catalog, seed_dtc_knowledge
        conn = init_db(db_path, Path("docs/schema.sql"))
        load_signal_catalog(conn, Path("docs/signal_catalog.csv"))
        seed_dtc_knowledge(conn)
        conn.close()

    for q in test_queries:
        t_start = time.perf_counter()

        # 1. Planner routing
        tool_call = router.route(query=q)
        t_planned = time.perf_counter()
        planner_ms = (t_planned - t_start) * 1000.0
        planner_latencies.append(planner_ms)

        # 2. Tool dispatch
        t_tool_start = time.perf_counter()
        packet = dispatch_tool(tool_call["tool"], tool_call.get("args", {}), db_path)
        t_tool_end = time.perf_counter()
        tool_ms = (t_tool_end - t_tool_start) * 1000.0
        tool_latencies.append(tool_ms)

        # 3. Instant template (Time-to-first-answer INCLUDING planner)
        first_ans = render_template_response(packet)
        t_first = time.perf_counter()
        ttfa_ms = (t_first - t_start) * 1000.0
        ttfa_with_planner_list.append(ttfa_ms)

        # 4. Verbaliser
        t_verb_start = time.perf_counter()
        narration = generate_narration(engine, packet, q, max_tokens=60)
        t_verb_end = time.perf_counter()
        verb_ms = (t_verb_end - t_verb_start) * 1000.0
        verbaliser_latencies.append(verb_ms)

        ttfn_ms = (t_verb_end - t_start) * 1000.0
        ttfn_list.append(ttfn_ms)

    peak_rss = get_process_rss_mb()
    peak_cgroup = get_cgroup_peak_mb()

    mem_profile = get_runtime_memory_profile(during_model_execution=True)
    cgroup_verified, cgroup_msg, cgroup_snap = verify_container_memory_limit()

    # Determine limit and headroom based strictly on verified cgroups
    if cgroup_verified and cgroup_snap.limit_mb is not None:
        container_limit_mb = cgroup_snap.limit_mb
        cgroup_status = cgroup_snap.status
        headroom_mb = round(container_limit_mb - peak_cgroup, 2) if peak_cgroup is not None else None
    else:
        container_limit_mb = None
        cgroup_status = cgroup_snap.status if cgroup_snap.cgroup_version is not None else "BLOCKED_NO_CGROUP"
        headroom_mb = None

    report = {
        "model_load_time_sec": load_time_sec,
        "during_model_execution": True,
        "host_process_rss_mb": peak_rss,
        "host_memory_source": mem_profile.get("host_memory_source"),
        "peak_cgroup_memory_mb": peak_cgroup,
        "container_memory_limit_mb": container_limit_mb,
        "actual_container_headroom_mb": headroom_mb,
        "cgroup_enforced_2gb": cgroup_verified,
        "cgroup_verification_status": cgroup_status,
        "cgroup_verification_message": cgroup_msg,
        "cgroup_snapshot": cgroup_snap.to_dict(),
        "prompt_tokens": p_tokens,
        "generation_tokens": c_tokens,
        "tokens_per_second": round(c_tokens / total_time, 2),
        "planner_latency_ms_p50": percentile(planner_latencies, 50),
        "planner_latency_ms_p95": percentile(planner_latencies, 95),
        "tool_latency_ms_p50": percentile(tool_latencies, 50),
        "tool_latency_ms_p95": percentile(tool_latencies, 95),
        "verbaliser_latency_ms_p50": percentile(verbaliser_latencies, 50),
        "verbaliser_latency_ms_p95": percentile(verbaliser_latencies, 95),
        "time_to_first_answer_with_planner_ms_p50": percentile(ttfa_with_planner_list, 50),
        "time_to_first_answer_with_planner_ms_p95": percentile(ttfa_with_planner_list, 95),
        "time_to_full_narration_ms_p50": percentile(ttfn_list, 50),
        "time_to_full_narration_ms_p95": percentile(ttfn_list, 95),
    }

    print("\n================ PROFILE SUMMARY ================")
    print(json.dumps(report, indent=2))

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote profile report to {out_path}")

    if not cgroup_verified:
        if require_cgroup:
            print(
                f"\n[FAIL] --require-cgroup specified but container memory limit <= 2GB could not be confirmed!\n"
                f"Status: {cgroup_status}\n"
                f"Details: {cgroup_msg}",
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(
                f"\n[NOTICE] Cgroup limit unverified on current environment ({cgroup_status}).\n"
                f"Details: {cgroup_msg}\n"
                f"Host process RSS is {peak_rss} MB ({mem_profile.get('host_memory_source')}).\n"
                f"True 2GB container enforcement requires execution inside a capped Linux container.\n"
            )

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Measure on-device SLM runtime performance profile.")
    parser.add_argument(
        "--require-cgroup",
        action="store_true",
        help="Exit with code 1 if container cgroup <= 2GB limit is not verified.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Path to write JSON profile report.",
    )
    args = parser.parse_args()
    run_profiler(require_cgroup=args.require_cgroup, out_path=args.out)
