# -*- coding: utf-8 -*-
"""THUY LOI AI - Reservoir Engine
Port of the Z-F-V interpolation logic recovered from the legacy XLA VBA modules.

Source: CodeZFV2027.xla / reconstructed VBA modules.
Default interpolation is piecewise linear. Per-reservoir boundary behavior
is preserved where it is explicit in the source modules.
"""
from __future__ import annotations
import json
import os
from bisect import bisect_right
from typing import Any, Dict, Optional, Tuple

_BASE = os.path.dirname(__file__)
with open(os.path.join(_BASE, "reservoir_curves.json"), "r", encoding="utf-8") as f:
    CURVES: Dict[str, Dict[str, Any]] = json.load(f)

ALIASES = {
    "PNinh2026": ["phu ninh", "phú ninh", "ho phu ninh", "hồ phú ninh", "c24"],
    "ThachBan2026": ["thach ban", "thạch bàn", "ho thach ban", "hồ thạch bàn"],
    "TruocDong2026": ["truoc dong", "trước đông", "ho truoc dong", "hồ trước đông"],
    "DongTien2026": ["dong tien", "đồng tiến", "ho dong tien", "hồ đồng tiến"],
    "DongNghe2026": ["dong nghe", "đồng nghệ", "ho dong nghe", "hồ đồng nghệ"],
    "VinhTrinh2026": ["vinh trinh", "vĩnh trinh", "ho vinh trinh", "hồ vĩnh trinh"],
    "VietAN2026": ["viet an", "việt an", "ho viet an", "hồ việt an"],
    "HocKhe2026": ["hoc khe", "học khe", "ho hoc khe", "hồ học khe"],
    "HoCau2026": ["ho cau", "hồ cầu", "ho cau 2026", "hồ cầu 2026"],
    "HoaTrung2026": ["hoa trung", "hoa trung", "ho hoa trung", "hồ hoa trung"],
}

def _norm(s: Any) -> str:
    import unicodedata, re
    x = "" if s is None else str(s)
    x = unicodedata.normalize("NFD", x)
    x = "".join(c for c in x if unicodedata.category(c) != "Mn")
    x = x.lower().replace("đ", "d")
    return re.sub(r"\s+", " ", x).strip()

def resolve_reservoir(facility: str) -> Optional[str]:
    n = _norm(facility)
    # Exact module display names first
    for key, meta in CURVES.items():
        if _norm(meta["name"]) == n:
            return key
    # Aliases / contained name
    for key, aliases in ALIASES.items():
        if any(a in n for a in aliases):
            return key
    # Module token fallback
    for key in CURVES:
        if _norm(key) in n:
            return key
    return None

def _linear(x: float, x1: float, y1: float, x2: float, y2: float) -> float:
    if x2 == x1:
        return y1
    return y1 + (x - x1) * (y2 - y1) / (x2 - x1)

def _interp(x: float, xs: list[float], ys: list[float], policy: str) -> Tuple[Optional[float], str]:
    if not xs or len(xs) != len(ys):
        return None, "invalid_curve"
    if x == xs[0]:
        return ys[0], "exact"
    if x == xs[-1]:
        return ys[-1], "exact"
    if x < xs[0] or x > xs[-1]:
        if policy == "strict":
            return None, "out_of_range"
        if policy == "clamp":
            return (ys[0], "clamped_low") if x < xs[0] else (ys[-1], "clamped_high")
        # linear extrapolation: same two end points as the HoaTrung VBA module
        if x < xs[0]:
            return _linear(x, xs[0], ys[0], xs[1], ys[1]), "extrapolated_low"
        return _linear(x, xs[-2], ys[-2], xs[-1], ys[-1]), "extrapolated_high"

    i = bisect_right(xs, x) - 1
    return _linear(x, xs[i], ys[i], xs[i+1], ys[i+1]), "interpolated"

def _curve_value(meta: Dict[str, Any], z: float, field: str) -> Tuple[Optional[float], str]:
    return _interp(z, meta["z_m"], meta[field], meta["out_of_range"])

def _volume_at_z(meta: Dict[str, Any], z: float) -> Tuple[Optional[float], str]:
    return _curve_value(meta, z, "v_m3")

def _area_at_z(meta: Dict[str, Any], z: float) -> Tuple[Optional[float], str]:
    return _curve_value(meta, z, "f_m2")

def _z_at_volume(meta: Dict[str, Any], volume: float) -> Tuple[Optional[float], str]:
    return _interp(volume, meta["v_m3"], meta["z_m"], meta["out_of_range"])

def calculate_state(facility: str, water_level: float, limits: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    key = resolve_reservoir(facility)
    if not key:
        return {"ok": False, "error": "Chưa có đường quan hệ Z-F-V cho công trình này.", "facility": facility}
    meta = CURVES[key]
    z = float(water_level)
    f, f_mode = _area_at_z(meta, z)
    v, v_mode = _volume_at_z(meta, z)
    result: Dict[str, Any] = {
        "ok": True,
        "reservoir_id": key,
        "reservoir": meta["name"],
        "source_module": meta["source_module"],
        "algorithm": meta["algorithm"],
        "out_of_range_policy": meta["out_of_range"],
        "water_level_m": z,
        "area_m2": f,
        "area_km2": (f / 1_000_000.0) if f is not None else None,
        "volume_m3": v,
        "volume_million_m3": (v / 1_000_000.0) if v is not None else None,
        "interpolation": {"area": f_mode, "volume": v_mode},
        "curve_range": {"z_min_m": meta["z_m"][0], "z_max_m": meta["z_m"][-1]},
    }

    limits = limits or {}
    mndbt = limits.get("mndbt")
    mndgc = limits.get("mndgc")
    result["limits"] = {"MNDBT": mndbt, "MNDGC": mndgc}

    if mndbt is not None:
        try:
            mndbt = float(mndbt)
            v_bt, bt_mode = _volume_at_z(meta, mndbt)
            f_bt, _ = _area_at_z(meta, mndbt)
            result["mndbt"] = {
                "z_m": mndbt, "volume_m3": v_bt,
                "volume_million_m3": v_bt/1_000_000 if v_bt is not None else None,
                "area_m2": f_bt, "area_km2": f_bt/1_000_000 if f_bt is not None else None,
                "mode": bt_mode,
            }
            if v is not None and v_bt is not None:
                result["volume_vs_mndbt_m3"] = v - v_bt
                result["fill_percent_vs_mndbt"] = (v / v_bt * 100) if v_bt else None
                result["remaining_to_mndbt_m3"] = max(0.0, v_bt - v)
        except (TypeError, ValueError):
            pass

    if mndgc is not None:
        try:
            mndgc = float(mndgc)
            v_gc, gc_mode = _volume_at_z(meta, mndgc)
            result["mndgc"] = {
                "z_m": mndgc, "volume_m3": v_gc,
                "volume_million_m3": v_gc/1_000_000 if v_gc is not None else None,
                "mode": gc_mode,
            }
            if v is not None and v_gc is not None:
                result["volume_vs_mndgc_m3"] = v - v_gc
        except (TypeError, ValueError):
            pass

    if mndbt is not None and mndgc is not None:
        if z > float(mndgc):
            result["technical_state"] = "above_mndgc"
        elif z >= float(mndbt):
            result["technical_state"] = "between_mndbt_mndgc"
        else:
            result["technical_state"] = "below_mndbt"
    elif mndbt is not None:
        result["technical_state"] = "at_or_above_mndbt" if z >= float(mndbt) else "below_mndbt"
    else:
        result["technical_state"] = "unknown"

    return result
