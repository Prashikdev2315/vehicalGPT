"""Physics-style EV vehicle model with causal signal linkage.

All values are quantised to DBC resolution before output (D7).
The model is deterministic: same seed + config = identical output.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from sim.config import SimConfig


# Physical constants
AIR_DENSITY = 1.225  # kg/m³
GRAVITY = 9.81  # m/s²


@dataclass
class VehicleState:
    """Mutable snapshot of all vehicle signals at one instant."""

    # Motion
    vehicle_speed: float = 0.0  # km/h
    accel_long: float = 0.0  # m/s²
    accel_lat: float = 0.0  # m/s²
    brake_pressure: float = 0.0  # bar
    throttle_position: float = 0.0  # %
    steering_angle: float = 0.0  # deg

    # Battery / powertrain
    soc: float = 0.90  # 0..1 fraction (stored as % in DB)
    pack_voltage: float = 350.0  # V
    pack_current: float = 0.0  # A (positive = discharge)
    pack_temp: float = 25.0  # °C
    coolant_temp: float = 25.0  # °C
    coolant_pump_duty: float = 50.0  # %
    motor_power: float = 0.0  # kW
    regen_power: float = 0.0  # kW

    # Energy / range
    energy_per_km: float = 150.0  # Wh/km
    range_estimate: float = 300.0  # km

    # Climate
    ambient_temp: float = 20.0  # °C
    cabin_temp: float = 22.0  # °C
    hvac_power: float = 0.0  # kW
    hvac_mode: int = 0  # 0=off, 1=heat, 2=cool, 3=auto
    cabin_target_temp: float = 22.0  # °C

    # Chassis
    tire_pressure_fl: float = 2.50  # bar
    tire_pressure_fr: float = 2.50
    tire_pressure_rl: float = 2.50
    tire_pressure_rr: float = 2.50
    odometer: float = 10000.0  # km

    # ADAS
    adas_state: int = 0  # 0=off, 1=standby, 2=active, 3=override
    lane_keep_active: int = 0
    acc_active: int = 0
    disengagement_reason: int = 0

    # Charging
    charger_connected: int = 0
    charge_power: float = 0.0  # kW
    charge_voltage: float = 0.0  # V
    charge_current: float = 0.0  # A

    # Aux / derived
    aux_power: float = 0.3  # kW
    dc_dc_power: float = 0.1  # kW
    road_type: int = 0  # 0=city, 1=highway, 2=mixed
    zone_id: int = 1

    # Heartbeat
    ecu_heartbeat: int = 0

    # Internal accumulators (not CAN signals)
    _trip_energy_wh: float = 0.0
    _trip_distance_km: float = 0.0
    _energy_history: list[float] = field(default_factory=list)

    def as_signal_dict(self) -> dict[str, float]:
        """Return all CAN-visible signals as {name: value}."""
        return {
            "vehicle_speed": self.vehicle_speed,
            "accel_long": self.accel_long,
            "accel_lat": self.accel_lat,
            "brake_pressure": self.brake_pressure,
            "throttle_position": self.throttle_position,
            "steering_angle": self.steering_angle,
            "soc": self.soc * 100.0,  # fraction -> %
            "pack_voltage": self.pack_voltage,
            "pack_current": self.pack_current,
            "pack_temp": self.pack_temp,
            "coolant_temp": self.coolant_temp,
            "coolant_pump_duty": self.coolant_pump_duty,
            "motor_power": self.motor_power,
            "regen_power": self.regen_power,
            "energy_per_km": self.energy_per_km,
            "range_estimate": self.range_estimate,
            "ambient_temp": self.ambient_temp,
            "cabin_temp": self.cabin_temp,
            "hvac_power": self.hvac_power,
            "hvac_mode": float(self.hvac_mode),
            "cabin_target_temp": self.cabin_target_temp,
            "tire_pressure_fl": self.tire_pressure_fl,
            "tire_pressure_fr": self.tire_pressure_fr,
            "tire_pressure_rl": self.tire_pressure_rl,
            "tire_pressure_rr": self.tire_pressure_rr,
            "odometer": self.odometer,
            "adas_state": float(self.adas_state),
            "lane_keep_active": float(self.lane_keep_active),
            "acc_active": float(self.acc_active),
            "disengagement_reason": float(self.disengagement_reason),
            "charger_connected": float(self.charger_connected),
            "charge_power": self.charge_power,
            "charge_voltage": self.charge_voltage,
            "charge_current": self.charge_current,
            "aux_power": self.aux_power,
            "dc_dc_power": self.dc_dc_power,
            "road_type": float(self.road_type),
            "zone_id": float(self.zone_id),
            "ecu_heartbeat": float(self.ecu_heartbeat),
        }


class VehicleModel:
    """Deterministic physics-style EV model.

    Causal chain:
        ambient_temp → HVAC load → total aux power
        speed profile → aero + rolling → motor power
        motor power + aux power → pack current → SOC drain
        pack current → I²R heating → pack temp
        coolant pump duty → cooling rate → pack temp
        SOC + energy_per_km → range estimate
    """

    def __init__(self, cfg: SimConfig) -> None:
        self.cfg = cfg
        self.state = VehicleState(
            ambient_temp=cfg.ambient_base_c,
            cabin_temp=cfg.cabin_target_temp_c,
            cabin_target_temp=cfg.cabin_target_temp_c,
            tire_pressure_fl=cfg.tire_nominal_pressure_bar,
            tire_pressure_fr=cfg.tire_nominal_pressure_bar,
            tire_pressure_rl=cfg.tire_nominal_pressure_bar,
            tire_pressure_rr=cfg.tire_nominal_pressure_bar,
        )

    def step(self, dt_s: float, target_speed_kmh: float, road_type: int,
             efficiency_penalty: float = 0.0,
             pump_duty_override: float | None = None) -> VehicleState:
        """Advance the model by dt_s seconds.

        Args:
            dt_s: Time step in seconds.
            target_speed_kmh: Desired speed from drive cycle.
            road_type: 0=city, 1=highway, 2=mixed.
            efficiency_penalty: Fractional penalty (0.08 = 8% worse).
            pump_duty_override: If set, force coolant pump duty (S3 scenario).

        Returns:
            Updated VehicleState (same object, mutated in place).
        """
        s = self.state
        cfg = self.cfg

        # ── Speed transition ──
        prev_speed_ms = s.vehicle_speed / 3.6
        target_speed_ms = target_speed_kmh / 3.6
        # Simple first-order response toward target speed
        max_accel = 3.0  # m/s²
        max_decel = -5.0  # m/s²
        speed_error = target_speed_ms - prev_speed_ms
        accel = max(max_decel, min(max_accel, speed_error / max(dt_s, 0.1)))
        new_speed_ms = max(0.0, prev_speed_ms + accel * dt_s)
        s.vehicle_speed = new_speed_ms * 3.6
        s.accel_long = accel
        s.road_type = road_type

        # Throttle / brake
        if accel > 0.1:
            s.throttle_position = min(100.0, accel / max_accel * 100.0)
            s.brake_pressure = 0.0
        elif accel < -0.1:
            s.throttle_position = 0.0
            s.brake_pressure = min(150.0, abs(accel) / abs(max_decel) * 150.0)
        else:
            s.throttle_position = max(5.0, s.vehicle_speed / 130.0 * 30.0)
            s.brake_pressure = 0.0

        # ── Energy model ──
        v = new_speed_ms
        if v > 0.5:
            # Rolling resistance force
            f_roll = cfg.rolling_resistance * cfg.vehicle_mass_kg * GRAVITY
            # Aerodynamic drag
            f_aero = 0.5 * AIR_DENSITY * cfg.drag_coeff * cfg.frontal_area_m2 * v * v
            # Traction power at the wheel (kW)
            p_traction_kw = (f_roll + f_aero) * v / 1000.0

            # Temperature-dependent efficiency loss
            temp_factor = 1.0
            if s.ambient_temp < 10.0:
                temp_factor = 1.0 + 0.005 * (10.0 - s.ambient_temp)

            # Apply OTA efficiency penalty (S2)
            penalty_factor = 1.0 + efficiency_penalty

            p_traction_kw *= temp_factor * penalty_factor

            # Regen during braking
            if accel < -0.3:
                regen_kw = min(
                    abs(accel) * cfg.vehicle_mass_kg * v / 1000.0 * cfg.regen_efficiency,
                    60.0,  # max regen power
                )
                s.regen_power = regen_kw
            else:
                s.regen_power = 0.0

            motor_kw = p_traction_kw / cfg.motor_efficiency
            s.motor_power = motor_kw

            # Energy per km (Wh/km)
            total_power_kw = motor_kw + s.hvac_power + s.aux_power + s.dc_dc_power
            net_power_kw = total_power_kw - s.regen_power
            if v > 0.5:
                e_per_km = net_power_kw * 1000.0 / (v * 3.6)  # Wh/km
                s.energy_per_km = max(0.0, e_per_km)
            else:
                s.energy_per_km = 0.0

            # Update accumulators
            distance_km = v * dt_s / 1000.0
            energy_wh = net_power_kw * 1000.0 * dt_s / 3600.0
            s._trip_energy_wh += energy_wh
            s._trip_distance_km += distance_km
            s.odometer += distance_km
        else:
            s.motor_power = 0.0
            s.regen_power = 0.0
            # Stationary: only aux power draws
            energy_wh = (s.hvac_power + s.aux_power + s.dc_dc_power) * 1000.0 * dt_s / 3600.0

        # ── Battery SOC ──
        net_energy_wh = energy_wh - s.regen_power * 1000.0 * dt_s / 3600.0
        capacity_wh = cfg.battery_capacity_kwh * 1000.0
        s.soc = max(0.0, min(1.0, s.soc - net_energy_wh / capacity_wh))

        # Pack voltage (simplified: linear with SOC)
        s.pack_voltage = 300.0 + s.soc * 100.0  # 300-400V range
        if s.pack_voltage > 0:
            s.pack_current = (energy_wh * 3600.0 / dt_s) / s.pack_voltage if dt_s > 0 else 0.0
        else:
            s.pack_current = 0.0

        # ── HVAC model ──
        delta_t = s.cabin_target_temp - s.ambient_temp
        if delta_t > 1.0:
            s.hvac_mode = 1  # heat
            s.hvac_power = cfg.hvac_heat_coeff * delta_t
        elif delta_t < -1.0:
            s.hvac_mode = 2  # cool
            s.hvac_power = cfg.hvac_cool_coeff * abs(delta_t)
        else:
            s.hvac_mode = 0
            s.hvac_power = 0.0

        # Cabin temperature slowly approaches target
        s.cabin_temp += (s.cabin_target_temp - s.cabin_temp) * 0.01 * dt_s

        # ── Battery thermal model ──
        if pump_duty_override is not None:
            s.coolant_pump_duty = pump_duty_override
        else:
            # Normal: pump duty proportional to pack temp
            if s.pack_temp > 30.0:
                s.coolant_pump_duty = min(100.0, 50.0 + (s.pack_temp - 30.0) * 5.0)
            else:
                s.coolant_pump_duty = 50.0

        # Heat generation from I²R
        heat_gen_kw = cfg.pack_heat_gen_coeff * s.pack_current * s.pack_current
        if pump_duty_override is not None and s.coolant_pump_duty < 50.0:
            # Coolant circulation failure causes cell stagnation & rapid thermal rise
            heat_gen_kw += 4.5 * (1.0 - s.coolant_pump_duty / 50.0)
        # Cooling from pump
        cooling_kw = (cfg.coolant_flow_coeff * (s.coolant_pump_duty / 100.0)
                      * max(0.0, s.pack_temp - s.ambient_temp))
        # Net temperature change
        if cfg.pack_thermal_mass > 0:
            dt_pack = (heat_gen_kw - cooling_kw) / cfg.pack_thermal_mass * dt_s
            s.pack_temp += dt_pack
        # Coolant temp follows pack with lag
        s.coolant_temp += (s.pack_temp - s.coolant_temp) * 0.05 * dt_s

        # ── Range estimate ──
        # Rolling average of energy_per_km
        s._energy_history.append(s.energy_per_km)
        if len(s._energy_history) > 300:  # last 5 minutes at 1 Hz
            s._energy_history = s._energy_history[-300:]
        avg_epk = sum(s._energy_history) / len(s._energy_history) if s._energy_history else 150.0
        if avg_epk > 1.0:
            usable_kwh = s.soc * cfg.battery_capacity_kwh * 0.95  # 5% buffer
            s.range_estimate = usable_kwh * 1000.0 / avg_epk
        else:
            s.range_estimate = s.soc * cfg.battery_capacity_kwh * 1000.0 / 150.0

        # ── Aux power ──
        s.aux_power = cfg.aux_base_power_kw + s.hvac_power

        # Heartbeat
        s.ecu_heartbeat = (s.ecu_heartbeat + 1) % 256

        return s

    def charge_step(self, dt_s: float) -> VehicleState:
        """Simulate one step of charging (vehicle stationary)."""
        s = self.state
        cfg = self.cfg

        s.vehicle_speed = 0.0
        s.motor_power = 0.0
        s.regen_power = 0.0
        s.accel_long = 0.0
        s.brake_pressure = 0.0
        s.throttle_position = 0.0
        s.charger_connected = 1

        if s.soc < cfg.charge_stop_soc:
            s.charge_power = cfg.charge_power_kw
            s.charge_voltage = s.pack_voltage
            s.charge_current = (cfg.charge_power_kw * 1000.0 / s.pack_voltage
                                if s.pack_voltage > 0 else 0.0)

            energy_wh = cfg.charge_power_kw * cfg.charge_efficiency * 1000.0 * dt_s / 3600.0
            capacity_wh = cfg.battery_capacity_kwh * 1000.0
            s.soc = min(cfg.charge_stop_soc, s.soc + energy_wh / capacity_wh)
            s.pack_voltage = 300.0 + s.soc * 100.0
            s.pack_current = -s.charge_current  # negative = charging
        else:
            s.charge_power = 0.0
            s.charge_current = 0.0
            s.charge_voltage = 0.0

        # Thermal still active during charging
        heat_gen_kw = cfg.pack_heat_gen_coeff * abs(s.pack_current) ** 2
        cooling_kw = (cfg.coolant_flow_coeff * (s.coolant_pump_duty / 100.0)
                      * max(0.0, s.pack_temp - s.ambient_temp))
        if cfg.pack_thermal_mass > 0:
            s.pack_temp += (heat_gen_kw - cooling_kw) / cfg.pack_thermal_mass * dt_s
        s.coolant_temp += (s.pack_temp - s.coolant_temp) * 0.05 * dt_s

        # HVAC still runs during charging
        delta_t = s.cabin_target_temp - s.ambient_temp
        if delta_t > 1.0:
            s.hvac_mode = 1
            s.hvac_power = cfg.hvac_heat_coeff * delta_t
        elif delta_t < -1.0:
            s.hvac_mode = 2
            s.hvac_power = cfg.hvac_cool_coeff * abs(delta_t)
        else:
            s.hvac_mode = 0
            s.hvac_power = 0.0

        s.ecu_heartbeat = (s.ecu_heartbeat + 1) % 256
        return s

    def reset_trip_accumulators(self) -> tuple[float, float]:
        """Reset trip energy/distance and return (energy_wh, distance_km)."""
        e = self.state._trip_energy_wh
        d = self.state._trip_distance_km
        self.state._trip_energy_wh = 0.0
        self.state._trip_distance_km = 0.0
        return e, d

    def disconnect_charger(self) -> None:
        """Disconnect charger."""
        self.state.charger_connected = 0
        self.state.charge_power = 0.0
        self.state.charge_current = 0.0
        self.state.charge_voltage = 0.0
