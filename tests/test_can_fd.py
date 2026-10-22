"""Test: CAN-FD 64-byte message roundtrip on virtual bus (D5)."""
from __future__ import annotations

from pathlib import Path
import pytest
import can
import cantools

DBC_PATH = Path("docs/signals.dbc")


class TestCanFd:
    def test_can_fd_virtual_bus_roundtrip(self) -> None:
        """Send and receive a 64-byte CAN-FD frame on the virtual bus."""
        channel = "vcan_fd_test"
        bus_tx = can.Bus(interface="virtual", channel=channel, fd=True)
        bus_rx = can.Bus(interface="virtual", channel=channel, fd=True)

        payload = bytes([i % 256 for i in range(64)])
        msg_tx = can.Message(
            arbitration_id=0x700,
            data=payload,
            is_fd=True,
            is_extended_id=False,
            bitrate_switch=True,
        )

        bus_tx.send(msg_tx)
        msg_rx = bus_rx.recv(timeout=1.0)

        bus_tx.shutdown()
        bus_rx.shutdown()

        assert msg_rx is not None, "Failed to receive CAN-FD message"
        assert msg_rx.arbitration_id == 0x700
        assert msg_rx.is_fd is True
        assert len(msg_rx.data) == 64
        assert msg_rx.data == payload

    def test_can_fd_dbc_encode_decode(self) -> None:
        """Verify DBC encodes and decodes the 64-byte DiagSnapshot message."""
        dbc = cantools.database.load_file(str(DBC_PATH))
        msg_def = dbc.get_message_by_name("DiagSnapshot")
        assert msg_def.length == 64

        signals = {
            "diag_ecu_id": 0x42,
            "diag_status": 0x01,
            "diag_dtc_count": 3,
            "diag_payload_byte0": 0xAA,
            "diag_payload_byte63": 0xFF,
        }
        encoded = msg_def.encode(signals, strict=False)
        assert len(encoded) == 64

        decoded = msg_def.decode(encoded)
        assert decoded["diag_ecu_id"] == 0x42
        assert decoded["diag_status"] == 0x01
        assert decoded["diag_dtc_count"] == 3
        assert decoded["diag_payload_byte0"] == 0xAA
        assert decoded["diag_payload_byte63"] == 0xFF
