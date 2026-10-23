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
    assert engine.use_cache is False
    assert engine.is_available is False

    with pytest.raises(FileNotFoundError):
        engine._ensure_loaded()


def test_slm_engine_use_cache_explicit_opt_in() -> None:
    """Verify SLMEngine allows explicitly enabling cache when requested."""
    engine = SLMEngine(model_path="models/nonexistent.gguf", n_ctx=1024, n_threads=2, use_cache=True, lazy_load=True)
    assert engine.use_cache is True


def test_get_slm_engine_cache_defaults_and_opt_in() -> None:
    """Verify get_slm_engine defaults to use_cache=False and preserves opt-in compatibility."""
    from slm.engine import get_slm_engine, reset_slm_engine
    reset_slm_engine()
    e_default = get_slm_engine(model_path="models/nonexistent.gguf", lazy_load=True)
    assert e_default.use_cache is False

    reset_slm_engine()
    e_opt_in = get_slm_engine(model_path="models/nonexistent.gguf", use_cache=True, lazy_load=True)
    assert e_opt_in.use_cache is True
    reset_slm_engine()
