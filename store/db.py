"""SQLite database access layer.

Initialises the schema from docs/schema.sql, loads the signal catalog,
and provides bulk-insert helpers for the simulator.
"""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Sequence


def init_db(db_path: Path, schema_path: Path) -> sqlite3.Connection:
    """Create and initialise the database from the contract schema.

    Args:
        db_path: Path for the SQLite database file.
        schema_path: Path to docs/schema.sql.

    Returns:
        Open connection with WAL mode and foreign keys enabled.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    schema_sql = schema_path.read_text(encoding="utf-8")
    conn.executescript(schema_sql)
    conn.commit()
    return conn


def load_signal_catalog(conn: sqlite3.Connection, catalog_path: Path) -> None:
    """Populate signal_catalog table from CSV."""
    with open(catalog_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            conn.execute(
                "INSERT OR IGNORE INTO signal_catalog "
                "(signal, unit, source, description, aliases) VALUES (?, ?, ?, ?, ?)",
                (row["signal"], row["unit"], row["source"],
                 row["description"], row["aliases"]),
            )
    conn.commit()


def seed_dtc_knowledge(conn: sqlite3.Connection) -> None:
    """Insert hand-curated DTC knowledge entries.

    These are NOT LLM-generated — each entry is hand-written with
    real OBD-II / manufacturer-specific codes relevant to EVs.
    """
    dtcs: list[tuple[str, str, str]] = [
        # Battery / HV system
        ("P0A7E", "Battery pack overtemperature",
         '["coolant_pump_failure","high_ambient_temp","high_current_draw","blocked_coolant_line"]'),
        ("P0A80", "Replace energy storage assembly",
         '["battery_degradation","cell_imbalance","deep_discharge_damage"]'),
        ("P0A7F", "Battery pack overvoltage",
         '["charger_fault","bms_calibration_error"]'),
        ("P0A09", "DC/DC converter status circuit",
         '["dc_dc_converter_fault","12v_battery_issue"]'),
        ("P0A1F", "Drive motor A inverter overtemperature",
         '["sustained_high_power","coolant_system_issue","ambient_heat"]'),
        # Cooling system
        ("P0480", "Cooling fan relay circuit",
         '["relay_failure","wiring_fault","fuse_blown"]'),
        ("P0481", "Cooling fan 2 control circuit",
         '["relay_failure","control_module_fault"]'),
        ("P0A3F", "Drive motor A position sensor circuit range/performance",
         '["sensor_degradation","connector_corrosion"]'),
        ("P0A78", "Drive motor A inverter low voltage",
         '["12v_supply_issue","dc_dc_converter_fault"]'),
        # Charging
        ("P0A94", "DC/DC converter performance",
         '["converter_degradation","input_voltage_issue"]'),
        ("P0AF0", "Battery high voltage system interlock circuit",
         '["connector_issue","service_disconnect_loose"]'),
        ("P0A08", "DC/DC converter interlock circuit",
         '["safety_interlock_open","maintenance_mode"]'),
        # Motor / drivetrain
        ("P0A0D", "Drive motor A temperature sensor circuit",
         '["sensor_fault","wiring_open_circuit"]'),
        ("P0A0F", "Drive motor B temperature sensor circuit",
         '["sensor_fault","wiring_open_circuit"]'),
        ("P0A25", "Drive motor B power inverter insulation test failure",
         '["insulation_breakdown","moisture_ingress"]'),
        # ADAS
        ("U0100", "Lost communication with ECM/PCM",
         '["can_bus_fault","ecu_failure","wiring_harness_damage"]'),
        ("U0140", "Lost communication with body control module",
         '["bcm_fault","can_network_error"]'),
        ("U0155", "Lost communication with instrument panel cluster",
         '["ipc_fault","can_bus_error"]'),
        ("C0035", "Left front wheel speed sensor circuit",
         '["sensor_fault","wiring_damage","wheel_bearing"]'),
        ("C0040", "Right front wheel speed sensor circuit",
         '["sensor_fault","wiring_damage","wheel_bearing"]'),
        # Tire pressure
        ("C0750", "Tire pressure monitoring system sensor",
         '["tpms_sensor_battery","sensor_not_learned","rf_interference"]'),
        ("C0755", "Tire pressure not monitored",
         '["tpms_receiver_fault","all_sensors_lost"]'),
        # General
        ("P0562", "System voltage low",
         '["12v_battery_weak","alternator_issue","parasitic_drain"]'),
        ("P0563", "System voltage high",
         '["voltage_regulator_fault","dc_dc_overvoltage"]'),
        ("P0602", "Control module programming error",
         '["ota_update_incomplete","flash_corruption"]'),
        ("P0606", "ECM/PCM processor fault",
         '["ecu_hardware_failure","overheating"]'),
        ("P0A06", "Drive motor A temperature too high",
         '["sustained_high_power","coolant_issue","ambient_conditions"]'),
        ("P2195", "O2 sensor signal biased lean",
         '["not_applicable_ev","legacy_code"]'),
        ("B1318", "Battery voltage low",
         '["12v_battery_discharge","parasitic_drain"]'),
        ("B1325", "Memory power supply failure",
         '["ecu_power_loss","connector_fault"]'),
    ]

    for code, desc, causes in dtcs:
        conn.execute(
            "INSERT OR IGNORE INTO dtc_knowledge (code, description, related_causes) "
            "VALUES (?, ?, ?)",
            (code, desc, causes),
        )
    conn.commit()


def bulk_insert_signals(conn: sqlite3.Connection,
                        rows: Sequence[tuple[int, str, str, float, str]],
                        ) -> None:
    """Insert rows into the signals table (1 Hz data).

    Each row: (ts, source, signal, value, unit).
    """
    conn.executemany(
        "INSERT INTO signals (ts, source, signal, value, unit) VALUES (?, ?, ?, ?, ?)",
        rows,
    )


def bulk_insert_signals_1s(conn: sqlite3.Connection,
                           rows: Sequence[tuple[int, str, float, float, float, int]],
                           ) -> None:
    """Insert rows into signals_1s aggregate table.

    Each row: (ts, signal, avg, min, max, n).
    """
    conn.executemany(
        "INSERT OR REPLACE INTO signals_1s (ts, signal, avg, min, max, n) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )


def bulk_insert_signals_1m(conn: sqlite3.Connection,
                           rows: Sequence[tuple[int, str, float, float, float, int]],
                           ) -> None:
    """Insert rows into signals_1m aggregate table."""
    conn.executemany(
        "INSERT OR REPLACE INTO signals_1m (ts, signal, avg, min, max, n) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )


def insert_trip(conn: sqlite3.Connection,
                ts_start: int, ts_end: int,
                distance_km: float, energy_kwh: float,
                avg_speed: float, city_share: float, highway_share: float,
                avg_ambient_c: float, hvac_energy_kwh: float,
                ) -> int:
    """Insert a trip record and return its ID."""
    cur = conn.execute(
        "INSERT INTO trips "
        "(ts_start, ts_end, distance_km, energy_kwh, fuel_l, "
        " avg_speed_kph, city_share, highway_share, avg_ambient_c, hvac_energy_kwh) "
        "VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)",
        (ts_start, ts_end, distance_km, energy_kwh,
         avg_speed, city_share, highway_share, avg_ambient_c, hvac_energy_kwh),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_event(conn: sqlite3.Connection,
                 ts_start: int, ts_end: int | None,
                 event_type: str, source: str,
                 severity: str = "info",
                 trip_id: int | None = None,
                 payload: dict[str, Any] | None = None,
                 ) -> int:
    """Insert an event and return its ID."""
    cur = conn.execute(
        "INSERT INTO events (ts_start, ts_end, type, source, severity, trip_id, payload) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts_start, ts_end, event_type, source, severity, trip_id,
         json.dumps(payload) if payload else None),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_dtc(conn: sqlite3.Connection,
               ts: int, ecu: str, code: str,
               status: str = "confirmed",
               description: str | None = None) -> int:
    """Insert a DTC record and return its ID."""
    cur = conn.execute(
        "INSERT INTO dtcs (ts, ecu, code, status, description) VALUES (?, ?, ?, ?, ?)",
        (ts, ecu, code, status, description),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_event_snapshot(conn: sqlite3.Connection,
                          rows: Sequence[tuple[int, int, str, float]],
                          ) -> None:
    """Insert full-rate event snapshot rows.

    Each row: (event_id, ts, signal, value).
    """
    conn.executemany(
        "INSERT OR REPLACE INTO event_snapshots (event_id, ts, signal, value) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )


def insert_digest_daily(conn: sqlite3.Connection,
                        day: str, metric: str, value: float,
                        n_trips: int) -> None:
    """Insert or replace a daily digest metric."""
    conn.execute(
        "INSERT OR REPLACE INTO digest_daily (day, metric, value, n_trips) "
        "VALUES (?, ?, ?, ?)",
        (day, metric, value, n_trips),
    )


def get_db_size_bytes(db_path: Path) -> int:
    """Return the file size of the database."""
    return db_path.stat().st_size if db_path.exists() else 0
