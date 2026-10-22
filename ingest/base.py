"""Common adapter interface (ABC) for all ingestion sources."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator, NamedTuple


class NormalisedRow(NamedTuple):
    """A single normalised data point: (ts, source, signal, value, unit)."""
    ts: int  # epoch milliseconds
    source: str  # can | someip | vhal | qnx | adas | diag | derived
    signal: str  # canonical signal name
    value: float
    unit: str


class BaseAdapter(ABC):
    """Abstract base for protocol adapters."""

    @abstractmethod
    def start(self) -> None:
        """Start the adapter (connect to bus, open file, etc.)."""

    @abstractmethod
    def stop(self) -> None:
        """Stop the adapter and release resources."""

    @abstractmethod
    def read(self) -> Iterator[NormalisedRow]:
        """Yield normalised rows from the source."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return the source identifier (e.g. 'can', 'someip')."""
