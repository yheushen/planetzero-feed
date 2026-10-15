# The "is Google right?" section of ~/projects/05_planet-zero/haze-logger/dashboard.py, copied on 2026-10-15 (the
# kill line of the research: Google within 30% of what was measured, per point, rolling 30 days). Changed: it returns
# check results for checks.json instead of HTML rows, names the places as the feed does, and takes the radius and the
# 30% rule as arguments so the tests can prove each one matters.
"""Our checks of numbers we may not republish (invariant 6). Google's own values never leave this module: only our
result does (the share of hours it was within 30% of the measured value, how many hours, against what, when).

Inputs are the private logger's files (`../haze-logger/data/` on the owner's Mac): Google's answers at 10 points,
and the public NEA and OpenAQ readings it keeps with them for 30 days and more.
"""
import csv
import datetime as dt
import glob
import math
import os

TZ8 = dt.timezone(dt.timedelta(hours=8))


def km(a, b, c, d):
    return math.hypot((d - b) * math.cos(math.radians((a + c) / 2)) * 111.32, (c - a) * 110.57)


def read_all(data, folder):
    rows = []
    for f in sorted(glob.glob(os.path.join(data, folder, "*.csv"))):
        rows += list(csv.DictReader(open(f, newline="", encoding="utf-8")))
    return rows


def place_id(point):
    return "sg-" + point[3:] if point.startswith("SG-") else "my-" + point.lower()


def fmt_day(t):
    return f"{t.day} {t.strftime('%b')}"


CLOSE = 66   # % of hours within 30%: at or above this, the verdict is "Close to"
WITHIN = 0.3   # how far off still counts as close: the research's kill line, shared with the AI chat audit (audit/score.py)


def within(value, measured, share=WITHIN):
    """Is value within `share` (30%) of what was measured? The Google check's measure, and the AI chat audit's."""
    return measured > 0 and abs(value / measured - 1) <= share


def verdict(share, median_ratio, sg):
    """Our check in words, for the number cell of Google's row: close, or which way it is off (the median of Google over measured)."""
    if share >= CLOSE:
        return "Close to NEA" if sg else "Close to the sensors"
    if median_ratio < 0.85:
        return "Reads low"
    if median_ratio > 1.15:
        return "Reads high"
    return "Often off"


def compute(data, now, radius_km=10.0, share=WITHIN, days=30):
    """Check results for checks.json from the logger's data folder, as of `now` (local ISO time)."""
    at = dt.datetime.fromisoformat(now).astimezone(TZ8)
    since = (at - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    cut = at.strftime("%Y-%m-%dT%H:%M")
    nea = {(r["datetime_sgt"][:16], "SG-" + r["region"]): float(r["pm25_1h"]) for r in read_all(data, "sg") if r.get("pm25_1h")}
    sens_h, sens_xy = {}, {}
    for r in read_all(data, "openaq"):
        if r.get("parameter") == "pm25" and r.get("value") and r.get("is_monitor") != "yes" and r.get("lat"):
            sens_h.setdefault(r["location_id"], {})[r["datetime_local"][:13] + ":00"] = float(r["value"])
            sens_xy[r["location_id"]] = (float(r["lat"]), float(r["lon"]))
    by_point = {}
    for r in read_all(data, "google"):
        if r.get("pm25") and since < r["datetime_local"][:16] <= cut:
            by_point.setdefault(r["point_id"], []).append(r)
    out = []
    for pid, rs in sorted(by_point.items()):
        la, lo = float(rs[0]["lat"]), float(rs[0]["lon"])
        if pid.startswith("SG-"):
            against = f"NEA's monitor in {pid[3:].title()}"
            pairs = [(float(r["pm25"]), nea[(r["datetime_local"][:16], pid)], r["datetime_local"][:16]) for r in rs if (r["datetime_local"][:16], pid) in nea]
        else:
            near = [s for s in sens_xy if km(la, lo, *sens_xy[s]) <= radius_km]
            against = (f"the community sensor within {radius_km:g} km" if len(near) == 1
                       else f"the mean of the {len(near)} community sensors within {radius_km:g} km" if near else f"no community sensor within {radius_km:g} km")
            pairs = []
            for r in rs:
                t = r["datetime_local"][:16]
                vs = [sens_h[s][t] for s in near if t in sens_h[s]]
                if vs:
                    pairs.append((float(r["pm25"]), sum(vs) / len(vs), t))
        pairs = [p for p in pairs if p[1] > 0]
        if not pairs:
            continue
        pct = 100 * sum(1 for g, m, t in pairs if within(g, m, share)) / len(pairs)
        ratios = sorted(g / m for g, m, t in pairs)
        k = len(ratios) // 2
        median = ratios[k] if len(ratios) % 2 else (ratios[k - 1] + ratios[k]) / 2
        first = dt.datetime.fromisoformat(min(p[2] for p in pairs))
        last = dt.datetime.fromisoformat(max(p[2] for p in pairs))
        value = int(pct + 0.5)
        out.append({
            "id": f"google-within-30pct-{place_id(pid)}",
            "subject": "Google",
            "place_id": place_id(pid),
            "metric": "share_within_30pct",
            "value": value,
            "unit": "% of hours",
            "window_days": days,
            "hours_compared": len(pairs),
            "against": against,
            "text": f"Google's estimate was within 30% of {against} in {value}% of {len(pairs)} hours, {fmt_day(first)} to {fmt_day(last)}.",
            "verdict": verdict(value, median, pid.startswith("SG-")),
            "median_ratio": round(median, 2),
            "computed_at": at.strftime("%Y-%m-%dT%H:%M+08:00"),
            "data_from": first.strftime("%Y-%m-%dT%H:%M+08:00"),
            "data_to": last.strftime("%Y-%m-%dT%H:%M+08:00"),
        })
    return out
