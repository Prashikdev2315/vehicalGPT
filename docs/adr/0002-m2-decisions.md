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
- Baseline normal statistics ($\mu_0, \sigma_0$) are calculated from the first 20% of the lookback *time span* rather than sample counts, preventing high-rate snapshot bursts from distorting early-window baselines.
- Deviation onset is algorithmically declared upon 3 consecutive sustained departures exceeding $\max(3\sigma_0, \text{min\_dev})$.
- No hardcoded time offsets or causal assumptions are permitted.

**Empirical Result:** For the S3 battery overheat scenario (event #17), the engine algorithmically detects `coolant_pump_duty` deviation at $-445.0\,\text{s}$ prior to the event, followed by `pack_temp` deviation at $-382.0\,\text{s}$, proving pump degradation preceded battery overheating by $63.0\,\text{s}$.

---

## D4. Independent Causal Attribution Decomposition
**Decision:** The `explain_change` tool and `insight/attribution.py` decompose shifts in metrics (such as `range_per_charge` and `energy_per_km`) without reading `SimConfig` or simulation constants:
- HVAC power consumption is directly measured from trip energy records ($\text{hvac\_energy\_kwh} / \text{distance\_km}$).
- Firmware OTA step changes are dynamically detected from the `events` table (`type = 'ota_update'`), measuring the step discontinuity across trips immediately before and after the update.
- Gating on fit quality: relation is marked `"attributed_contribution"` when model fit is strong ($R^2 \ge 0.60$ or residual error $< 40\%$), and `"correlation"` otherwise.
- Counterfactual validation proves attribution is within $\pm 10$ percentage points of true ground truth.

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

## D7. 100-Question Evaluation Benchmark
**Decision:** A 100-question evaluation benchmark (`eval/benchmark.json`) is maintained with a 50/50 dev/test split, covering all 10 tools, conversational paraphrases, diagnostics, edge cases, data gaps, and refusals (control requests, out-of-scope queries, and safety judgements).
All tool outputs must strictly validate against `docs/evidence_packet.schema.json`.
Target latency is p50 < 500 ms, p95 < 2000 ms, and peak RAM < 100 MB.
