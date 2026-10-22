# Simulator Specification

Purpose: generate realistic multi-signal vehicle data and a 3-4 week history with **labelled ground-truth events**, with no hardware and no GPU. Output feeds the ingestion layer through the same interfaces used for real buses.

## Design principles
- Deterministic: every run takes a seed; same seed gives identical data.
- Physics-style, not random noise: signals must be causally linked so cause analysis is testable (temperature -> HVAC load -> energy use -> range).
- Every injected anomaly is recorded in `eval/ground_truth.json` with start/end, cause, and affected signals.
- Output paths: (a) live emission on a python-can bus, (b) candump-format log files, (c) direct bulk load into SQLite for fast history generation.
- Time compression: history can be generated faster than real time; live mode runs at real time.

## Vehicle model (EV baseline; fuel variant optional)
- Drive cycles: city, highway, mixed; each trip is a speed profile with stops, accelerations and road type tags.
- Energy per km = rolling resistance + aero (speed squared) + auxiliary load + battery efficiency factor (temperature dependent).
- Auxiliary load: HVAC power depends on (cabin target - ambient temperature); heating draws more than cooling.
- Battery: state of charge, pack voltage/current, pack and coolant temperatures; thermal model with cooling pump duty.
- Range estimate: usable energy / recent energy-per-km.
- Daily routine: weekday commute trips, occasional weekend long trip, charging sessions overnight.
- Ambient temperature: daily cycle plus a gradual cooling trend across the generated period.

## Starting signal set (about 40; finalise in `docs/signal_catalog.csv`)
| Group | Signals |
|---|---|
| Motion | vehicle_speed, accel_long, accel_lat, brake_pressure, throttle_position, steering_angle |
| Battery/powertrain | soc, pack_voltage, pack_current, pack_temp, coolant_temp, coolant_pump_duty, motor_power, regen_power |
| Energy/range | energy_per_km, range_estimate, range_per_charge (derived) |
| Climate | ambient_temp, cabin_temp, hvac_power, hvac_mode |
| Chassis | tire_pressure_fl/fr/rl/rr, odometer |
| ADAS | adas_state, lane_keep_active, acc_active, disengagement_reason |
| System/diag | dtc events, ecu_heartbeat, log lines per source |
| Location (coarse) | road_type (city/highway), zone id |

Signal rates: fast signals 10-50 Hz in live mode; stored raw at the rate needed, aggregated per `schema.sql` tiers.

## Injected scenarios (ground truth)
| ID | Scenario | What is injected | Expected explanation |
|---|---|---|---|
| S1 | Range reduction over ~2 weeks | Gradual ambient temperature drop + higher heating use | Range down ~10-15%; most attributable to HVAC and temperature, remainder unexplained |
| S2 | Efficiency regression after software update | Step change in energy_per_km on a known date; ota_update event logged | Largest change aligns with the update date |
| S3 | Battery overheating warning | Coolant pump duty degrades 5-10 minutes before pack temperature rises, then warning event and DTC | Timeline shows pump duty drop first, then temperature rise rate increase |
| S4 | ADAS disengagements | Several events on specific days with reason codes (e.g. low lane-marking confidence, driver override) | Event search returns exactly the injected set for a given day |
| S5 | City vs highway difference | Different energy_per_km profile per road type | Comparison shows highway vs city gap matching the model |
| S6 | Tire pressure drift (optional) | Slow pressure loss on one tyre | Contributes a small share to efficiency decline |
| S7 | Missing data (optional) | Signal dropout window and a source outage | Answers must report data gaps instead of guessing |

Decoys: include benign anomalies (a one-off hard brake, a brief warning that clears) so the system is tested on false positives.

## Outputs
- `vehicle.db` populated per `docs/schema.sql` (history for the requested number of days).
- `data/candump/*.log` for replay.
- `eval/ground_truth.json`: list of `{id, scenario, ts_start, ts_end, cause, signals, expected_facts}`.
- `docs/signals.dbc` and `docs/signal_catalog.csv` consistent with the generated signals.
- A small curated `dtc_knowledge` seed (30-50 codes relevant to the scenarios; hand-written, not LLM-generated).

## Interfaces
- `sim.generate_history(days, seed, out_db)` for bulk history.
- `sim.run_live(bus_config, speedup=1.0)` to emit on a python-can bus.
- `sim.write_candump(path, start, duration, seed)` for log files.
- Bus config selects `virtual`, `udp_multicast` or real `socketcan` without code changes.

## Acceptance tests
- Same seed produces byte-identical output.
- Every ground-truth event is present in `events`/`dtcs` as labelled.
- Derived metrics (e.g. range_per_charge) reproduce the intended S1 drop within a stated tolerance.
- Round trip: candump replay through ingestion yields the same rows as direct load.
- Generated history size per day is reported and compared with the PRD storage estimate.

## Fixtures for other adapters
Provide small recorded fixture files (SOME/IP service messages, Android VHAL property dumps, QNX/DLT-style log excerpts) that exercise each adapter. Label them as fixtures; do not describe them as real vehicle captures.
