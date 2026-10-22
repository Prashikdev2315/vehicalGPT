"""Measure real on-device SLM runtime performance profile with model loaded in memory."""
from __future__ import annotations

import json
from pathlib import Path
import time
from typing import Any

from eval.eval_e2e import percentile
from slm.engine import get_slm_engine
from slm.grammar import get_llama_grammar
from slm.prompts import build_planner_prompt
from slm.router import PlannerRouter
from slm.telemetry import get_cgroup_peak_mb, get_process_rss_mb
from slm.templates import render_template_response
from slm.verbaliser import generate_narration
from tools.registry import dispatch_tool


def run_profiler():
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
    highest_mem = max(peak_rss, peak_cgroup)

    report = {
        "model_load_time_sec": load_time_sec,
        "rss_with_model_loaded_mb": peak_rss,
        "peak_cgroup_memory_mb": highest_mem,
        "container_memory_limit_mb": 2048.0,
        "actual_container_headroom_mb": round(2048.0 - highest_mem, 2),
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
    return report


if __name__ == "__main__":
    run_profiler()
