"""Read allocation headroom without changing Windows settings or other apps."""
from __future__ import annotations

import ctypes
import os

import psutil


def allocation_headroom():
    physical = psutil.virtual_memory().available
    if os.name != 'nt':
        return physical
    from ctypes import wintypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', wintypes.DWORD), ('load', wintypes.DWORD)] + [
            (name, ctypes.c_ulonglong) for name in (
                'total_physical', 'available_physical', 'total_commit', 'available_commit',
                'total_virtual', 'available_virtual', 'available_extended_virtual')]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise ctypes.WinError()
    return min(physical, status.available_commit)
