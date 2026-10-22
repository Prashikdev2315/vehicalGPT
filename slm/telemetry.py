"""Process and cgroup memory telemetry utilities."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

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


def get_process_rss_mb() -> float:
    """Measure resident set size (RSS) in MB using cgroups on Linux or OS APIs on Windows."""
    # 1. Linux container cgroup v2
    cg2 = Path("/sys/fs/cgroup/memory.current")
    if cg2.exists():
        try:
            return round(int(cg2.read_text().strip()) / (1024.0 * 1024.0), 2)
        except Exception:
            pass

    # 2. Linux container cgroup v1
    cg1 = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
    if cg1.exists():
        try:
            return round(int(cg1.read_text().strip()) / (1024.0 * 1024.0), 2)
        except Exception:
            pass

    # 3. Windows GetProcessMemoryInfo WorkingSetSize
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

    # 4. POSIX resource fallback
    try:
        import resource
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 2)
    except Exception:
        pass

    return 0.0


def get_cgroup_peak_mb() -> float:
    """Measure peak resident set size (RSS) or peak cgroup memory in MB."""
    # 1. Linux container cgroup v2 peak
    cg2 = Path("/sys/fs/cgroup/memory.peak")
    if cg2.exists():
        try:
            return round(int(cg2.read_text().strip()) / (1024.0 * 1024.0), 2)
        except Exception:
            pass

    # 2. Linux container cgroup v1 max usage
    cg1 = Path("/sys/fs/cgroup/memory/memory.max_usage_in_bytes")
    if cg1.exists():
        try:
            return round(int(cg1.read_text().strip()) / (1024.0 * 1024.0), 2)
        except Exception:
            pass

    # Fallback to current RSS
    return get_process_rss_mb()
