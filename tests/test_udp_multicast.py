"""Test: two-process send/receive via python-can udp_multicast (D4)."""
from __future__ import annotations

import subprocess
import sys
import os
from pathlib import Path

import pytest


def _cleanup_process(proc: subprocess.Popen[str] | None) -> None:
    """Best-effort process cleanup to avoid orphans in failure/timeout paths."""
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=1)
        except Exception:
            pass


def test_udp_multicast_two_processes() -> None:
    """Verify that process A can send and process B can receive via udp_multicast."""
    require_multicast = os.getenv("VEHICLEGPT_REQUIRE_UDP_MULTICAST") == "1"
    rx_code = (
        "import sys, can\n"
        "try:\n"
        "    bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=50020)\n"
        "except Exception as e:\n"
        "    print(f'INIT_ERROR:{type(e).__name__}:{e}', flush=True)\n"
        "    sys.exit(2)\n"
        "try:\n"
        "    print('READY', flush=True)\n"
        "    msg = bus.recv(timeout=4.0)\n"
        "    bus.shutdown()\n"
        "    if msg and msg.arbitration_id == 0x123:\n"
        "        print('SUCCESS', flush=True)\n"
        "        sys.exit(0)\n"
        "    sys.exit(1)\n"
        "except Exception as e:\n"
        "    print(f'RUNTIME_ERROR:{type(e).__name__}:{e}', flush=True)\n"
        "    sys.exit(3)\n"
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
    p_tx: subprocess.Popen[str] | None = None
    try:
        # Wait for receiver to be bound and ready
        ready_line = p_rx.stdout.readline().strip() if p_rx.stdout else ""
        if ready_line.startswith("INIT_ERROR:"):
            _, exc_type, exc_msg = ready_line.split(":", 2)
            init_unavailable_patterns = (
                "could not create or configure socket",
                "No such device",
                "Network is unreachable",
                "Operation not permitted",
                "Cannot assign requested address",
            )
            is_env_unavailable = (
                exc_type in {"OSError", "CanInitializationError", "CanInterfaceNotImplementedError"}
                and any(pattern in exc_msg for pattern in init_unavailable_patterns)
            )
            if is_env_unavailable and not require_multicast:
                p_rx.communicate(timeout=5)
                pytest.skip(
                    f"udp_multicast unavailable in this runtime ({exc_type}: {exc_msg})"
                )
            stdout, stderr = p_rx.communicate(timeout=5)
            pytest.fail(
                "Receiver failed to initialize udp_multicast: "
                f"{exc_type}: {exc_msg}. stdout={stdout} stderr={stderr}"
            )
        if ready_line == "":
            stdout, stderr = p_rx.communicate(timeout=5)
            pytest.fail(f"Receiver produced no readiness output. stdout={stdout} stderr={stderr}")
        if ready_line.startswith("RUNTIME_ERROR:"):
            stdout, stderr = p_rx.communicate(timeout=5)
            pytest.fail(f"Receiver runtime error before READY: {ready_line}. stdout={stdout} stderr={stderr}")
        if ready_line.startswith("ERROR:"):
            stdout, stderr = p_rx.communicate(timeout=5)
            pytest.fail(f"Receiver startup error before READY: {ready_line}. stdout={stdout} stderr={stderr}")
        if "could not create or configure socket" in ready_line:
            p_rx.communicate(timeout=5)
            pytest.fail(f"Unexpected unstructured startup error format: {ready_line}")
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
    finally:
        _cleanup_process(p_tx)
        _cleanup_process(p_rx)
