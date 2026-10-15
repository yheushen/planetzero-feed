# nea_hourly_band and api_band copied from ~/projects/05_planet-zero/haze-logger/dashboard.py on 2026-10-15; changed:
# the edges and words now come from engine/schema/scales.json (SPEC section 6), so engine, page and connector share them.
"""Bands for every scale, and NEA's PSI from 24-hour PM2.5 (the conversions themselves are in convert.py)."""
import json
import os

SCALES = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema", "scales.json"), encoding="utf-8"))


def whole(value):
    """Numbers are rounded to whole numbers before banding, so the band always matches the number shown."""
    return int(float(value) + 0.5)


def band(value, scale):
    v = whole(value)
    for b in SCALES[scale]["bands"]:
        if v >= b["min"] and (b["max"] is None or v <= b["max"]):
            return b["word"]
    raise ValueError(f"{value} is outside the {scale} scale")


def psi_from_pm25(conc):
    """NEA's PSI sub-index for a 24-hour PM2.5 average: straight lines between its breakpoints (engine/convert.py, session 6)."""
    import convert
    return convert.to_index(conc, "psi")


def earlier(series, t, value, scale, hours=12):
    """'Check again in an hour' (docs/design/now-phone-malaysia.html): the worst reading of the same monitor or sensor in the
    `hours` before t, when its band is worse than now's: {value, band, measured_at}, else None. series: {local time: value}."""
    import datetime as dt
    lo = (dt.datetime.fromisoformat(t[:16]) - dt.timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M")
    past = [(v, u) for u, v in series.items() if v is not None and lo < u[:16] < t[:16]]
    if not past:
        return None
    v, u = max(past)
    words = [b["word"] for b in SCALES[scale]["bands"]]
    if words.index(band(v, scale)) <= words.index(band(value, scale)):
        return None
    return {"value": round(v, 1), "band": band(v, scale), "measured_at": u[:16] + "+08:00"}
