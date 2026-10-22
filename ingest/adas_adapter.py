"""ADAS event adapter."""
from __future__ import annotations

from typing import Iterator

from ingest.base import BaseAdapter, NormalisedRow


class ADASAdapter(BaseAdapter):
    """ADAS event adapter.

    In M1, ADAS events are inserted directly by the simulator.
    This adapter provides the interface for future ADAS system integration.
    """

    @property
    def source_name(self) -> str:
        return "adas"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> Iterator[NormalisedRow]:
        yield from []
