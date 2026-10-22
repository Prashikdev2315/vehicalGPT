"""Tests for SLM runtime harness, checksum verification, and engine initialization."""
from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from scripts.download_model import EXPECTED_SHA256, EXPECTED_SIZE, verify_checksum
from slm.engine import SLMEngine


def test_verify_checksum_logic(tmp_path: Path) -> None:
    """Verify that checksum verification accurately detects matching and mismatching files."""
    f = tmp_path / "test.bin"
    content = b"VehicleGPT-SLM-Verification-Test"
    f.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest()

    assert verify_checksum(f, expected_hash) is True
    assert verify_checksum(f, "0000000000000000000000000000000000000000000000000000000000000000") is False


def test_model_constants() -> None:
    """Verify defined GGUF model properties match exact HuggingFace metadata."""
    assert EXPECTED_SIZE == 1117320736
    assert EXPECTED_SHA256 == "6a1a2eb6d15622bf3c96857206351ba97e1af16c30d7a74ee38970e434e9407e"


def test_slm_engine_lazy_init() -> None:
    """Verify SLMEngine configures parameters and supports lazy loading."""
    engine = SLMEngine(model_path="models/nonexistent.gguf", n_ctx=1024, n_threads=2, lazy_load=True)
    assert engine.n_ctx == 1024
    assert engine.n_threads == 2
    assert engine.is_available is False

    with pytest.raises(FileNotFoundError):
        engine._ensure_loaded()
