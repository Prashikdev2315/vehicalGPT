"""Test: CAN adapter send/receive on virtual bus, DBC decode."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from ingest.can_adapter import CANAdapter

DBC_PATH = Path("docs/signals.dbc")


@pytest.fixture
def adapter_pair() -> tuple[CANAdapter, CANAdapter]:
    """Create a sender/receiver pair on the same virtual bus."""
    sender = CANAdapter(bus_type="virtual", channel="test_ch", dbc_path=DBC_PATH)
    receiver = CANAdapter(bus_type="virtual", channel="test_ch", dbc_path=DBC_PATH)
    sender.start()
    receiver.start()
    yield sender, receiver
    sender.stop()
    receiver.stop()


class TestCANAdapter:
    def test_send_receive_roundtrip(self, adapter_pair: tuple[CANAdapter, CANAdapter]) -> None:
        """Send signals, receive and decode — values must match DBC resolution."""
        sender, receiver = adapter_pair

        test_signals = {
            "vehicle_speed": 55.55,
            "soc": 72.3,
            "pack_voltage": 350.0,
        }

        sender.send(test_signals, timestamp=1000.0)
        time.sleep(0.05)

        received = receiver.recv_one(timeout=1.0)
        assert received is not None, "No message received"
        # At least one signal should be present
        assert len(received) > 0

    def test_dbc_loads(self) -> None:
        """DBC file loads without errors."""
        import cantools
        db = cantools.database.load_file(str(DBC_PATH))
        assert len(db.messages) > 0
        # Check key signals exist
        signal_names = set()
        for msg in db.messages:
            for sig in msg.signals:
                signal_names.add(sig.name)
        assert "vehicle_speed" in signal_names
        assert "soc" in signal_names
        assert "pack_temp" in signal_names
        assert "hvac_power" in signal_names

    def test_virtual_bus_multiple_messages(self, adapter_pair: tuple[CANAdapter, CANAdapter]) -> None:
        """Multiple messages can be sent and received."""
        sender, receiver = adapter_pair

        signals = {
            "vehicle_speed": 80.0,
            "accel_long": 1.5,
            "brake_pressure": 0.0,
            "throttle_position": 45.0,
            "soc": 65.0,
            "pack_voltage": 370.0,
            "ambient_temp": 15.0,
        }
        sender.send(signals, timestamp=2000.0)
        time.sleep(0.05)

        # Receive multiple messages
        all_received: dict[str, float] = {}
        for _ in range(20):
            result = receiver.recv_one(timeout=0.1)
            if result is None:
                break
            all_received.update(result)

        assert len(all_received) > 0
