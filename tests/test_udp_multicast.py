"""Test: two-process send/receive via python-can udp_multicast (D4)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_udp_multicast_two_processes() -> None:
    """Verify that process A can send and process B can receive via udp_multicast."""
    rx_code = (
        "import sys, can\n"
        "try:\n"
        "    bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=50020)\n"
        "    print('READY', flush=True)\n"
        "    msg = bus.recv(timeout=4.0)\n"
        "    bus.shutdown()\n"
        "    if msg and msg.arbitration_id == 0x123:\n"
        "        print('SUCCESS', flush=True)\n"
        "        sys.exit(0)\n"
        "    sys.exit(1)\n"
        "except Exception as e:\n"
        "    print(f'ERROR: {e}', flush=True)\n"
        "    sys.exit(2)\n"
    )

    tx_code = (
        "import time, can\n"
        "time.sleep(0.5)\n"
        "bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=50020)\n"
        "msg = can.Message(arbitration_id=0x123, data=[0xDE, 0xAD, 0xBE, 0xEF], is_extended_id=False)\n"
        "bus.send(msg)\n"
        "time.sleep(0.2)\n"
        "bus.shutdown()\n"
    )

    p_rx = subprocess.Popen(
        [sys.executable, "-c", rx_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    # Wait for receiver to be bound and ready
    ready_line = p_rx.stdout.readline().strip() if p_rx.stdout else ""
    if "could not create or configure socket" in ready_line:
        p_rx.communicate(timeout=5)
        pytest.skip("udp_multicast socket unavailable in this container/network runtime")
    assert ready_line == "READY", f"Receiver did not report READY: {ready_line}"

    p_tx = subprocess.Popen(
        [sys.executable, "-c", tx_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p_tx.wait(timeout=5)
    stdout, stderr = p_rx.communicate(timeout=5)

    assert p_rx.returncode == 0, f"Receiver failed with rc={p_rx.returncode}. stdout={stdout}, stderr={stderr}"
    assert "SUCCESS" in stdout
