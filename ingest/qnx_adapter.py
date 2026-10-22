"""QNX/DLT log adapter stub — fixture-only in M1."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ingest.base import BaseAdapter, NormalisedRow


class QNXLogAdapter(BaseAdapter):
    """Stub QNX log adapter. Parses fixture text logs only (M5 for real stack)."""

    # Simple log line regex: timestamp level source [component] message
    _LINE_RE = re.compile(
        r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z)\s+(\w+)\s+(\S+)\s+\[(\S+)\]\s+(.+)$"
    )

    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self._fixture_path = Path(fixture_path) if fixture_path else None

    @property
    def source_name(self) -> str:
        return "qnx"

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def read(self) -> Iterator[NormalisedRow]:
        """Parse the QNX log fixture if provided."""
        if not self._fixture_path or not self._fixture_path.exists():
            return

        with open(self._fixture_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m = self._LINE_RE.match(line)
                if m:
                    ts_str, level, source, component, message = m.groups()
                    try:
                        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        ts_ms = int(dt.timestamp() * 1000)
                    except ValueError:
                        continue
                    # Yield as a log-type row (signal = level for now)
                    yield NormalisedRow(
                        ts=ts_ms, source="qnx",
                        signal=f"log_{level.lower()}", value=1.0, unit="",
                    )
