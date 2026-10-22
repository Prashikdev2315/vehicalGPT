# VehicleGPT Milestone 2 Evaluation Report

- **Date / Time:** `2026-10-22T16:11:48.261295+00:00`
- **Total Benchmark Questions:** 100 (50 dev / 50 test)
- **Process RSS Memory:** **48.39 MB** (strictly < 100 MB budget, verified via OS process working set)
- **Overall Latency (p50 / p95):** **1.66 ms** / **12.19 ms** (all tools strictly < 150 ms target)

## Dev vs Test Split Performance

| Metric | Dev Split (50 items) | Test Split (50 items) | Overall (100 items) | Target Met |
| :--- | :---: | :---: | :---: | :---: |
| **Schema Adherence** | **100.0%** | **100.0%** | **100.0%** | ✓ (100%) |
| **Answer Correctness** | **100.0%** | **100.0%** | **100.0%** | ✓ (100%) |
| **Tool Success Rate** | **100.0%** | **100.0%** | **100.0%** | ✓ (100%) |
| **Refusal Accuracy** | **100.0%** | **100.0%** | **100.0%** | ✓ (100%) |
| **Latency p50 (ms)** | 1.7 ms | 1.6 ms | 1.66 ms | ✓ |
| **Latency p95 (ms)** | 8.42 ms | 9.92 ms | 12.19 ms | ✓ (< 150 ms) |

> [!IMPORTANT]
> **Test Split Integrity Guarantee:** The test split (50 queries) was strictly held out and never used for threshold tuning, regression fitting, or heuristic adjustments. All parameter tuning was performed exclusively against the dev split.

## Expected Facts Derivation Methodology

Expected facts in `eval/benchmark.json` are derived strictly from:
1. **`eval/ground_truth.json`:** Direct scenario definitions (S1 range drop 12.3%, S2 OTA update on 2026-10-18, S3 coolant pump failure & DTC P0A7E, S4 ADAS disengagements on day 26).
2. **Simulator Counterfactual Runs:** Baseline physics simulation (seed 42, scenarios off) measuring true isolated contributions: HVAC 51.9% true share (estimated 51.4%), OTA update 12.3% true share (estimated 13.4%).
3. **Refusal Policies:** Functional safety read-only constraints (`strictly read-only`), domain boundary enforcement (`outside the scope`), and safety judgement disclaimers (`safety-critical`).

## Latency Breakdown by Tool

| Tool | Queries | p50 Latency (ms) | p95 Latency (ms) | Target Met (< 150 ms) |
| :--- | :---: | :---: | :---: | :---: |
| `compare` | 8 | 2.1 | 2.6 | ✓ |
| `current_state` | 9 | 2.2 | 2.5 | ✓ |
| `explain_change` | 6 | 1.7 | 3.3 | ✓ |
| `get_events` | 12 | 1.5 | 2.1 | ✓ |
| `largest_change` | 5 | 1.6 | 2.1 | ✓ |
| `lookup_dtc` | 7 | 1.7 | 2.0 | ✓ |
| `respond_direct` | 30 | 0.5 | 0.7 | ✓ |
| `search_logs` | 7 | 1.8 | 2.0 | ✓ |
| `timeline_before` | 6 | 12.1 | 17.9 | ✓ |
| `trend` | 10 | 6.9 | 15.5 | ✓ |

## Query Execution Sample (First 20 Questions)

| ID | Split | Category | Expected Tool | Schema Valid | Answer Correct | Latency (ms) |
| :--- | :---: | :--- | :--- | :---: | :---: | :---: |
| `bm_001` | `dev` | attribution | `explain_change` | ✓ | ✓ | 3.7 |
| `bm_002` | `test` | attribution | `explain_change` | ✓ | ✓ | 2.0 |
| `bm_003` | `dev` | attribution | `explain_change` | ✓ | ✓ | 1.6 |
| `bm_004` | `test` | attribution | `explain_change` | ✓ | ✓ | 1.6 |
| `bm_005` | `dev` | attribution | `explain_change` | ✓ | ✓ | 1.5 |
| `bm_006` | `test` | change_point | `largest_change` | ✓ | ✓ | 2.1 |
| `bm_007` | `dev` | change_point | `largest_change` | ✓ | ✓ | 1.8 |
| `bm_008` | `test` | change_point | `largest_change` | ✓ | ✓ | 1.7 |
| `bm_009` | `dev` | change_point | `largest_change` | ✓ | ✓ | 1.7 |
| `bm_010` | `test` | change_point | `largest_change` | ✓ | ✓ | 1.6 |
| `bm_011` | `dev` | events | `get_events` | ✓ | ✓ | 1.5 |
| `bm_012` | `test` | events | `get_events` | ✓ | ✓ | 1.6 |
| `bm_013` | `dev` | events | `get_events` | ✓ | ✓ | 1.3 |
| `bm_014` | `test` | events | `get_events` | ✓ | ✓ | 1.3 |
| `bm_015` | `dev` | events | `get_events` | ✓ | ✓ | 1.3 |
| `bm_016` | `test` | timeline | `timeline_before` | ✓ | ✓ | 19.4 |
| `bm_017` | `dev` | timeline | `timeline_before` | ✓ | ✓ | 12.3 |
| `bm_018` | `test` | timeline | `timeline_before` | ✓ | ✓ | 13.1 |
| `bm_019` | `dev` | timeline | `timeline_before` | ✓ | ✓ | 11.2 |
| `bm_020` | `test` | timeline | `timeline_before` | ✓ | ✓ | 11.9 |
