"""CAN bus adapter using python-can.

Supports:
    - virtual bus (single-process tests)
    - udp_multicast (multi-process / container)
    - socketcan (real can0, config-only change)
    - candump log file replay

All signal decoding uses docs/signals.dbc via cantools.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Iterator

import can
import cantools

from ingest.base import BaseAdapter, NormalisedRow


class CANAdapter(BaseAdapter):
    """CAN bus adapter behind python-can."""

    def __init__(
        self,
        bus_type: str = "virtual",
        channel: str = "vcan0",
        dbc_path: str | Path = "docs/signals.dbc",
        bitrate: int = 500000,
        fd: bool = False,
    ) -> None:
        self._bus_type = bus_type
        self._channel = channel
        self._dbc_path = Path(dbc_path)
        self._bitrate = bitrate
        self._fd = fd
        self._bus: can.BusABC | None = None
        self._db: cantools.database.Database | None = None

    @property
    def source_name(self) -> str:
        return "can"

    def start(self) -> None:
        """Open the CAN bus and load the DBC."""
        self._db = cantools.database.load_file(str(self._dbc_path))
        self._bus = can.Bus(
            interface=self._bus_type,
            channel=self._channel,
            bitrate=self._bitrate,
            fd=self._fd,
        )

    def stop(self) -> None:
        if self._bus is not None:
            self._bus.shutdown()
            self._bus = None

    def send(self, signals: dict[str, float], timestamp: float | None = None) -> None:
        """Encode and send signals as CAN messages.

        Groups signals by DBC message and sends each message.
        """
        if self._bus is None or self._db is None:
            raise RuntimeError("Adapter not started")

        for msg_def in self._db.messages:
            msg_signals = {}
            for sig in msg_def.signals:
                if sig.name in signals:
                    msg_signals[sig.name] = signals[sig.name]

            if msg_signals:
                # Fill in defaults for signals not provided
                for sig in msg_def.signals:
                    if sig.name not in msg_signals:
                        msg_signals[sig.name] = sig.offset if sig.offset else 0
                try:
                    data = msg_def.encode(msg_signals, strict=False)
                except Exception:
                    continue
                msg = can.Message(
                    arbitration_id=msg_def.frame_id,
                    data=data,
                    is_extended_id=False,
                    is_fd=msg_def.length > 8,
                    timestamp=timestamp or time.time(),
                )
                self._bus.send(msg)

    def read(self) -> Iterator[NormalisedRow]:
        """Read and decode CAN messages, yielding normalised rows."""
        if self._bus is None or self._db is None:
            raise RuntimeError("Adapter not started")

        while True:
            msg = self._bus.recv(timeout=1.0)
            if msg is None:
                break

            try:
                decoded = self._db.decode_message(msg.arbitration_id, msg.data)
            except (KeyError, cantools.database.DecodeError):
                continue

            ts_ms = int(msg.timestamp * 1000)
            for sig_name, sig_val in decoded.items():
                # Look up unit from DBC
                try:
                    msg_def = self._db.get_message_by_frame_id(msg.arbitration_id)
                    sig_def = msg_def.get_signal_by_name(sig_name)
                    unit = sig_def.unit or ""
                except (KeyError, AttributeError):
                    unit = ""

                yield NormalisedRow(
                    ts=ts_ms,
                    source="can",
                    signal=sig_name,
                    value=float(sig_val),
                    unit=unit,
                )

    def recv_one(self, timeout: float = 1.0) -> dict[str, float] | None:
        """Receive and decode a single CAN message. Returns {signal: value} or None."""
        if self._bus is None or self._db is None:
            raise RuntimeError("Adapter not started")

        msg = self._bus.recv(timeout=timeout)
        if msg is None:
            return None

        try:
            decoded = self._db.decode_message(msg.arbitration_id, msg.data)
            return {k: float(v) for k, v in decoded.items()}
        except (KeyError, cantools.database.DecodeError):
            return None


class CandumpReplayAdapter(BaseAdapter):
    """Replays a candump-format log file through the CAN adapter interface."""

    def __init__(self, log_path: str | Path,
                 dbc_path: str | Path = "docs/signals.dbc") -> None:
        self._log_path = Path(log_path)
        self._dbc_path = Path(dbc_path)
        self._db: cantools.database.Database | None = None

    @property
    def source_name(self) -> str:
        return "can"

    def start(self) -> None:
        self._db = cantools.database.load_file(str(self._dbc_path))

    def stop(self) -> None:
        pass

    def read(self) -> Iterator[NormalisedRow]:
        """Parse and decode a candump log file."""
        if self._db is None:
            raise RuntimeError("Adapter not started")

        with open(self._log_path, "r", encoding="ascii") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    # Format: (timestamp) interface id#data
                    parts = line.split()
                    ts_str = parts[0].strip("()")
                    ts_ms = int(float(ts_str) * 1000)
                    frame_part = parts[2]  # id#data
                    frame_id_str, data_hex = frame_part.split("#")
                    frame_id = int(frame_id_str, 16)
                    data = bytes.fromhex(data_hex)

                    decoded = self._db.decode_message(frame_id, data)
                    for sig_name, sig_val in decoded.items():
                        try:
                            msg_def = self._db.get_message_by_frame_id(frame_id)
                            sig_def = msg_def.get_signal_by_name(sig_name)
                            unit = sig_def.unit or ""
                        except (KeyError, AttributeError):
                            unit = ""

                        yield NormalisedRow(
                            ts=ts_ms,
                            source="can",
                            signal=sig_name,
                            value=float(sig_val),
                            unit=unit,
                        )
                except (ValueError, IndexError, KeyError,
                        cantools.database.DecodeError):
                    continue
