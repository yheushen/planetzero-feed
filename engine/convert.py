"""From a 24-hour PM2.5 average to each index, and back (SPEC section 18): NEA's PSI, DOE's API, the US AQI by the US EPA's lines
of 2024 and by the older lines some apps still use. The lines live in engine/schema/scales.json ("conversions"), shared with the
page (web/src/convert.ts), which is tested against the same table (evals/feed, F18).

    to_index(130.7, "psi")   -> 180        to_pm25(174, "api") -> 130.7
"""
import json
import math
import os

CONVERSIONS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema", "scales.json"), encoding="utf-8"))["conversions"]
SCALES = tuple(k for k in CONVERSIONS if k != "note")


def whole(v):
    """Whole points, halves up (as NEA rounds; Python's round() would take 96.5 to 96)."""
    return math.floor(v + 0.5)


def prepared(conc, how):
    """The concentration as each agency reads it before its formula: a whole number (NEA), 1 decimal (DOE), or truncated to
    1 decimal (the US EPA)."""
    if how == "whole":
        return whole(conc)
    if how == "1 decimal":
        return math.floor(round(conc * 10, 6) + 0.5) / 10
    return math.floor(round(conc * 10, 6)) / 10


def _at(seg, c):
    if "index" in seg:
        lo, hi, (ilo, ihi) = seg["from"], seg["to"], seg["index"]
        return ilo + (c - lo) * (ihi - ilo) / (hi - lo)
    return seg["slope"] * (c - seg["minus"]) + seg["plus"]


def _span(seg):
    """The index range a segment covers."""
    return tuple(seg["index"]) if "index" in seg else (_at(seg, seg["from"]), _at(seg, seg["to"]))


def to_index(conc, scale):
    """The index for a 24-hour PM2.5 average in µg/m³, a whole point, halves up. Above the last segment its line goes on."""
    conv = CONVERSIONS[scale]
    c = max(0.0, prepared(float(conc), conv["concentration"]))
    segs = conv["segments"]
    for seg in segs:
        if c <= seg["to"]:
            return whole(_at(seg, max(c, seg["from"])))
    return whole(_at(segs[-1], c))


def to_pm25(index, scale):
    """The 24-hour PM2.5 average in µg/m³ (1 decimal) that gives this index: the inverse of to_index."""
    segs = CONVERSIONS[scale]["segments"]
    i = max(0.0, float(index))
    for seg in segs:
        lo, hi = _span(seg)
        if i <= hi + 0.5:   # whole points: 100 is the top of 51 to 100.08
            i = max(i, lo)
            break
    else:
        seg = segs[-1]
    if "index" in seg:
        (ilo, ihi) = seg["index"]
        c = seg["from"] + (i - ilo) * (seg["to"] - seg["from"]) / (ihi - ilo)
    else:
        c = (i - seg["plus"]) / seg["slope"] + seg["minus"]
    return math.floor(c * 10 + 0.5) / 10


def table(rows=(10, 25, 40, 55, 60, 75, 100, 130, 150, 200, 300)):
    """SPEC section 18's table: [(µg/m³, PSI, API, US AQI 2024, US AQI older)]."""
    return [(r, to_index(r, "psi"), to_index(r, "api"), to_index(r, "us_aqi"), to_index(r, "us_aqi_older")) for r in rows]


if __name__ == "__main__":
    for row in table():
        print(*row)
