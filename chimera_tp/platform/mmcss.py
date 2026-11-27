"""A cooperative MMCSS lane for a thread owned by the calling application."""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os


@contextmanager
def interactive_thread(task: str = "Window Manager"):
    """Request bounded interactive scheduling for this thread until the context exits."""
    state = {"registered": False, "task": task, "reverted": False}
    handle = None
    if os.name == "nt":
        try:
            avrt = ctypes.WinDLL("avrt", use_last_error=True)
            register = avrt.AvSetMmThreadCharacteristicsW
            register.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
            register.restype = wintypes.HANDLE
            revert = avrt.AvRevertMmThreadCharacteristics
            revert.argtypes = [wintypes.HANDLE]
            revert.restype = wintypes.BOOL
            index = wintypes.DWORD()
            handle = register(task, ctypes.byref(index))
            state["registered"] = bool(handle)
            if not handle:
                state["winerror"] = ctypes.get_last_error()
        except OSError as exc:
            state["error"] = str(exc)
    try:
        yield state
    finally:
        if handle:
            state["reverted"] = bool(revert(handle))
            if not state["reverted"]:
                state["winerror"] = ctypes.get_last_error()
