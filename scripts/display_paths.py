"""Report active Windows scan-out targets using the CCD API (wingdi.h)."""

import ctypes as ct
from ctypes import wintypes as w
import json
import os


class Luid(ct.Structure):
    _fields_ = [("low", w.DWORD), ("high", w.LONG)]


class Rational(ct.Structure):
    _fields_ = [("numerator", w.UINT), ("denominator", w.UINT)]


class Source(ct.Structure):
    _fields_ = [("adapter", Luid), ("id", w.UINT), ("mode", w.UINT), ("status", w.UINT)]


class Target(ct.Structure):
    _fields_ = [("adapter", Luid), ("id", w.UINT), ("mode", w.UINT), ("technology", w.UINT),
                ("rotation", w.UINT), ("scaling", w.UINT), ("rate", Rational),
                ("scan", w.UINT), ("available", w.BOOL), ("status", w.UINT)]


class DisplayPath(ct.Structure):
    _fields_ = [("source", Source), ("target", Target), ("flags", w.UINT)]


class Header(ct.Structure):
    _fields_ = [("type", w.UINT), ("size", w.UINT), ("adapter", Luid), ("id", w.UINT)]


class TargetName(ct.Structure):
    _fields_ = [("header", Header), ("flags", w.UINT), ("technology", w.UINT), ("manufacturer", w.WORD),
                ("product", w.WORD), ("connector", w.UINT), ("friendly", w.WCHAR * 64),
                ("path", w.WCHAR * 128)]


class AdapterName(ct.Structure):
    _fields_ = [("header", Header), ("path", w.WCHAR * 128)]


def active_displays() -> list[dict]:
    if os.name != "nt":
        raise OSError("Windows display configuration API required")
    assert ct.sizeof(DisplayPath) == 72 and ct.sizeof(TargetName) == 420
    api = ct.windll.user32
    for _ in range(4):
        count, modes = w.UINT(), w.UINT()
        rc = api.GetDisplayConfigBufferSizes(2, ct.byref(count), ct.byref(modes))
        if rc:
            raise ct.WinError(rc)
        paths = (DisplayPath * count.value)()
        # Mode records are not inspected. Each DISPLAYCONFIG_MODE_INFO occupies 64 B.
        mode_data = (ct.c_uint64 * (modes.value * 8))()
        rc = api.QueryDisplayConfig(2, ct.byref(count), paths, ct.byref(modes), mode_data, None)
        if rc == 122:
            continue
        if rc:
            raise ct.WinError(rc)
        break
    else:
        raise RuntimeError("Display configuration changed repeatedly")
    result = []
    for entry in paths[:count.value]:
        target = entry.target
        name, adapter = TargetName(), AdapterName()
        name.header = Header(2, ct.sizeof(name), target.adapter, target.id)
        adapter.header = Header(4, ct.sizeof(adapter), target.adapter, 0)
        for query in (name, adapter):
            rc = api.DisplayConfigGetDeviceInfo(ct.byref(query))
            if rc:
                raise ct.WinError(rc)
        device = adapter.path.upper()
        pci = device.split("#")[1] if "#" in device else device
        result.append({"monitor": name.friendly, "target_id": target.id, "adapter_pci": pci,
                       "adapter_luid": f"{target.adapter.high & 0xffffffff:08x}:{target.adapter.low:08x}",
                       "connector": {4:"DVI",5:"HDMI",10:"DisplayPort",11:"embedded DisplayPort"}.get(
                           target.technology, str(target.technology)),
                       "hz": round(target.rate.numerator / target.rate.denominator, 3)
                       if target.rate.denominator else None})
    return result


if __name__ == "__main__":
    print(json.dumps(active_displays()))
