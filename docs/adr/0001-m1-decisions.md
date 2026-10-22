# ADR 0001 — Milestone 1 Design Decisions

**Status:** Accepted
**Date:** 2026-10-22
**Context:** Ambiguities and conflicts found during M1 planning; resolved by project owner.

---

## D1. `range_per_charge` storage

**Decision:** `range_per_charge` is stored only in `digest_daily` and `trips`, never in the raw `signals` table. It remains in `signal_catalog` with `source = derived` so tool-argument validation can accept it as a valid metric name. Tool metric validation checks both catalog signals and digest metric names.

**Rationale:** Storing a derived metric at 1 Hz inflates the `signals` table for no benefit; the insight engine can compute finer granularity from trip-level data when needed.

## D2. Signal storage rates

**Decision:**
- The raw `signals` table is written at **1 Hz** (pre-aggregated from the simulator's native rate).
- Full-rate data (10-50 Hz) exists only in the in-memory ring buffer and candump log files.
- **Event snapshots:** full-rate data for **±60 seconds** around each event is stored in a snapshot (separate table or file), so timeline-before queries have high-resolution data.

**Rationale:** 40 signals × 10 Hz × 86400 s ≈ 34 M rows/day raw, far exceeding the ~70 MB/day PRD estimate at 1 Hz. The ±60 s event snapshots preserve the detail needed for S3 (battery overheating timeline) without the storage cost.

## D3. Pure EV, no fuel

**Decision:** M1 generates pure-EV data. `trips.fuel_l` is always NULL. Add aliases `["fuel_efficiency", "efficiency", "mileage"]` to the `energy_per_km` signal in the catalog.

**Rationale:** The fuel model adds complexity with no demo value. Aliases ensure natural-language queries about "efficiency" map to the correct metric.

## D4. python-can version pinning

**Decision:** Do not assume a python-can version. During M1 setup:
1. Install python-can and verify dependencies.
2. Run two-process integration test (`tests/test_udp_multicast.py`) that sends frames on `udp_multicast` from process A and receives in process B.
3. Test passed successfully on `python-can==4.6.1` with `msgpack==1.2.3` (required by python-can for udp_multicast serialization).
4. Pin `python-can==4.6.1` and `msgpack>=1.0.0` in `pyproject.toml`.
5. Skip `socketcand`.

**python-can version:** `python-can==4.6.1` (verified with `tests/test_udp_multicast.py`).

**Rationale:** The `udp_multicast` interface behaviour varies across versions; testing first avoids surprises.

## D5. CAN frame format

**Decision:** Classic 8-byte CAN for all regular messages. Add **one CAN-FD message** (64-byte payload) carrying a combined diagnostics snapshot, with a test that verifies FD support on the virtual bus. If the virtual bus does not support FD, document the limitation and use classic CAN only.

**Rationale:** Proves CAN-FD works without making the entire DBC depend on it. Most signals fit comfortably in 8-byte frames.

## D6. Adapter fixtures

**Decision:** Create tiny placeholder fixture files in `fixtures/` (SOME/IP, VHAL, QNX) and stub adapters that can parse them. No real adapter logic until M5.

## D7. Candump roundtrip precision

**Decision:** The simulator quantises all signal values to the DBC-defined resolution **before** writing to the DB. The roundtrip test (candump → ingest → DB) then requires **exact equality**, not approximate. This makes the DBC the single source of truth for signal precision.

**Rationale:** A tolerance-based comparison hides encoding bugs. Quantising at the source ensures the DB and the CAN bus carry identical values.

## D8. Candump file scope

**Decision:** `make sim` writes candump files for:
1. One representative full day (the day containing the most events).
2. The S3 event window (±5 minutes around the battery overheating scenario).
3. A small test sample (1 hour of normal driving).

Total candump size is reported by `make sim`. Do **not** generate 28 days of candump logs.

## D9. S1/S2 overlap

**Decision:** Keep the overlap deliberately. S1 (gradual range loss from temperature/HVAC) and S2 (step-change from OTA update on ~day 18) overlap in the second half. `ground_truth.json` records this as an **interacting-causes case**: the expected facts for the overlap window state that both temperature/HVAC and the OTA update contribute, with adjusted attribution percentages.

**Rationale:** Real vehicles have overlapping causes. Testing the insight engine on this case is more valuable than separating them.

## D10. WSL2 requirement

**Decision:** WSL2 with Ubuntu is the required development shell. It is not currently installed on this machine. Setup of WSL2 is a prerequisite before code execution begins.

**Note:** File creation and planning can proceed on the Windows filesystem; all scripts, Makefile, and Docker commands will target Linux/WSL2.

## D11. File rename

**Decision:** `docs/problem statement.md` renamed to `docs/problem_statement.md`. All references updated.

## D12. Battery thermal stagnation heating term during pump degradation (S3)

**Decision:** When `pump_duty_override` is active and degraded below normal duty (< 50%), add a coolant stagnation heating term to the battery thermal model:
$$\text{heat\_gen\_kw} += 4.5 \times \left(1.0 - \frac{\text{coolant\_pump\_duty}}{50.0}\right)$$

**Rationale:** In a liquid-cooled battery pack, coolant circulation is necessary to transport heat from cell cores to the radiator. When the coolant pump stalls or degrades, coolant flow ceases, eliminating convective heat transfer and causing localized cell thermal hot-spots. Without this term, driving at moderate commute speeds (10–15 A draw) produced insufficient Joule heating ($I^2R \approx 0.3\,\text{kW}$) to elevate the 50 kJ/K pack thermal mass from 32°C to the 45°C overtemperature threshold within the 10-minute degradation window. The stagnation term accurately reproduces the rapid cell core temperature rise seen in real EV coolant pump failures while ensuring `coolant_pump_duty` drops before `pack_temp` rises.

## D13. Docker container network multicast and alternative transports

**Decision:**
1. **Container Networking for Multicast:** Standard Docker bridge networks (`bridge`) filter or isolate UDP multicast packets across containers and virtual interfaces due to IGMP snooping and default bridge iptables rules. For multi-process CAN streaming over `udp_multicast` inside Docker, containers must run with `network_mode: host` (`--net=host`) so processes share the network namespace and multicast routing on loopback.
2. **Alternative Transports:** If host networking cannot be used (e.g. in orchestrators requiring network namespace isolation), alternative transports are:
   - **Linux SocketCAN (`vcan0`):** Pass `/dev/net/tun` or host SocketCAN interface into the container.
   - **UNIX Domain Sockets / IPC:** Fast, lightweight point-to-point or broadcast transport for local inter-process communication.
   - **`socketcand` (TCP):** Bridges CAN frames over standard TCP connections across container network bridges without multicast dependencies.
3. **Multi-Arch (`linux/arm64`):** Cross-building container images for ARM64 requires Docker Buildx with QEMU binfmt emulation (`tonistiigi/binfmt`). On hosts where the Docker daemon is not active, builds must be run via Docker Desktop or CI.

## D14. Vehicle clock and timezone anchoring

**Decision:**
1. `SimConfig` maintains a vehicle timezone (default `Asia/Kolkata`) and an anchor `reference_now` datetime.
2. The generated history starts at `start_date = (reference_now.date() - (days - 1))` at `00:00:00` and ends strictly at `reference_now`.
3. No simulation data, events, or trips are permitted to extend into the future relative to `reference_now` (`ts <= ref_now_ms`).
4. Daily digests (`digest_daily.day`) and relative date calculations ("yesterday", "today") are formatted in the vehicle timezone.

