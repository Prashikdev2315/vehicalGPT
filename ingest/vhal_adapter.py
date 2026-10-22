"""Android Vehicle HAL adapter stub — fixture-only in M1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ingest.base import BaseAdapter, NormalisedRow


class VHALAdapter(BaseAdapter):
    """Stub VHAL adapter. Parses fixture JSON only (M5 for real stack)."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self._fixture_path = Path(fixture_path) if fixture_path else None

    @property
    def source_name(self) -> str:
        return "vhal"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> Iterator[NormalisedRow]:
        """Parse the VHAL fixture JSON if provided."""
        if not self._fixture_path or not self._fixture_path.exists():
            return

        with open(self._fixture_path, encoding="utf-8") as f:
            data = json.load(f)

        for prop in data.get("properties", []):
            ts = prop.get("timestamp", 0)
            name = prop.get("prop_name", "unknown").lower()
            values = prop.get("value", {}).get("floatValues", [])
            if values:
                yield NormalisedRow(
                    ts=ts, source="vhal", signal=name,
                    value=values[0], unit="",
                )
