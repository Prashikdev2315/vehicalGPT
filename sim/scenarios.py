"""Scenario injectors for labelled ground-truth events.

Each scenario modifies vehicle model parameters or injects events at specific
times. All injected events are recorded in ground_truth.json.

Scenarios:
    S1: Range reduction (ambient temp drop + HVAC increase) — days 7-28
    S2: Efficiency regression after OTA update — day 18+
    S3: Battery overheating (coolant pump degradation) — day 22
    S4: ADAS disengagements — days 10, 14, 21
    S5: City vs highway difference — natural model output
    S6: Tire pressure drift (optional) — day 10+
    S7: Missing data dropout (optional) — day 15

S1 and S2 overlap from day 18 onward (interacting-causes case per D9).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class GroundTruthEvent:
    """A labelled ground-truth event for evaluation."""

    id: str
    scenario: str
    ts_start: int  # epoch ms
    ts_end: int  # epoch ms
    cause: str | list[str]
    signals: list[str]
    expected_facts: list[str]
    event_type: str | None = None  # maps to events.type if applicable
    severity: str = "info"
    extra: dict[str, Any] = field(default_factory=dict)


class ScenarioManager:
    """Manages all scenario injections across the simulation."""

    def __init__(self, base_epoch_ms: int, enable_s6: bool = True,
                 enable_s7: bool = True) -> None:
        self.base_epoch_ms = base_epoch_ms
        self.enable_s6 = enable_s6
        self.enable_s7 = enable_s7
        self.ground_truth: list[GroundTruthEvent] = []
        self._ota_applied = False
        self._s3_triggered = False
        self._s7_dropout_active = False

    def day_to_epoch(self, day: int, hour: float = 0.0) -> int:
        """Convert day index + hour to epoch milliseconds."""
        return self.base_epoch_ms + int((day * 24 + hour) * 3600 * 1000)

    # ── S1: Ambient temperature cooling trend ──

    def get_ambient_temp(self, day: int, hour: float,
                         base_temp: float, daily_amplitude: float,
                         cooling_rate: float) -> float:
        """Compute ambient temperature for a given time.

        Includes daily cycle + gradual cooling trend starting day 7.
        """
        # Daily sinusoidal cycle: coldest at ~5 AM, warmest at ~15 PM
        import math
        daily = daily_amplitude * math.sin(2 * math.pi * (hour - 5) / 24)

        # S1: gradual cooling trend from day 7 onward
        if day >= 7:
            trend = -cooling_rate * (day - 7)
        else:
            trend = 0.0

        return base_temp + daily + trend

    def get_s1_ground_truth(self, s1_start_day: int = 7,
                            computed_metrics: dict[str, Any] | None = None) -> GroundTruthEvent:
        """Generate S1 ground truth entry with computed facts for named windows."""
        if computed_metrics:
            drop_pct = computed_metrics.get("s1_drop_pct", 12.3)
            base_w = computed_metrics.get("base_window", "days 1-5")
            s1_w = computed_metrics.get("s1_window", "days 14-17")
            base_r = computed_metrics.get("base_range_km", 659.7)
            s1_r = computed_metrics.get("s1_range_km", 578.5)
            expected_facts = [
                f"range_per_charge fell {drop_pct:.1f}% across S1 window ({s1_w} vs baseline {base_w})",
                "HVAC heating power increased due to ambient temperature cooling",
                f"baseline range: {base_r:.1f} km, S1 range: {s1_r:.1f} km",
            ]
            extra = {
                "measured_drop_pct": round(drop_pct, 2),
                "base_window": base_w,
                "s1_window": s1_w,
                "baseline_range_km": base_r,
                "s1_range_km": s1_r,
            }
        else:
            expected_facts = [
                "range_per_charge fell 10-15%",
                "HVAC/temperature contribution ~50-60%",
                "ambient temperature mean dropped",
            ]
            extra = {"measured_drop_pct": 12.3}

        return GroundTruthEvent(
            id="S1",
            scenario="Range reduction over ~2 weeks",
            ts_start=self.day_to_epoch(s1_start_day),
            ts_end=self.day_to_epoch(28),
            cause="ambient_temp_drop + hvac_increase",
            signals=["ambient_temp", "hvac_power", "energy_per_km", "range_per_charge"],
            expected_facts=expected_facts,
            extra=extra,
        )

    # ── S2: OTA update efficiency regression ──

    def get_efficiency_penalty(self, day: int, ota_day: int,
                               penalty_pct: float) -> float:
        """Return efficiency penalty fraction (0.0 before OTA, penalty after)."""
        if day >= ota_day:
            if not self._ota_applied:
                self._ota_applied = True
            return penalty_pct / 100.0
        return 0.0

    def get_s2_ground_truth(self, ota_day: int = 18) -> GroundTruthEvent:
        return GroundTruthEvent(
            id="S2",
            scenario="Efficiency regression after software update",
            ts_start=self.day_to_epoch(ota_day),
            ts_end=self.day_to_epoch(28),
            cause="ota_update_efficiency_regression",
            signals=["energy_per_km", "range_per_charge"],
            expected_facts=[
                "energy_per_km step change on OTA update date",
                "efficiency worsened ~8% post-update",
            ],
            event_type="ota_update",
        )

    def get_s1_s2_overlap_ground_truth(self, ota_day: int = 18,
                                       computed_metrics: dict[str, Any] | None = None) -> GroundTruthEvent:
        """S1/S2 interacting-causes entry for the overlap window."""
        if computed_metrics:
            comb_drop = computed_metrics.get("combined_drop_pct", 38.5)
            hvac_share = computed_metrics.get("hvac_share_pct", 56.1)
            ota_share = computed_metrics.get("ota_share_pct", 26.3)
            other_share = computed_metrics.get("other_share_pct", 17.6)
            overlap_w = computed_metrics.get("overlap_window", "days 24-28")
            expected_facts = [
                f"range_per_charge fell {comb_drop:.1f}% (combined S1+S2 window {overlap_w} vs baseline)",
                f"HVAC/temperature contribution: {hvac_share:.1f}%",
                f"OTA update efficiency regression contribution: {ota_share:.1f}%",
                f"unexplained physical remainder (air density, tire RR, battery efficiency): {other_share:.1f}%",
            ]
            extra = {
                "combined_drop_pct": round(comb_drop, 2),
                "hvac_share_pct": round(hvac_share, 2),
                "ota_share_pct": round(ota_share, 2),
                "remainder_share_pct": round(other_share, 2),
                "overlap_window": overlap_w,
            }
        else:
            expected_facts = [
                "range_per_charge fell ~35-40% (combined)",
                "HVAC/temperature contribution ~50-60%",
                "OTA update contribution ~25-30%",
                "remainder unexplained ~15-20%",
            ]
            extra = {"combined_drop_pct": 38.5}

        return GroundTruthEvent(
            id="S1_S2_overlap",
            scenario="Range reduction — interacting causes (temperature + OTA)",
            ts_start=self.day_to_epoch(ota_day),
            ts_end=self.day_to_epoch(28),
            cause=["ambient_temp_drop + hvac_increase",
                    "ota_update_efficiency_regression"],
            signals=["ambient_temp", "hvac_power", "energy_per_km", "range_per_charge"],
            expected_facts=expected_facts,
            extra=extra,
        )

    # ── S3: Battery overheating ──

    def get_pump_duty_override(self, day: int, hour: float,
                                s3_day: int, degradation_minutes: int,
                                ) -> float | None:
        """Return pump duty override for S3 scenario.

        Ramps pump duty from normal (50%) down to 10% over degradation_minutes,
        then back to normal after the event. Returns None outside the window.
        """
        if day != s3_day:
            return None

        # S3 event starts at 7.6 (during morning commute driving)
        event_start_h = 7.6
        event_end_h = event_start_h + degradation_minutes / 60.0

        if event_start_h <= hour <= event_end_h:
            # Linear ramp down
            progress = (hour - event_start_h) / (event_end_h - event_start_h)
            return max(10.0, 50.0 - 40.0 * progress)
        elif event_end_h < hour < event_end_h + 0.5:
            # Recovery
            return None  # model takes over
        return None

    def get_s3_ground_truth(self, s3_day: int = 22,
                            degradation_min: int = 10) -> GroundTruthEvent:
        event_start_h = 7.6
        event_end_h = event_start_h + degradation_min / 60.0
        return GroundTruthEvent(
            id="S3",
            scenario="Battery overheating warning",
            ts_start=self.day_to_epoch(s3_day, event_start_h),
            ts_end=self.day_to_epoch(s3_day, event_end_h + 0.5),
            cause="coolant_pump_degradation",
            signals=["coolant_pump_duty", "pack_temp", "coolant_temp"],
            expected_facts=[
                "coolant pump duty dropped before temperature rise",
                "pack temperature exceeded threshold",
                "DTC P0A7E set",
            ],
            event_type="battery_overtemp_warning",
            severity="critical",
        )

    # ── S4: ADAS disengagements ──

    DISENGAGEMENT_REASONS = [
        (1, "low_lane_marking_confidence"),
        (2, "driver_override"),
        (3, "sensor_occlusion"),
        (4, "speed_out_of_range"),
        (5, "system_fault"),
    ]

    def get_s4_events(self, rng: Any, event_days: tuple[int, ...],
                       ) -> list[dict[str, Any]]:
        """Generate ADAS disengagement events for given days.

        Returns list of dicts with keys: day, hour, reason_code, reason_text.
        """
        events = []
        for day in event_days:
            # 1-3 events per day
            n = rng.integers(1, 4)
            for _ in range(n):
                hour = float(rng.uniform(8.0, 18.0))
                reason_idx = int(rng.integers(0, len(self.DISENGAGEMENT_REASONS)))
                code, text = self.DISENGAGEMENT_REASONS[reason_idx]
                events.append({
                    "day": day,
                    "hour": hour,
                    "reason_code": code,
                    "reason_text": text,
                })
        return events

    def get_s4_ground_truth(self, event_days: tuple[int, ...],
                            events: list[dict[str, Any]]) -> GroundTruthEvent:
        return GroundTruthEvent(
            id="S4",
            scenario="ADAS disengagements",
            ts_start=self.day_to_epoch(min(event_days)),
            ts_end=self.day_to_epoch(max(event_days), 23.99),
            cause="various_adas_triggers",
            signals=["adas_state", "disengagement_reason"],
            expected_facts=[
                f"Total {len(events)} disengagement events",
                f"Events on days {list(event_days)}",
            ],
            event_type="adas_disengagement",
            extra={"event_count": len(events), "days": list(event_days)},
        )

    # ── S5: City vs highway (natural) ──

    def get_s5_ground_truth(self) -> GroundTruthEvent:
        return GroundTruthEvent(
            id="S5",
            scenario="City vs highway energy difference",
            ts_start=self.day_to_epoch(0),
            ts_end=self.day_to_epoch(28),
            cause="physics_model_road_type_difference",
            signals=["energy_per_km", "road_type"],
            expected_facts=[
                "city energy_per_km ~30-40% higher than highway",
                "difference consistent with aero vs stop-start physics",
            ],
        )

    # ── S6: Tire pressure drift (optional) ──

    def get_tire_pressure_fl(self, day: int, nominal: float,
                              start_day: int, leak_rate: float) -> float:
        """Return front-left tire pressure with slow leak."""
        if not self.enable_s6 or day < start_day:
            return nominal
        days_leaking = day - start_day
        return max(1.5, nominal - leak_rate * days_leaking)

    def get_s6_ground_truth(self, start_day: int = 10,
                            leak_rate: float = 0.05) -> GroundTruthEvent:
        return GroundTruthEvent(
            id="S6",
            scenario="Tire pressure drift (front-left)",
            ts_start=self.day_to_epoch(start_day),
            ts_end=self.day_to_epoch(28),
            cause="slow_tire_leak_fl",
            signals=["tire_pressure_fl", "energy_per_km"],
            expected_facts=[
                f"tire_pressure_fl dropped {leak_rate} bar/day from day {start_day}",
                "small contribution to efficiency decline",
            ],
        )

    # ── S7: Data dropout (optional) ──

    def is_dropout_active(self, day: int, hour: float,
                          dropout_day: int, dropout_hours: float) -> bool:
        """Check if signal dropout is active."""
        if not self.enable_s7 or day != dropout_day:
            return False
        # Dropout from 10:00 for dropout_hours
        dropout_start = 10.0
        return dropout_start <= hour < dropout_start + dropout_hours

    def get_s7_ground_truth(self, dropout_day: int = 15,
                            dropout_hours: float = 2.0) -> GroundTruthEvent:
        return GroundTruthEvent(
            id="S7",
            scenario="Signal dropout window",
            ts_start=self.day_to_epoch(dropout_day, 10.0),
            ts_end=self.day_to_epoch(dropout_day, 10.0 + dropout_hours),
            cause="source_outage",
            signals=["soc", "pack_temp"],
            expected_facts=[
                "data gap reported for soc and pack_temp",
                "no guessing during gap",
            ],
        )

    # ── Decoy events ──

    def get_decoy_events(self, rng: Any) -> list[dict[str, Any]]:
        """Generate benign decoy events (false-positive tests)."""
        decoys = []
        # One-off hard brake on day 5
        decoys.append({
            "type": "hard_braking",
            "day": 5,
            "hour": float(rng.uniform(8.0, 17.0)),
            "severity": "info",
            "payload": {"decel_g": round(float(rng.uniform(0.6, 0.9)), 2)},
        })
        # Brief service warning on day 12 that clears
        decoys.append({
            "type": "service_warning",
            "day": 12,
            "hour": float(rng.uniform(9.0, 16.0)),
            "severity": "warning",
            "payload": {"message": "Check tire pressure system", "cleared": True},
        })
        return decoys

    # ── Build full ground truth ──

    def build_ground_truth(self, cfg: Any, s4_events: list[dict[str, Any]],
                           computed_metrics: dict[str, Any] | None = None,
                           ) -> list[dict[str, Any]]:
        """Build the complete ground_truth.json content."""
        entries: list[GroundTruthEvent] = [
            self.get_s1_ground_truth(computed_metrics=computed_metrics),
            self.get_s2_ground_truth(cfg.ota_update_day),
            self.get_s1_s2_overlap_ground_truth(cfg.ota_update_day, computed_metrics=computed_metrics),
            self.get_s3_ground_truth(cfg.s3_event_day, cfg.s3_pump_degradation_minutes),
            self.get_s4_ground_truth(cfg.s4_event_days, s4_events),
            self.get_s5_ground_truth(),
        ]
        if self.enable_s6:
            entries.append(self.get_s6_ground_truth(
                cfg.s6_start_day, cfg.s6_leak_rate_bar_per_day))
        if self.enable_s7:
            entries.append(self.get_s7_ground_truth(
                cfg.s7_dropout_day, cfg.s7_dropout_hours))

        return [
            {
                "id": e.id,
                "scenario": e.scenario,
                "ts_start": e.ts_start,
                "ts_end": e.ts_end,
                "cause": e.cause,
                "signals": e.signals,
                "expected_facts": e.expected_facts,
                **({"event_type": e.event_type} if e.event_type else {}),
                **({"severity": e.severity} if e.severity != "info" else {}),
                **({"extra": e.extra} if e.extra else {}),
            }
            for e in entries
        ]

    def write_ground_truth(self, path: Path, cfg: Any,
                           s4_events: list[dict[str, Any]],
                           computed_metrics: dict[str, Any] | None = None) -> None:
        """Write ground_truth.json to disk."""
        data = self.build_ground_truth(cfg, s4_events, computed_metrics=computed_metrics)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
