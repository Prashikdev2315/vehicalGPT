"""Diagnostics adapter for DTC/UDS ingestion."""
from __future__ import annotations

from typing import Iterator

from ingest.base import BaseAdapter, NormalisedRow


class DiagAdapter(BaseAdapter):
    """DTC / diagnostic data adapter.

    In M1, DTCs are inserted directly by the simulator into the dtcs table.
    This adapter provides the interface for future UDS/ISO-TP integration.
    """

    @property
    def source_name(self) -> str:
        return "diag"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> Iterator[NormalisedRow]:
        yield from []
