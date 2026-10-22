"""Process and cgroup memory telemetry utilities.

Supports:
- Linux cgroup v2 (/sys/fs/cgroup/memory.max, memory.current, memory.peak)
- Linux cgroup v1 (/sys/fs/cgroup/memory/memory.limit_in_bytes, memory.usage_in_bytes, memory.max_usage_in_bytes)
- Windows GetProcessMemoryInfo WorkingSetSize
- POSIX resource.getrusage fallback

Strictly enforces:
- Does NOT silently report unavailable cgroup metrics as zero.
- Detects unlimited limits ('max' or >= 2^60 bytes).
- Distinguishes measured cgroup peak from host/process RSS.
- Verifies effective container limit <= 2,147,483,648 bytes (2 GB).
"""
from __future__ import annotations

import ctypes
from dataclasses import asdict, dataclass
import os
from pathlib import Path
from typing import Any

# 2 GiB in bytes
TWO_GB_BYTES = 2 * 1024 * 1024 * 1024  # 2,147,483,648 bytes

# Windows memory structures
if os.name == "nt":
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]


@dataclass
class CGroupMemorySnapshot:
    """Structured snapshot of Linux cgroup memory state."""

    cgroup_version: int | None
    limit_bytes: int | None
    limit_mb: float | None
    current_bytes: int | None
    current_mb: float | None
    peak_bytes: int | None
    peak_mb: float | None
    is_unlimited: bool
    is_capped_at_2gb: bool
    status: str
    details: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_cgroup_version(cgroup_root: Path | None = None) -> int | None:
    """Detect whether Linux cgroup v2, cgroup v1, or none is active."""
    root = cgroup_root or Path("/sys/fs/cgroup")
    if not root.exists():
        return None

    # cgroup v2 uses unified hierarchy at root: memory.max / memory.current / cgroup.controllers
    if (root / "memory.max").exists() or (root / "cgroup.controllers").exists():
        return 2

    # cgroup v1 uses per-subsystem controllers: either root/memory or directly at root
    if (root / "memory" / "memory.limit_in_bytes").exists() or (root / "memory.limit_in_bytes").exists():
        return 1

    return None


def read_cgroup_memory(cgroup_root: Path | None = None) -> CGroupMemorySnapshot:
    """Read Linux cgroup memory parameters.

    Returns structured snapshot. Does NOT return zeros or host RSS for unavailable metrics.
    """
    root = cgroup_root or Path("/sys/fs/cgroup")
    version = detect_cgroup_version(root)

    if version is None:
        return CGroupMemorySnapshot(
            cgroup_version=None,
            limit_bytes=None,
            limit_mb=None,
            current_bytes=None,
            current_mb=None,
            peak_bytes=None,
            peak_mb=None,
            is_unlimited=True,
            is_capped_at_2gb=False,
            status="BLOCKED_NO_CGROUP",
            details="No cgroup v1 or v2 filesystem detected at target root",
        )

    limit_bytes: int | None = None
    current_bytes: int | None = None
    peak_bytes: int | None = None
    is_unlimited = False

    try:
        if version == 2:
            # cgroup v2
            max_file = root / "memory.max"
            if max_file.exists():
                content = max_file.read_text(encoding="utf-8").strip()
                if content == "max":
                    is_unlimited = True
                else:
                    limit_bytes = int(content)

            curr_file = root / "memory.current"
            if curr_file.exists():
                current_bytes = int(curr_file.read_text(encoding="utf-8").strip())

            peak_file = root / "memory.peak"
            if peak_file.exists():
                peak_bytes = int(peak_file.read_text(encoding="utf-8").strip())
            else:
                # Older kernel without memory.peak
                peak_bytes = current_bytes

        elif version == 1:
            # cgroup v1: check root/memory first, then root directly
            v1_dir = root / "memory" if (root / "memory" / "memory.limit_in_bytes").exists() else root
            lim_file = v1_dir / "memory.limit_in_bytes"
            if lim_file.exists():
                val = int(lim_file.read_text(encoding="utf-8").strip())
                # cgroup v1 sets ~9223372036854771712 for unlimited
                if val >= 9223372036854771712 or val >= (1 << 60):
                    is_unlimited = True
                else:
                    limit_bytes = val

            usage_file = v1_dir / "memory.usage_in_bytes"
            if usage_file.exists():
                current_bytes = int(usage_file.read_text(encoding="utf-8").strip())

            max_usage_file = v1_dir / "memory.max_usage_in_bytes"
            if max_usage_file.exists():
                peak_bytes = int(max_usage_file.read_text(encoding="utf-8").strip())

    except Exception as e:
        return CGroupMemorySnapshot(
            cgroup_version=version,
            limit_bytes=None,
            limit_mb=None,
            current_bytes=None,
            current_mb=None,
            peak_bytes=None,
            peak_mb=None,
            is_unlimited=True,
            is_capped_at_2gb=False,
            status="error",
            details=f"Error reading cgroup files: {e}",
        )

    limit_mb = round(limit_bytes / (1024.0 * 1024.0), 2) if limit_bytes is not None else None
    current_mb = round(current_bytes / (1024.0 * 1024.0), 2) if current_bytes is not None else None
    peak_mb = round(peak_bytes / (1024.0 * 1024.0), 2) if peak_bytes is not None else None

    # Verification of 2 GB cap
    is_capped = (limit_bytes is not None) and (not is_unlimited) and (limit_bytes <= TWO_GB_BYTES)

    if is_unlimited:
        status = "unlimited"
        details = f"cgroup v{version} memory limit is unconstrained (max)"
    elif is_capped:
        status = "enforced_2gb"
        details = f"cgroup v{version} memory limit verified at {limit_mb} MB (<= 2048 MB)"
    else:
        status = "exceeds_budget"
        details = f"cgroup v{version} memory limit {limit_mb} MB exceeds 2048 MB budget"

    return CGroupMemorySnapshot(
        cgroup_version=version,
        limit_bytes=limit_bytes,
        limit_mb=limit_mb,
        current_bytes=current_bytes,
        current_mb=current_mb,
        peak_bytes=peak_bytes,
        peak_mb=peak_mb,
        is_unlimited=is_unlimited,
        is_capped_at_2gb=is_capped,
        status=status,
        details=details,
    )


