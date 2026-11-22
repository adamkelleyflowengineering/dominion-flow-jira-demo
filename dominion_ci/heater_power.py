"""Wing anti-icing heater power command (implements REQ-45163).

In detected icing the controller commands continuous power between 2.4 kW and
3.0 kW, scaled with liquid water content (LWC) and outside air temperature
(OAT). Outside icing it commands a small standby power (keeps the mat above
dew point) and never more than the 3.0 kW bus limit.
"""
from __future__ import annotations

MIN_ICING_KW = 2.4
MAX_KW = 3.0
STANDBY_KW = 0.15

LWC_FULL_SCALE_G_M3 = 1.0
OAT_COLDEST_C = -40.0
OAT_WARMEST_C = 5.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def heater_power_command(oat_c: float, lwc_g_m3: float, icing_detected: bool) -> float:
    """Return the commanded continuous heater power in kW."""
    if lwc_g_m3 < 0:
        raise ValueError("lwc_g_m3 cannot be negative")
    if not icing_detected:
        return STANDBY_KW
    lwc_factor = _clamp(lwc_g_m3 / LWC_FULL_SCALE_G_M3, 0.0, 1.0)
    cold_factor = _clamp((OAT_WARMEST_C - oat_c) / (OAT_WARMEST_C - OAT_COLDEST_C), 0.0, 1.0)
    demand = MIN_ICING_KW + (MAX_KW - MIN_ICING_KW) * (0.6 * lwc_factor + 0.4 * cold_factor)
    return round(_clamp(demand, MIN_ICING_KW, MAX_KW), 3)
