from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _get_tz(tz_name: str) -> Any:
    """Return timezone object with graceful fallback if system tz database is missing."""
    try:
        return ZoneInfo(tz_name)
    except Exception:
        from datetime import timezone as dt_timezone
        if tz_name == "Asia/Kolkata":
            return dt_timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
        return dt_timezone.utc


@dataclass(frozen=True)
class SimConfig:
    """Immutable configuration for a simulation run."""

    seed: int = 42
    days: int = 28
    out_db: Path = Path("data/vehicle.db")
    candump_dir: Path = Path("data/candump")
    ground_truth_path: Path = Path("eval/ground_truth.json")

    # Vehicle clock & timezone
    timezone: str = "Asia/Kolkata"
    reference_now: datetime | None = None

    def get_reference_now(self) -> datetime:
        """Return the anchor 'reference now' as a timezone-aware datetime in the vehicle timezone."""
        tz = _get_tz(self.timezone)
        if self.reference_now is not None:
            if self.reference_now.tzinfo is None:
                return self.reference_now.replace(tzinfo=tz)
            return self.reference_now.astimezone(tz)
        # Default reference now: end of Day 28 (2026-10-28 23:59:59) in vehicle timezone
        return datetime(2026, 10, 28, 23, 59, 59, tzinfo=tz)

    def get_base_datetime(self, days: int = 28) -> datetime:
        """Return start datetime (Day 0 00:00:00) so history ends at reference_now."""
        ref_now = self.get_reference_now()
        tz = _get_tz(self.timezone)
        start_date = ref_now.date() - timedelta(days=days - 1)
        return datetime.combine(start_date, datetime.min.time(), tzinfo=tz)

    def get_vehicle_date(self, ts_ms: int) -> str:
        """Format an epoch ms timestamp as a YYYY-MM-DD date in the vehicle timezone."""
        dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=_get_tz(self.timezone))
        return dt.strftime("%Y-%m-%d")

    def get_yesterday_date(self) -> str:
        """Return 'yesterday' date string relative to reference now in vehicle timezone."""
        ref = self.get_reference_now()
        yesterday = ref.date() - timedelta(days=1)
        return yesterday.strftime("%Y-%m-%d")

    def get_today_date(self) -> str:
        """Return 'today' date string for reference now in vehicle timezone."""
        ref = self.get_reference_now()
        return ref.date().strftime("%Y-%m-%d")

    # DBC / catalog paths
    dbc_path: Path = Path("docs/signals.dbc")
    catalog_path: Path = Path("docs/signal_catalog.csv")
    schema_path: Path = Path("docs/schema.sql")

    # Vehicle parameters
    vehicle_mass_kg: float = 1800.0
    battery_capacity_kwh: float = 60.0
    frontal_area_m2: float = 2.3
    drag_coeff: float = 0.28
    rolling_resistance: float = 0.012
    motor_efficiency: float = 0.92
    regen_efficiency: float = 0.70
    aux_base_power_kw: float = 0.3

    # HVAC parameters
    hvac_heat_coeff: float = 0.15  # kW per degree delta (heating)
    hvac_cool_coeff: float = 0.08  # kW per degree delta (cooling)
    cabin_target_temp_c: float = 22.0

    # Battery thermal
    pack_thermal_mass: float = 50.0  # kJ/K
    coolant_flow_coeff: float = 0.05  # kW/K at full pump duty
    pack_heat_gen_coeff: float = 0.002  # kW per A^2 (I²R)
    pack_overtemp_threshold_c: float = 45.0

    # Tire
    tire_nominal_pressure_bar: float = 2.50

    # Timing
    sim_step_s: float = 1.0  # raw signal generation step
    native_hz: int = 10  # full-rate signal frequency for event snapshots
    event_snapshot_window_s: int = 60  # +/- seconds around events

    # CAN bus config
    bus_type: str = "virtual"  # virtual | udp_multicast | socketcan
    bus_channel: str = "vcan0"

    # Ambient temperature model
    ambient_base_c: float = 20.0  # day-1 mean temperature
    ambient_daily_amplitude_c: float = 5.0
    ambient_cooling_rate_c_per_day: float = 0.5  # S1 scenario trend

    # Scenario switches
    enable_s6_tire_leak: bool = True
    enable_s7_data_dropout: bool = True

    # Charging
    charge_power_kw: float = 7.4
    charge_efficiency: float = 0.95
    charge_start_soc: float = 0.20  # start charging below this
    charge_stop_soc: float = 0.95

    # Drive cycle
    weekday_trips: int = 2
    commute_distance_km: float = 15.0
    weekend_long_trip_prob: float = 0.25
    weekend_long_distance_km: float = 80.0

    # S2 OTA scenario
    ota_update_day: int = 18
    ota_efficiency_penalty_pct: float = 8.0

    # S3 Battery overheating
    s3_event_day: int = 22
    s3_pump_degradation_minutes: int = 10

    # S4 ADAS disengagements
    s4_event_days: tuple[int, ...] = (10, 14, 21)

    # S6 Tire leak
    s6_start_day: int = 10
    s6_leak_rate_bar_per_day: float = 0.05

    # S7 Data dropout
    s7_dropout_day: int = 15
    s7_dropout_hours: float = 2.0