def verify_container_memory_limit(
    max_allowed_bytes: int = TWO_GB_BYTES,
    cgroup_root: Path | None = None,
) -> tuple[bool, str, CGroupMemorySnapshot]:
    """Verify that effective container memory limit is enforced and <= max_allowed_bytes.

    Returns (is_valid, message, snapshot).
    """
    snapshot = read_cgroup_memory(cgroup_root)
    if snapshot.cgroup_version is None:
        return (
            False,
            f"Container cgroup verification BLOCKED: no cgroup filesystem ({snapshot.details})",
            snapshot,
        )

    if snapshot.is_unlimited:
        return (
            False,
            f"Container cgroup verification FAILED: memory limit is UNLIMITED ({snapshot.details})",
            snapshot,
        )

    if snapshot.limit_bytes is None or snapshot.limit_bytes > max_allowed_bytes:
        return (
            False,
            f"Container cgroup verification FAILED: limit {snapshot.limit_mb} MB exceeds {round(max_allowed_bytes / (1024*1024), 2)} MB budget",
            snapshot,
        )

    return (
        True,
        f"Container cgroup verification PASSED: cgroup v{snapshot.cgroup_version} limit enforced at {snapshot.limit_mb} MB (<= 2048 MB)",
        snapshot,
    )


def get_process_rss_mb() -> float:
    """Measure current process resident set size (RSS) in MB using OS APIs."""
    # 1. Linux /proc/self/status VmRSS
    proc_status = Path("/proc/self/status")
    if proc_status.exists():
        try:
            for line in proc_status.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    # Value in kB
                    return round(float(parts[1]) / 1024.0, 2)
        except Exception:
            pass

    # 2. Windows GetProcessMemoryInfo WorkingSetSize
    if os.name == "nt":
        try:
            pmc = PROCESS_MEMORY_COUNTERS()
            pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            fn = ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
            fn.restype = wintypes.BOOL
            h = ctypes.windll.kernel32.GetCurrentProcess()
            if fn(h, ctypes.byref(pmc), ctypes.sizeof(PROCESS_MEMORY_COUNTERS)):
                return round(pmc.WorkingSetSize / (1024.0 * 1024.0), 2)
        except Exception:
            pass

    # 3. POSIX resource fallback
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2)
    except Exception:
        pass

    return 0.0


def get_cgroup_peak_mb(cgroup_root: Path | None = None) -> float | None:
    """Measure peak cgroup memory in MB if active.

    Returns None when cgroup is not present. NEVER returns host/process RSS,
    ensuring host memory is never reported as container cgroup memory.
    """
    snap = read_cgroup_memory(cgroup_root)
    return snap.peak_mb


def get_runtime_memory_profile(
    during_model_execution: bool = False,
    cgroup_root: Path | None = None,
) -> dict[str, Any]:
    """Capture a unified runtime memory telemetry profile."""
    snapshot = read_cgroup_memory(cgroup_root)
    process_rss = get_process_rss_mb()

    if snapshot.cgroup_version is not None and snapshot.peak_mb is not None:
        cgroup_peak = snapshot.peak_mb
        cgroup_source = f"cgroup_v{snapshot.cgroup_version}"
    else:
        cgroup_peak = None
        cgroup_source = None

    if Path("/proc/self/status").exists():
        host_source = "linux_proc_status_rss"
    elif os.name == "nt":
        host_source = "windows_working_set"
    else:
        host_source = "posix_getrusage"

    return {
        "during_model_execution": during_model_execution,
        "memory_source": cgroup_source or host_source,
        "cgroup_memory_source": cgroup_source,
        "peak_cgroup_memory_mb": cgroup_peak,
        "peak_memory_mb": cgroup_peak if cgroup_peak is not None else process_rss,
        "host_process_rss_mb": process_rss,
        "process_rss_mb": process_rss,
        "host_memory_source": host_source,
        "cgroup_enforced_2gb": snapshot.is_capped_at_2gb,
        "cgroup_verification_status": snapshot.status,
        "cgroup_snapshot": snapshot.to_dict(),
    }
