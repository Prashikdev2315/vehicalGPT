"""Drive cycle generator: creates realistic daily trip patterns.

Produces speed profiles and road-type tags for the vehicle model.
Deterministic via numpy RNG seeded from the main simulation seed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.random import Generator


@dataclass
class TripSegment:
    """One segment of a trip at a roughly constant target speed."""

    duration_s: float
    target_speed_kmh: float
    road_type: int  # 0=city, 1=highway, 2=mixed


@dataclass
class Trip:
    """A complete trip made up of segments."""

    segments: list[TripSegment]
    trip_type: str  # "city", "highway", "mixed"

    @property
    def total_duration_s(self) -> float:
        return sum(seg.duration_s for seg in self.segments)

    @property
    def city_share(self) -> float:
        total = self.total_duration_s
        if total == 0:
            return 0.0
        city = sum(s.duration_s for s in self.segments if s.road_type == 0)
        return city / total

    @property
    def highway_share(self) -> float:
        total = self.total_duration_s
        if total == 0:
            return 0.0
        hwy = sum(s.duration_s for s in self.segments if s.road_type == 1)
        return hwy / total


@dataclass
class DailySchedule:
    """All activities for one simulated day."""

    trips: list[Trip]
    charge_start_hour: float  # hour of day to start charging (e.g. 22.5)
    charge_duration_h: float  # how long to charge


def _city_trip(rng: Generator, distance_km: float) -> Trip:
    """Generate a city driving trip."""
    segments: list[TripSegment] = []
    remaining_km = distance_km
    avg_speed = 30.0  # km/h

    while remaining_km > 0.5:
        # Cruise segment
        seg_km = min(remaining_km, rng.uniform(0.8, 2.5))
        speed = rng.uniform(25.0, 50.0)
        duration = seg_km / speed * 3600.0
        segments.append(TripSegment(duration, speed, road_type=0))
        remaining_km -= seg_km

        # Stop (traffic light / intersection)
        if remaining_km > 0.5:
            stop_s = rng.uniform(10.0, 45.0)
            segments.append(TripSegment(stop_s, 0.0, road_type=0))

    return Trip(segments=segments, trip_type="city")


def _highway_trip(rng: Generator, distance_km: float) -> Trip:
    """Generate a highway driving trip."""
    segments: list[TripSegment] = []
    remaining_km = distance_km

    # On-ramp (city portion)
    ramp_km = min(remaining_km * 0.1, 2.0)
    segments.append(TripSegment(ramp_km / 35.0 * 3600.0, 35.0, road_type=0))
    remaining_km -= ramp_km

    # Highway cruise
    while remaining_km > 5.0:
        seg_km = min(remaining_km - 2.0, rng.uniform(10.0, 30.0))
        speed = rng.uniform(80.0, 120.0)
        duration = seg_km / speed * 3600.0
        segments.append(TripSegment(duration, speed, road_type=1))
        remaining_km -= seg_km

    # Off-ramp (city portion)
    if remaining_km > 0.5:
        segments.append(TripSegment(remaining_km / 35.0 * 3600.0, 35.0, road_type=0))

    return Trip(segments=segments, trip_type="highway")


def _mixed_trip(rng: Generator, distance_km: float) -> Trip:
    """Generate a mixed city/highway trip."""
    segments: list[TripSegment] = []
    remaining_km = distance_km

    # Alternate city and highway segments
    is_city = True
    while remaining_km > 0.5:
        if is_city:
            seg_km = min(remaining_km, rng.uniform(2.0, 5.0))
            speed = rng.uniform(25.0, 50.0)
            segments.append(TripSegment(seg_km / speed * 3600.0, speed, road_type=0))
            # Occasional stop
            if rng.random() < 0.4 and remaining_km > 2.0:
                segments.append(TripSegment(rng.uniform(10.0, 30.0), 0.0, road_type=0))
        else:
            seg_km = min(remaining_km, rng.uniform(5.0, 15.0))
            speed = rng.uniform(70.0, 110.0)
            segments.append(TripSegment(seg_km / speed * 3600.0, speed, road_type=1))

        remaining_km -= seg_km
        is_city = not is_city

    return Trip(segments=segments, trip_type="mixed")


def generate_daily_schedule(
    day_index: int,
    rng: Generator,
    weekday_trips: int = 2,
    commute_distance_km: float = 15.0,
    weekend_long_trip_prob: float = 0.25,
    weekend_long_distance_km: float = 80.0,
) -> DailySchedule:
    """Generate a day's schedule of trips and charging.

    Args:
        day_index: 0-based day number (0=Monday of week 1).
        rng: Seeded numpy Generator for determinism.
        weekday_trips: Number of commute trips on weekdays.
        commute_distance_km: Typical one-way commute distance.
        weekend_long_trip_prob: Probability of a long weekend trip.
        weekend_long_distance_km: Distance of weekend long trip.

    Returns:
        DailySchedule with trips and charging plan.
    """
    day_of_week = day_index % 7  # 0=Mon, 5=Sat, 6=Sun
    is_weekend = day_of_week >= 5

    trips: list[Trip] = []

    if is_weekend:
        # Weekend: maybe a long trip, maybe short errands
        if rng.random() < weekend_long_trip_prob:
            trip = _mixed_trip(rng, weekend_long_distance_km)
            trips.append(trip)
        else:
            # Short errands
            n_errands = rng.integers(1, 3)
            for _ in range(n_errands):
                dist = rng.uniform(3.0, 10.0)
                trip = _city_trip(rng, dist)
                trips.append(trip)
    else:
        # Weekday: commute trips
        for i in range(weekday_trips):
            dist = commute_distance_km * rng.uniform(0.9, 1.1)
            # Morning trip is more likely city, afternoon mixed
            if i == 0:
                trip = _city_trip(rng, dist)
            else:
                trip = _mixed_trip(rng, dist) if rng.random() < 0.4 else _city_trip(rng, dist)
            trips.append(trip)

    # Charging: overnight, starting around 22:00-23:00
    charge_start = rng.uniform(22.0, 23.0)
    charge_duration = rng.uniform(4.0, 7.0)

    return DailySchedule(
        trips=trips,
        charge_start_hour=charge_start,
        charge_duration_h=charge_duration,
    )
