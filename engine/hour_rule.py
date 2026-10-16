# km copied from ~/projects/05_planet-zero/haze-logger/dashboard.py on 2026-10-15; changed: nothing.
"""The Malaysia hour (invariant 3).

Malaysia's monitors measure every hour but DOE publishes only the 24-hour index. The hour comes from the
nearest open community sensor within 10 km, named, with its distance, and never called a government monitor.
  1. Sensors within 10.0 km of the place.
  2. Of those, the nearest whose latest reading is at most 3 hours old.
  3. Else the nearest whose latest reading is at most 8 hours old (the page marks it late).
  4. Else none: the page leads with DOE's index and says why. An hour is never invented.
The other sensors within 10 km that read the same hour are listed, so a reader can see if they agree.
"""
import datetime as dt
import math

from bands import band, earlier
from sources import openaq_credit

RADIUS_KM = 10.0
FRESH_H = 3
OLDEST_H = 8
SUSPECT_OVER = 55      # µg/m³; the same rule as Earth's monitors (engine/earth.py, session 7bc part 82)
SUSPECT_MAX = 1000
SUSPECT_KM = 50
NO_SENSOR = "No open sensor is within 10 km of here, and Malaysia publishes only the 24-hour index."
NO_RECENT = "The open sensors within 10 km of here have no reading in the last 8 hours, and Malaysia publishes only the 24-hour index."
NO_GOOD = ("The open sensor within 10 km of here reads 0 while the smoke around it is thick: likely a faulty sensor, so it is not used. "
           "Malaysia publishes only the 24-hour index.")


def km(a, b, c, d):
    return math.hypot((d - b) * math.cos(math.radians((a + c) / 2)) * 111.32, (c - a) * 110.57)


def hours_between(t_from, t_to):
    """Hours from one local time 'YYYY-MM-DDTHH:MM' to another."""
    return (dt.datetime.fromisoformat(t_to[:16]) - dt.datetime.fromisoformat(t_from[:16])).total_seconds() / 3600


def sensor_reading(s, t, distance):
    v = s["readings"][t]
    return {"status": "ok", "value": round(v, 1), "unit": "µg/m³", "scale": "hourly_pm25", "band": band(v, "hourly_pm25"), "window": "1h",
            "source": "OpenAQ", "source_type": "community sensor", "measured_at": t[:16] + "+08:00",
            "station": {"id": f"openaq-{s['id']}", "name": s["name"], "provider": s["provider"], "lat": s["lat"], "lon": s["lon"],
                        "owner": s.get("owner") or s["provider"] or "Unknown", "licence": s.get("licence") or "none given"},
            "distance_km": round(distance, 1), "credit": openaq_credit(s["provider"], s.get("owner"), s.get("licence"))}


def suspect(s, t, sensors, model):
    """A reading that disagrees with everything around it: 0 where the model at the place, or another sensor within 50 km at the
    same hour, says over 55 µg/m³; or any reading over 1,000. Never the hour, never listed beside it."""
    v = s["readings"].get(t)
    if v is None:
        return False
    if v > SUSPECT_MAX:
        return True
    if v > 0:
        return False
    if model is not None and model > SUSPECT_OVER:
        return True
    return any(o is not s and SUSPECT_OVER < (o["readings"].get(t) or 0) <= SUSPECT_MAX and km(s["lat"], s["lon"], o["lat"], o["lon"]) <= SUSPECT_KM for o in sensors)


def choose_hour(place, sensors, now, model=None):
    """(hour reading or 'none', other sensors within 10 km at the same hour). now is local 'YYYY-MM-DDTHH:MM'; model is the
    computer model's value at the place this hour, for the suspect rule (None when it has none)."""
    cands = []
    faulty = False
    for s in sensors:
        d = km(place["lat"], place["lon"], s["lat"], s["lon"])
        if d > RADIUS_KM:
            continue
        past = [t for t, v in s["readings"].items() if t[:16] <= now[:16] and v is not None]
        if past:
            t = max(past)
            if suspect(s, t, sensors, model):
                faulty = True
                continue
            cands.append((d, hours_between(t, now), t, s))
        else:
            cands.append((d, None, None, s))
    if not cands:
        return {"status": "none", "reason": NO_GOOD if faulty else NO_SENSOR}, []
    fresh = [c for c in cands if c[1] is not None and c[1] <= FRESH_H]
    usable = [c for c in cands if c[1] is not None and c[1] <= OLDEST_H]
    pool = fresh or usable
    if not pool:
        return {"status": "none", "reason": NO_GOOD if faulty else NO_RECENT}, []
    d, age, t, s = min(pool, key=lambda c: c[0])
    nearby = [sensor_reading(c[3], t, c[0]) for c in sorted(cands, key=lambda c: c[0])
              if c[3] is not s and t in c[3]["readings"] and c[3]["readings"][t] is not None and not suspect(c[3], t, sensors, model)]
    hour = sensor_reading(s, t, d)
    e = earlier(s["readings"], t, s["readings"][t], "hourly_pm25")
    if e:
        hour["earlier"] = e
    return hour, nearby
