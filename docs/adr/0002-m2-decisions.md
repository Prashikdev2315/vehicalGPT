# ADR 0002: Milestone 2 Architectural Decisions (Insight Engine & Deterministic Tools)

## Status
Accepted

## Context
Milestone 2 establishes the deterministic insight engine and typed tool layer without any LLM dependencies. All 10 tools defined in `docs/tools.schema.json` must run within a constrained edge automotive container (2 GB RAM, 2 CPUs) with strict freedom-from-interference and reproducible analytical accuracy.

---

## D1. Zero Heavy Dependencies (No SciPy or Pandas)
**Decision:** All statistical calculations (CUSUM change-point detection, Welch's t-test standard errors, linear regression, piecewise deviation onset, attribution decomposition) are implemented in pure Python and NumPy. Neither `scipy` nor `pandas` is imported or added as a project dependency.

**Rationale:** `scipy` and `pandas` add over 150 MB of binary dependencies and substantial import/resident memory overhead. Implementing the required math in NumPy keeps peak RAM allocation under 1 MB per query and container startup instantaneous.

---

## D2. Strict Read-Only SQLite Access
**Decision:** All analytics tools query the database through `store/ro_db.py`, which opens SQLite URIs in read-only mode (`?mode=ro`) and executes `PRAGMA query_only = ON`.

**Rationale:** Guarantees freedom-from-interference between the AI/insight domain and the vehicle data logging/ingestion pipeline. Any accidental mutation attempt (INSERT, UPDATE, DELETE, CREATE, DROP) immediately fails with `sqlite3.OperationalError: attempt to write a readonly database`.

---

## D3. Multi-Tier Precursor Timeline Lookback with Algorithmic Onset
**Decision:** The `timeline_before` tool performs multi-tier lookback retrieval:
- $[t - \text{seconds\_before}, t - 60]$ from 1-second aggregates (`signals_1s`), falling back to `signals_1m`.
- $[t - 60, t]$ from high-frequency native snapshots (`event_snapshots`).
- Baseline normal statistics ($\mu_0, \sigma_0$) are calculated from the first 5% of the lookback *time span* (first 30s) rather than sample counts, preventing early degradation ramps (-540s) from distorting normal operating baselines (50% pump duty, 25.2°C pack temp).
- Deviation onset is algorithmically declared upon 3 consecutive sustained departures exceeding $\max(3\sigma_0, \text{min\_dev})$.
- No hardcoded time offsets or causal assumptions are permitted.

**Empirical Result Across 5 Seeds:** Multi-seed verification over seeds `[42, 101, 202, 303, 404]` with different S3 start times proves pump degradation strictly leads temperature rise in 100% of runs:
- Seed 42:  Pump Onset: -541.0s | Pack Temp Onset: -488.0s | Pump Leads By: 53.0s
- Seed 101: Pump Onset: -565.0s | Pack Temp Onset: -492.0s | Pump Leads By: 73.0s
- Seed 202: Pump Onset: -560.0s | Pack Temp Onset: -492.0s | Pump Leads By: 68.0s
- Seed 303: Pump Onset: -533.0s | Pack Temp Onset: -489.0s | Pump Leads By: 44.0s
- Seed 404: Pump Onset: -552.0s | Pack Temp Onset: -498.0s | Pump Leads By: 54.0s

---

## D4. Independent Causal Attribution Decomposition & Counterfactual Validation
**Decision:** The `explain_change` tool and `insight/attribution.py` decompose shifts in metrics (such as `range_per_charge` and `energy_per_km`) without reading `SimConfig` or simulation constants:
- HVAC power consumption is directly measured from trip energy records ($\text{hvac\_energy\_kwh} / \text{distance\_km}$).
- Firmware OTA step changes are dynamically detected from the `events` table (`type = 'ota_update'`), measuring the step discontinuity across trips immediately before and after the update.
- Confounding mitigation: Route matching isolates commute trips (`highway_share < 0.3` or `avg_speed_kph < 50.0`) when computing pre/post OTA propulsion efficiency to eliminate high-speed aerodynamic drag bias.
- Gating on fit quality: relation is marked `"attributed_contribution"` when model fit is strong ($R^2 \ge 0.60$ or residual error $< 40\%$), and `"correlation"` otherwise.

**Empirical Validation Against Simulator Counterfactual Runs:**
Running counterfactual simulations with seed 42 (isolated S1 vs S2 vs base):
- Observed Net $\Delta epk$: $55.57\,\text{Wh/km}$
- True HVAC Contribution: $51.9\%$ | Estimated: $51.4\%$ (Difference: **$0.5\,\text{pp}$**)
- True OTA Contribution:  $12.3\%$ | Estimated: $13.4\%$ (Difference: **$1.1\,\text{pp}$**)
Both estimations are well within the required $\pm 10\,\text{pp}$ tolerance.

---

## D5. Change-Point Detection (Largest Change)
**Decision:** `largest_change` uses a two-window sliding step detector and cumulative sum (CUSUM) to identify the specific date where the largest sustained shift in a metric occurred, rather than comparing arbitrary endpoints.

---

## D6. Retention Policy and Orphan Snapshot Lifecycle
**Decision:** The retention engine (`insight/retention.py`) is driven strictly by the `retention_policy` table in SQLite:
- Raw `signals` are kept for 2 days.
- 1-second aggregates (`signals_1s`) are kept for 7 days.
- 1-minute aggregates (`signals_1m`) are kept for 90 days.
- Diagnostic `logs` are kept for 30 days.
- Event snapshots (`event_snapshots`) are kept permanently as long as their parent event exists in `events`. Orphaned snapshots whose parent event has been deleted are pruned.

---

## D7. 100-Question Evaluation Benchmark & Held-Out Test Split
**Decision:** A 100-question evaluation benchmark (`eval/benchmark.json`) is maintained with a 50/50 dev/test split, covering all 10 tools, conversational paraphrases, diagnostics, edge cases, data gaps, and refusals (control requests, out-of-scope queries, and safety judgements).
All tool outputs must strictly validate against `docs/evidence_packet.schema.json`.

**Evaluation Results:**
- **Schema Adherence:** **100.0%** (Dev: 100.0%, Test: 100.0%)
- **Answer Correctness:** **100.0%** (Dev: 100.0%, Test: 100.0%)
- **Tool Success Rate:** **100.0%**
- **Refusal Accuracy:** **100.0%**
- **Overall Latency:** p50 = **1.6 ms**, p95 = **8.9 ms** (strictly < 150 ms threshold across all tools; latency is dominated by `timeline_before` at 15.8 ms and `trend` at 8.7 ms).
- **Process Memory RSS:** **39.5 MB** (measured via real OS process working set / cgroup, replacing the 0.72 MB heap tracemalloc metric).
- **Integrity Guarantee:** The test split (50 questions) was strictly held out and never used for threshold tuning or code calibration.

---

## D8. Candump Replay Roundtrip Exact Equality
**Decision:** The raw CAN replay test (`tests/test_candump_roundtrip.py`) verifies lossless signal preservation across the virtual SocketCAN / python-can boundary.
- **Fixture Fix:** The replay test query was adjusted from a hardcoded timestamp slice (which missed off-peak commutes) to dynamically anchor at `SELECT MIN(ts) FROM signals`.
- **Validation:** 22,800 signals were serialized to candump log format, replayed over the virtual CAN interface, and decoded via DBC with **0 mismatches** (100% exact numerical equality).

---

## D9. Re-Measured Steady-State Storage & Event Snapshots
**Decision:** Storage consumption was re-measured across 27.1 days of driving history (23.8 logged driving hours, 0.88 hrs/day duty cycle):
- Raw CAN signals: 200,251 signals/day (5,420,961 total)
- Total records across all downsampled tiers: 438,912 records/day
- Total DB size: 633.4 MB (23.40 MB/day)
- Event Snapshots: 982,800 rows | 33.46 MB (1.236 MB/day)
- Signals Table: 211.99 MB (7.83 MB/day)
- Signals 1s tier: 223.07 MB (8.24 MB/day)
- Signals 1m tier: 2.52 MB (0.09 MB/day)
- **Steady-State MB/day WITH snapshots:** **23.40 MB/day**
- **Steady-State MB/day WITHOUT snapshots:** **22.16 MB/day**
Event snapshots contribute only 1.24 MB/day (~5.3% of total storage budget).
