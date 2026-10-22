"""SOME/IP adapter stub — fixture-only in M1."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ingest.base import BaseAdapter, NormalisedRow


class SOMEIPAdapter(BaseAdapter):
    """Stub SOME/IP adapter. Parses fixture files only (M5 for real stack)."""

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self._fixture_path = Path(fixture_path) if fixture_path else None

    @property
    def source_name(self) -> str:
        return "someip"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> Iterator[NormalisedRow]:
        """Parse the placeholder fixture if provided."""
        if self._fixture_path and self._fixture_path.exists():
            # Fixture is a simple hex dump text file — no real parsing in M1
            yield from []
