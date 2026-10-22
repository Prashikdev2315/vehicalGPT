"""Unit tests for robust cgroup v1 and cgroup v2 memory telemetry in slm/telemetry.py."""
from __future__ import annotations

from pathlib import Path
import pytest

from slm.telemetry import (
    TWO_GB_BYTES,
    CGroupMemorySnapshot,
    detect_cgroup_version,
    get_cgroup_peak_mb,
    get_process_rss_mb,
    get_runtime_memory_profile,
    read_cgroup_memory,
    verify_container_memory_limit,
)


class TestCGroupTelemetry:
    def test_unsupported_environment_detection(self, tmp_path: Path):
        """When no cgroup files are present, returns BLOCKED_NO_CGROUP without raising errors."""
        empty_root = tmp_path / "empty_cgroup"
        empty_root.mkdir()

        version = detect_cgroup_version(empty_root)
        assert version is None

        snap = read_cgroup_memory(empty_root)
        assert snap.cgroup_version is None
        assert snap.status == "BLOCKED_NO_CGROUP"
        assert snap.is_capped_at_2gb is False
        assert snap.limit_bytes is None
        assert snap.peak_bytes is None

        is_valid, msg, _ = verify_container_memory_limit(cgroup_root=empty_root)
        assert is_valid is False
        assert "no cgroup filesystem" in msg

    def test_cgroup_v2_enforced_2gb(self, tmp_path: Path):
        """Verify cgroup v2 with 2 GB limit (2,147,483,648 bytes) parses accurately."""
        v2_root = tmp_path / "sys_fs_cgroup_v2"
        v2_root.mkdir()
        (v2_root / "memory.max").write_text("2147483648\n", encoding="utf-8")
        (v2_root / "memory.current").write_text("1048576000\n", encoding="utf-8")
        (v2_root / "memory.peak").write_text("1572864000\n", encoding="utf-8")

        assert detect_cgroup_version(v2_root) == 2

        snap = read_cgroup_memory(v2_root)
        assert snap.cgroup_version == 2
        assert snap.limit_bytes == 2147483648
        assert snap.limit_mb == 2048.0
        assert snap.current_bytes == 1048576000
        assert snap.current_mb == 1000.0
        assert snap.peak_bytes == 1572864000
        assert snap.peak_mb == 1500.0
        assert snap.is_unlimited is False
        assert snap.is_capped_at_2gb is True
        assert snap.status == "enforced_2gb"

        is_valid, msg, _ = verify_container_memory_limit(cgroup_root=v2_root)
        assert is_valid is True
        assert "PASSED" in msg
        assert "2048.0 MB" in msg

    def test_cgroup_v2_unlimited(self, tmp_path: Path):
        """Verify cgroup v2 with 'max' is identified as unlimited and fails 2 GB verification."""
        v2_root = tmp_path / "sys_fs_cgroup_v2_unlimited"
        v2_root.mkdir()
        (v2_root / "memory.max").write_text("max\n", encoding="utf-8")
        (v2_root / "memory.current").write_text("524288000\n", encoding="utf-8")
        (v2_root / "memory.peak").write_text("524288000\n", encoding="utf-8")

        snap = read_cgroup_memory(v2_root)
        assert snap.cgroup_version == 2
        assert snap.is_unlimited is True
        assert snap.is_capped_at_2gb is False
        assert snap.status == "unlimited"

        is_valid, msg, _ = verify_container_memory_limit(cgroup_root=v2_root)
        assert is_valid is False
        assert "UNLIMITED" in msg

    def test_cgroup_v2_exceeds_budget(self, tmp_path: Path):
        """Verify cgroup v2 with 4 GB limit fails 2 GB verification."""
        v2_root = tmp_path / "sys_fs_cgroup_v2_4gb"
        v2_root.mkdir()
        four_gb = 4 * 1024 * 1024 * 1024
        (v2_root / "memory.max").write_text(f"{four_gb}\n", encoding="utf-8")
        (v2_root / "memory.current").write_text("1000000\n", encoding="utf-8")

        snap = read_cgroup_memory(v2_root)
        assert snap.cgroup_version == 2
        assert snap.limit_mb == 4096.0
        assert snap.is_capped_at_2gb is False
        assert snap.status == "exceeds_budget"

        is_valid, msg, _ = verify_container_memory_limit(cgroup_root=v2_root)
        assert is_valid is False
        assert "exceeds" in msg

    def test_cgroup_v1_enforced_2gb(self, tmp_path: Path):
        """Verify cgroup v1 with 2 GB limit in memory.limit_in_bytes."""
        v1_root = tmp_path / "sys_fs_cgroup_v1"
        mem_dir = v1_root / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "memory.limit_in_bytes").write_text("2147483648\n", encoding="utf-8")
        (mem_dir / "memory.usage_in_bytes").write_text("1048576000\n", encoding="utf-8")
        (mem_dir / "memory.max_usage_in_bytes").write_text("1677721600\n", encoding="utf-8")

        assert detect_cgroup_version(v1_root) == 1

        snap = read_cgroup_memory(v1_root)
        assert snap.cgroup_version == 1
        assert snap.limit_bytes == 2147483648
        assert snap.limit_mb == 2048.0
        assert snap.current_mb == 1000.0
        assert snap.peak_mb == 1600.0
        assert snap.is_unlimited is False
        assert snap.is_capped_at_2gb is True

        is_valid, msg, _ = verify_container_memory_limit(cgroup_root=v1_root)
        assert is_valid is True
        assert "cgroup v1 limit enforced" in msg

    def test_cgroup_v1_unlimited_large_int(self, tmp_path: Path):
        """Verify cgroup v1 large integer (e.g. 9223372036854771712) is recognized as unlimited."""
        v1_root = tmp_path / "sys_fs_cgroup_v1_unlimited"
        mem_dir = v1_root / "memory"
        mem_dir.mkdir(parents=True)
        (mem_dir / "memory.limit_in_bytes").write_text("9223372036854771712\n", encoding="utf-8")
        (mem_dir / "memory.usage_in_bytes").write_text("1000000\n", encoding="utf-8")
        (mem_dir / "memory.max_usage_in_bytes").write_text("2000000\n", encoding="utf-8")

        snap = read_cgroup_memory(v1_root)
        assert snap.is_unlimited is True
        assert snap.is_capped_at_2gb is False

        is_valid, msg, _ = verify_container_memory_limit(cgroup_root=v1_root)
        assert is_valid is False
        assert "UNLIMITED" in msg

    def test_runtime_memory_profile_tracks_execution_state(self, tmp_path: Path):
        """Verify get_runtime_memory_profile records during_model_execution flag."""
        v2_root = tmp_path / "v2"
        v2_root.mkdir()
        (v2_root / "memory.max").write_text("2147483648\n", encoding="utf-8")
        (v2_root / "memory.current").write_text("500000000\n", encoding="utf-8")
        (v2_root / "memory.peak").write_text("800000000\n", encoding="utf-8")

        profile_idle = get_runtime_memory_profile(during_model_execution=False, cgroup_root=v2_root)
        assert profile_idle["during_model_execution"] is False
        assert profile_idle["memory_source"] == "cgroup_v2"
        assert profile_idle["peak_memory_mb"] == round(800000000 / (1024 * 1024), 2)
        assert profile_idle["cgroup_enforced_2gb"] is True

        profile_active = get_runtime_memory_profile(during_model_execution=True, cgroup_root=v2_root)
        assert profile_active["during_model_execution"] is True

    def test_get_process_rss_returns_positive_float(self):
        """Verify get_process_rss_mb returns a non-negative float on the active OS."""
        rss = get_process_rss_mb()
        assert isinstance(rss, float)
        assert rss >= 0.0

    def test_get_cgroup_peak_mb_returns_none_when_unsupported(self, tmp_path: Path):
        """Verify get_cgroup_peak_mb returns None (NEVER host RSS) when no cgroup exists."""
        empty_root = tmp_path / "no_cgroup"
        empty_root.mkdir()
        peak = get_cgroup_peak_mb(empty_root)
        assert peak is None

    def test_get_cgroup_peak_mb_cgroup_v2(self, tmp_path: Path):
        """Verify get_cgroup_peak_mb returns accurate peak for cgroup v2."""
        v2_root = tmp_path / "v2_peak"
        v2_root.mkdir()
        (v2_root / "memory.max").write_text("2147483648\n", encoding="utf-8")
        (v2_root / "memory.peak").write_text("1258291200\n", encoding="utf-8")  # 1200 MB
        peak = get_cgroup_peak_mb(v2_root)
        assert peak == 1200.0

    def test_get_cgroup_peak_mb_cgroup_v1(self, tmp_path: Path):
        """Verify get_cgroup_peak_mb returns accurate peak for cgroup v1."""
        v1_root = tmp_path / "v1_peak"
        mem = v1_root / "memory"
        mem.mkdir(parents=True)
        (mem / "memory.limit_in_bytes").write_text("2147483648\n", encoding="utf-8")
        (mem / "memory.max_usage_in_bytes").write_text("1048576000\n", encoding="utf-8")  # 1000 MB
        peak = get_cgroup_peak_mb(v1_root)
        assert peak == 1000.0

    def test_cgroup_v1_direct_root_controller(self, tmp_path: Path):
        """Verify cgroup v1 works when controller files are directly under target root."""
        root = tmp_path / "v1_direct"
        root.mkdir()
        (root / "memory.limit_in_bytes").write_text("2147483648\n", encoding="utf-8")
        (root / "memory.usage_in_bytes").write_text("524288000\n", encoding="utf-8")
        (root / "memory.max_usage_in_bytes").write_text("734003200\n", encoding="utf-8")  # 700 MB

        assert detect_cgroup_version(root) == 1
        snap = read_cgroup_memory(root)
        assert snap.cgroup_version == 1
        assert snap.limit_mb == 2048.0
        assert snap.peak_mb == 700.0
        assert snap.is_capped_at_2gb is True

    def test_require_cgroup_fails_when_unsupported(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """Verify verify_container_memory_limit fails when cgroup is missing."""
        empty_root = tmp_path / "empty"
        empty_root.mkdir()
        ok, msg, snap = verify_container_memory_limit(cgroup_root=empty_root)
        assert ok is False
        assert snap.status == "BLOCKED_NO_CGROUP"
        assert "BLOCKED" in msg
