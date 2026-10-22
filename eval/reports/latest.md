# VehicleGPT Milestone 2 Evaluation Report

- **Date / Time:** `2026-10-22T13:56:57.830912+00:00`
- **Split:** `all` (100 questions evaluated)
- **Schema Adherence:** **100.0%** (strict validation against `docs/evidence_packet.schema.json`)
- **Tool Execution Success Rate:** **100.0%**
- **Refusal Accuracy:** **100.0%**
- **Overall Latency (p50 / p95):** **162.45 ms** / **335.41 ms**
- **Peak RAM Allocation:** **0.72 MB** (strictly < 100 MB target)

## Latency Breakdown by Tool

| Tool | Queries | p50 Latency (ms) | p95 Latency (ms) | Target Met |
| :--- | :---: | :---: | :---: | :---: |
| `compare` | 8 | 159.9 | 162.1 | ✓ |
| `current_state` | 9 | 163.2 | 191.0 | ✓ |
| `explain_change` | 6 | 162.1 | 176.1 | ✓ |
| `get_events` | 12 | 160.6 | 180.6 | ✓ |
| `largest_change` | 5 | 161.4 | 166.6 | ✓ |
| `lookup_dtc` | 7 | 157.3 | 171.4 | ✓ |
| `respond_direct` | 30 | 163.9 | 171.2 | ✓ |
| `search_logs` | 7 | 158.0 | 171.2 | ✓ |
| `timeline_before` | 6 | 1130.7 | 4110.4 | FAIL |
| `trend` | 10 | 224.3 | 292.6 | ✓ |

## Query Execution Sample (First 20 Questions)

| ID | Split | Category | Expected Tool | Success | Schema Valid | Latency (ms) | Peak RAM (KB) |
| :--- | :---: | :--- | :--- | :---: | :---: | :---: | :---: |
| `bm_001` | `dev` | attribution | `explain_change` | ✓ | ✓ | 163.6 | 178.2 |
| `bm_002` | `test` | attribution | `explain_change` | ✓ | ✓ | 180.0 | 216.3 |
| `bm_003` | `dev` | attribution | `explain_change` | ✓ | ✓ | 156.0 | 218.2 |
| `bm_004` | `test` | attribution | `explain_change` | ✓ | ✓ | 160.5 | 223.5 |
| `bm_005` | `dev` | attribution | `explain_change` | ✓ | ✓ | 158.7 | 227.0 |
| `bm_006` | `test` | change_point | `largest_change` | ✓ | ✓ | 167.3 | 209.9 |
| `bm_007` | `dev` | change_point | `largest_change` | ✓ | ✓ | 161.4 | 214.1 |
| `bm_008` | `test` | change_point | `largest_change` | ✓ | ✓ | 152.8 | 217.6 |
| `bm_009` | `dev` | change_point | `largest_change` | ✓ | ✓ | 163.9 | 221.3 |
| `bm_010` | `test` | change_point | `largest_change` | ✓ | ✓ | 156.5 | 222.5 |
| `bm_011` | `dev` | events | `get_events` | ✓ | ✓ | 154.1 | 221.3 |
| `bm_012` | `test` | events | `get_events` | ✓ | ✓ | 156.8 | 223.0 |
| `bm_013` | `dev` | events | `get_events` | ✓ | ✓ | 153.3 | 223.6 |
| `bm_014` | `test` | events | `get_events` | ✓ | ✓ | 157.4 | 224.0 |
| `bm_015` | `dev` | events | `get_events` | ✓ | ✓ | 157.0 | 224.7 |
| `bm_016` | `test` | timeline | `timeline_before` | ✓ | ✓ | 5101.5 | 604.3 |
| `bm_017` | `dev` | timeline | `timeline_before` | ✓ | ✓ | 1136.8 | 611.3 |
| `bm_018` | `test` | timeline | `timeline_before` | ✓ | ✓ | 1133.3 | 614.7 |
| `bm_019` | `dev` | timeline | `timeline_before` | ✓ | ✓ | 1128.2 | 617.8 |
| `bm_020` | `test` | timeline | `timeline_before` | ✓ | ✓ | 1101.5 | 618.5 |
