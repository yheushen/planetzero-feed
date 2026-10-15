#!/usr/bin/env python3
# The run order (fetch every source, each independent; merge; write a status file) follows
# ~/projects/05_planet-zero/haze-logger/logger.py (2026-10-15). Changed: sources run in parallel threads, the feed is
# built from this run's answers only (a failed fetch is "missing", never an old value), and every file is checked
# against engine/schema/ and the allow list before it is written.
"""Builds the feed: now.json, outlook.json, grid.json, checks.json, status.json and history/.

    python engine/build_feed.py --out web/public/feed            # live, now
    python engine/build_feed.py --out web/public/feed --offline  # replay of 15 Oct 2026, 4:12 am, from engine/tests/recorded/
    python engine/build_feed.py --out DIR --at 2026-10-15T04:12+08:00 --offline

Needs OPENAQ_KEY and FIRMS_MAP_KEY for a live run (.env, or the environment on GitHub).
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bands  # noqa: E402
import checks  # noqa: E402
import credits  # noqa: E402
import fetchers  # noqa: E402
import grid_spec  # noqa: E402
import history  # noqa: E402
import hour_rule  # noqa: E402
import publish  # noqa: E402
import sources  # noqa: E402
import transport  # noqa: E402
from envfile import ROOT, load_env  # noqa: E402

TZ8 = dt.timezone(dt.timedelta(hours=8))
REPLAY_AT = "2026-10-15T04:12+08:00"
# the private logger's data on the owner's Mac: Google's answers for our checks (only our results are published)
LOGGER_DATA = os.environ.get("LOGGER_DATA") or os.path.join(os.path.dirname(ROOT), "haze-logger", "data")
SCHEMA = os.path.join(HERE, "schema")


earlier = bands.earlier   # for evals/feed (F13)


def stamp(t):
    return t.astimezone(TZ8).strftime("%Y-%m-%dT%H:%M+08:00")


def clock(t):
    """'4:12 am', the way the page says times."""
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def months_back(now, days=3):
    return sorted({(now - dt.timedelta(days=d)).strftime("%Y-%m") for d in range(days + 1)})


# ---------------------------------------------------------------- readings
def reading(value, unit, scale, window, source, source_type, t, station, credit):
    return {"status": "ok", "value": value, "unit": unit, "scale": scale, "band": bands.band(value, scale), "window": window, "source": source,
            "source_type": source_type, "measured_at": t[:16] + "+08:00", "station": station, "credit": credit}


def missing(source, reason, now):
    return {"status": "missing", "source": source, "reason": reason, "checked_at": stamp(now)}


def latest(rows, key, field, cut):
    """The newest row for key whose field has a value, at or before cut."""
    best = None
    for r in rows:
        if r[key[0]] == key[1] and r.get(field) not in (None, "") and r["t"] <= cut and (best is None or r["t"] > best["t"]):
            best = r
    return best


def singapore_place(p, nea, now):
    st = {"id": p["source_id"], "name": p["short"], "lat": p["lat"], "lon": p["lon"]}
    if isinstance(nea, Exception):
        why = f"NEA did not answer at {clock(now)}."
        return missing("NEA", why, now), missing("NEA", why, now)
    cut = now.strftime("%Y-%m-%dT%H:%M")
    h = latest(nea, ("region", p["source_id"]), "pm25_1h", cut)
    i = latest(nea, ("region", p["source_id"]), "psi_24h", cut)
    hour = (reading(h["pm25_1h"], "µg/m³", "hourly_pm25", "1h", "NEA", "government monitor", h["t"], st, sources.CREDIT["NEA"]) if h
            else missing("NEA", f"NEA's answer at {clock(now)} had no hourly reading for {p['short']}.", now))
    if h:
        e = bands.earlier({r["t"]: r["pm25_1h"] for r in nea if r["region"] == p["source_id"] and r["t"] <= cut}, h["t"], h["pm25_1h"], "hourly_pm25")
        if e:
            hour["earlier"] = e
    index = (reading(i["psi_24h"], "PSI", "psi", "24h", "NEA", "government monitor", i["t"], st, sources.CREDIT["NEA"]) if i
             else missing("NEA", f"NEA's answer at {clock(now)} had no PSI for {p['short']}.", now))
    return hour, index


def malaysia_place(p, doe, oaq, now):
    cut = now.strftime("%Y-%m-%dT%H:%M")
    if isinstance(doe, Exception):
        index = missing("DOE", f"DOE did not answer at {clock(now)}.", now)
    else:
        stations, rows, _ = doe
        r = latest(rows, ("station_id", p["source_id"]), "api", cut)
        st = {"id": p["source_id"], "name": p["short"], "lat": p["lat"], "lon": p["lon"]}
        index = (reading(r["api"], "API", "api", "24h", "DOE", "government monitor", r["t"], st, sources.CREDIT["DOE"]) if r
                 else missing("DOE", f"DOE's answer at {clock(now)} had no index for {p['short']}.", now))
    if isinstance(oaq, Exception):
        return {"status": "missing", "source": "OpenAQ", "reason": f"OpenAQ, which carries the community sensors, did not answer at {clock(now)}.",
                "checked_at": stamp(now)}, index, []
    hour, nearby = hour_rule.choose_hour(p, oaq[0], cut)
    return hour, index, nearby


def model_row(p, cams, now):
    if isinstance(cams, Exception):
        return missing("CAMS", f"The computer model (CAMS, via Open-Meteo) did not answer at {clock(now)}.", now)
    t = now.strftime("%Y-%m-%dT%H:00")
    v = cams.get(p["id"], {}).get(t)
    if v is None:
        return missing("CAMS", f"The computer model gave nothing for {p['short']} at {clock(now.replace(minute=0))}.", now)
    return reading(round(v, 1), "µg/m³", "hourly_pm25", "1h", "CAMS", "computer model", t,
                   {"id": f"cams-{p['id']}", "name": "CAMS model grid", "lat": p["lat"], "lon": p["lon"]}, sources.CREDIT["CAMS"])


AQICN_KM = 1.0   # aqicn relays DOE's monitors at DOE's own coordinates; its city-level stations are left out


def aqicn_station(p, stations):
    """The aqicn station that relays this place's monitor: NEA's region by name ("Central, Singapore"), DOE's monitor by place."""
    if p["country"] == "SG":
        return next((s for s in stations if s["name"].strip().lower() == f"{p['short']}, singapore".lower()), None)
    near = [(hour_rule.km(p["lat"], p["lon"], s["lat"], s["lon"]), s) for s in stations]
    near = [x for x in near if x[0] <= AQICN_KM]
    return min(near, key=lambda x: x[0])[1] if near else None


def aqicn_row(p, got, now):
    """aqicn's current value for the place's monitor, credited to aqicn and to NEA or DOE; None when aqicn has no such station."""
    if isinstance(got, Exception):
        return missing("aqicn", f"aqicn did not answer at {clock(now)}.", now)
    s = aqicn_station(p, got)
    if s is None:
        return None
    agency = "NEA" if p["country"] == "SG" else "DOE"
    # In Singapore aqicn converts NEA's PM2.5 to US AQI. In Malaysia it shows DOE's API number itself (176 against DOE's 176,
    # Cheras, 15 Oct, 7 pm), coloured as US AQI: so it is banded on the API scale (run 2 review, item 2).
    unit, scale = ("US AQI", "us_aqi") if agency == "NEA" else ("API", "api")
    r = reading(s["aqi"], unit, scale, "24h", "aqicn", "government monitor", s["t"],
                {"id": f"aqicn-{s['uid']}", "name": s["name"], "lat": s["lat"], "lon": s["lon"]}, sources.aqicn_credit(agency))
    r["relayed_from"] = agency
    return r


# ---------------------------------------------------------------- outlook
PSI_WORDS = [b["word"] for b in bands.SCALES["psi"]["bands"]]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def turned(a, b, by=45):
    """Has the wind turned by `by` degrees or more? Angles wrap: 350 and 20 are 30 apart."""
    if a is None or b is None:
        return False
    d = abs(a - b) % 360
    return min(d, 360 - d) >= by


def why_line(days, weather):
    """1 line on why the outlook changes, only when the model's wind or rain explains it (SPEC section 8).
    Rain can explain easing, never worse air; a turn of the wind can explain either."""
    if not days or not weather:
        return None
    first = PSI_WORDS.index(days[0]["band"])
    k = next((i for i in range(1, len(days)) if PSI_WORDS.index(days[i]["band"]) != first), None)
    if k is None:
        return None
    w = {t: (d, r) for t, d, r in zip(weather.get("time", []), weather.get("wind_direction_10m_dominant", []), weather.get("precipitation_sum", []))}
    a, b = w.get(days[0]["valid_for"]), w.get(days[k]["valid_for"])
    if not a or not b:
        return None
    easing = PSI_WORDS.index(days[k]["band"]) < first
    reasons = (["with rain"] if easing and (b[1] or 0) >= 5 else []) + (["as the wind turns"] if turned(a[0], b[0]) else [])
    if not reasons:
        return None
    when = "tomorrow" if k == 1 else WEEKDAYS[dt.date.fromisoformat(days[k]["valid_for"]).weekday()]
    return f"{'Easing' if easing else 'Worse'} from {when} {' '.join(reasons)}."


def measured_index(out, p, day):
    """The 24-hour index that covers a whole day: NEA's PSI or DOE's API at midnight, else at 11 pm."""
    source = "nea_psi" if p["country"] == "SG" else "doe"
    nxt = (day + dt.timedelta(days=1)).isoformat()
    s = history.series(out, source, p["source_id"], sorted({day.strftime("%Y-%m"), nxt[:7]}))
    return s.get(nxt + "T00:00", s.get(day.isoformat() + "T23:00"))


def scorecard(out, places, today):
    """Last week's forecasts against what NEA and DOE measured: for each of the last 7 days, the forecast issued the
    day before, in the same band as the measured 24-hour index or not (SPEC section 8)."""
    logged = {}
    folder = os.path.join(out, "history", "outlook")
    for f in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        for sid, s in json.load(open(os.path.join(folder, f), encoding="utf-8"))["series"].items():
            logged.setdefault(sid, {}).update(s)
    issued = {t[:10] for s in logged.values() for t in s}
    first = dt.date.fromisoformat(min(issued)) if issued else today
    per = {}
    for p in places:
        right = of = 0
        for k in range(7, 0, -1):
            day = today - dt.timedelta(days=k)
            f = logged.get(f"{p['id']}|{day.isoformat()}", {}).get((day - dt.timedelta(days=1)).isoformat() + "T00:00")
            m = measured_index(out, p, day)
            if f is None or m is None:
                continue
            of += 1
            right += bands.band(f, "psi") == bands.band(m, "psi" if p["country"] == "SG" else "api")
        if of:
            per[p["id"]] = {"right": right, "of": of}
    if any(v["of"] >= 7 for v in per.values()):
        return {"status": "ready", "places": per}
    return {"status": "collecting", "from": (first + dt.timedelta(days=8)).isoformat()}


ADJ_DAYS = 3            # the review's rule: the last 3 days' ratio of the measured index to the model's estimate
ADJ_MIN_HOURS = 24      # fewer matched hours than this and the outlook is not adjusted (said so on the page)
ADJ_LIMITS = (0.5, 3.0)


def adjustment(measured, cams, now, days=ADJ_DAYS):
    """The ratio of the measured 24-hour index (NEA's PSI or DOE's API, hour by hour) to CAMS's own estimate on the same
    scale (its PM2.5 averaged over the same 24 hours, turned into PSI with NEA's breakpoints), over the last `days` days.
    A ratio of sums, so a few odd hours do not swing it; held between 0.5 and 3 (the raw ratio is kept)."""
    lo = (now - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M")
    cut = now.strftime("%Y-%m-%dT%H:%M")
    pairs = []
    for t, m in sorted(measured.items()):
        if m in (None, "") or not (lo < t[:16] <= cut):
            continue
        end = dt.datetime.fromisoformat(t[:13] + ":00")
        vals = [cams.get((end - dt.timedelta(hours=k)).strftime("%Y-%m-%dT%H:00")) for k in range(24)]
        vals = [v for v in vals if v is not None]
        if len(vals) < 18:   # as for a forecast day: 3 quarters of the hours
            continue
        pairs.append((t[:16], float(m), bands.psi_from_pm25(sum(vals) / len(vals))))
    model = sum(c for _, _, c in pairs)
    if len(pairs) < ADJ_MIN_HOURS or model <= 0:
        return {"status": "not adjusted", "hours": len(pairs),
                "reason": f"Only {len(pairs)} hours of readings to compare with the model in the last {days} days; {ADJ_MIN_HOURS} are needed."}
    raw = sum(m for _, m, _ in pairs) / model
    ratio = min(max(raw, ADJ_LIMITS[0]), ADJ_LIMITS[1])
    return {"status": "adjusted", "ratio": round(ratio, 2), "raw_ratio": round(raw, 2), "hours": len(pairs),
            "from": pairs[0][0] + "+08:00", "to": pairs[-1][0] + "+08:00"}


def adjusted(days, adj):
    """The days scaled by the adjustment and banded again; each keeps the model's own value as cams_value."""
    out = []
    for d in days:
        raw = d.get("cams_value", d["value"])
        v = min(500, bands.whole(raw * adj["ratio"])) if adj.get("status") == "adjusted" else raw
        out.append(dict(d, value=v, band=bands.band(v, "psi"), cams_value=raw))
    return out


def outlook(places, cams, now, out, weather=None):
    issued = stamp(now)
    method = ("CAMS PM2.5 (Copernicus, via Open-Meteo), averaged over each local day, turned into PSI with NEA's PM2.5 breakpoints, then adjusted "
              "to this week's readings: scaled by the last 3 days' ratio of the measured index (NEA's PSI or DOE's API) to the model's own "
              "estimate on the same scale. An estimate from a computer model.")
    res = {"schema_version": "1", "generated_at": issued, "issued_at": issued, "method": method, "places": {}, "scorecard": {"status": "collecting"}}
    if isinstance(cams, Exception):
        return res
    today = now.strftime("%Y-%m-%d")
    months = months_back(now, ADJ_DAYS + 1)
    log_rows, raw_rows = [], []
    for p in places:
        byday = {}
        for t, v in cams.get(p["id"], {}).items():
            if t[:10] >= today:
                byday.setdefault(t[:10], []).append(v)
        days = []
        for day in sorted(byday)[:5]:
            vs = byday[day]
            if len(vs) < 18:   # the model stops a few hours short of day 5; a day needs 3 quarters of its hours
                continue
            m = sum(vs) / len(vs)
            psi = bands.psi_from_pm25(m)
            days.append({"valid_for": day, "value": psi, "unit": "PSI", "scale": "psi", "band": bands.band(psi, "psi"), "window": "day", "source": "CAMS",
                         "source_type": "computer model", "issued_at": issued, "pm25_mean": round(m, 1), "hours": len(vs)})
        # the model's past hours: this run's answer, and what earlier runs kept
        past = {**history.series(out, "cams", p["id"], months), **cams.get(p["id"], {})}
        measured = history.series(out, "nea_psi" if p["country"] == "SG" else "doe", p["source_id"], months)
        adj = adjustment(measured, past, now)
        days = adjusted(days, adj)
        for d in days:
            log_rows.append((f"{p['id']}|{d['valid_for']}", today + "T00:00", d["value"]))
            raw_rows.append((f"{p['id']}|{d['valid_for']}", today + "T00:00", d["cams_value"]))
        res["places"][p["id"]] = {"days": days, "adjust": adj}
        why = why_line(days, None if isinstance(weather, Exception) or weather is None else weather.get(p["id"]))
        if why:
            res["places"][p["id"]]["why"] = why
    # log the day's forecasts, as shown (adjusted) and as the model gave them: the scorecard compares the shown one with what was
    # measured once its day is over; the model's own is kept so we can say whether adjusting helps
    history.merge(out, "outlook", {"source": "CAMS", "unit": "PSI", "window": "day",
                                   "note": "series 'place|valid day', time = the local day it was issued; adjusted to the week's readings",
                                   "credits": credits.block(["CAMS", "NEA", "DOE"], now)}, log_rows)
    history.merge(out, "outlook_cams", {"source": "CAMS", "unit": "PSI", "window": "day",
                                        "note": "series 'place|valid day', time = the local day it was issued; the model's own value",
                                        "credits": credits.block(["CAMS"], now)}, raw_rows)
    res["scorecard"] = scorecard(out, places, now.date())
    return res


# ---------------------------------------------------------------- grid
def weather_day(now, cache, places):
    """The day's wind direction and rain at every place, from the cache or fetched (1 call a day)."""
    p = os.path.join(cache, f"weather-{now.strftime('%Y-%m-%d')}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    w = fetchers.fetch_weather(places)
    os.makedirs(cache, exist_ok=True)
    json.dump(w, open(p, "w", encoding="utf-8"))
    return w


def grid_day(now, cache):
    """The day's grid from the cache, or fetched (about 8 minutes, once a day) and cached."""
    day = now.strftime("%Y-%m-%d")
    p = os.path.join(cache, f"grid-{day}.json")
    if os.path.exists(p):
        return json.load(open(p, encoding="utf-8"))
    g = fetchers.fetch_grid(day)
    os.makedirs(cache, exist_ok=True)
    for old in os.listdir(cache):
        if old.startswith("grid-") and old < f"grid-{(now - dt.timedelta(days=2)).strftime('%Y-%m-%d')}":
            os.remove(os.path.join(cache, old))
    tmp = p + ".tmp"
    json.dump(g, open(tmp, "w", encoding="utf-8"), separators=(",", ":"))
    os.replace(tmp, p)
    return g


def r1(v):
    return None if v is None else round(v, 1)


def grid(now, g, fires):
    hour = now.strftime("%Y-%m-%dT%H:00")
    at = hour + "+08:00"
    res = {"schema_version": "1", "generated_at": stamp(now), "valid_at": at}
    if isinstance(g, Exception):
        why = f"The grid (CAMS and Open-Meteo) did not answer at {clock(now)}."
        res["smoke"] = {"status": "missing", "reason": why, "unit": "µg/m³", "window": "1h", "source": "CAMS", "source_type": "computer model",
                        "measured_at": at, "credit": sources.CREDIT["CAMS"], "grid": grid_spec.BOX, "values": []}
        res["wind"] = {"status": "missing", "reason": why, "unit": "km/h", "window": "1h", "source": "Open-Meteo", "source_type": "computer model",
                       "measured_at": at, "credit": sources.CREDIT["Open-Meteo"], "fields": [{"name": "box", "grid": grid_spec.BOX, "speed": [], "direction": []}]}
    else:
        res["smoke"] = {"status": "ok", "unit": "µg/m³", "window": "1h", "source": "CAMS", "source_type": "computer model", "measured_at": at,
                        "credit": sources.CREDIT["CAMS"], "grid": grid_spec.BOX, "values": [r1((pt.get(hour) or [None])[0]) for pt in g["smoke"]]}
        fields = []
        for name, kind, spec in (("box", "wind", grid_spec.BOX), ("hemi", "hemi", grid_spec.HEMI)):
            vals = [pt.get(hour) or [None, None] for pt in g[kind]]
            fields.append({"name": name, "grid": spec, "speed": [r1(v[0]) for v in vals], "direction": [r1(v[1]) for v in vals]})
        res["wind"] = {"status": "ok", "unit": "km/h", "window": "1h", "source": "Open-Meteo", "source_type": "computer model", "measured_at": at,
                       "credit": sources.CREDIT["Open-Meteo"], "fields": fields}
    lo, hi = now - dt.timedelta(hours=24), now
    if isinstance(fires, Exception):
        res["fires"] = {"status": "missing", "reason": f"NASA FIRMS did not answer at {clock(now)}.", "unit": "detections", "window": "24h", "source": "FIRMS",
                        "source_type": "satellite", "measured_at": stamp(now), "from": stamp(lo), "to": stamp(hi), "credit": sources.CREDIT["FIRMS"], "cells": []}
    else:
        cells = {}
        for t, la, lo_, frp in fires:
            k = (round(la * 10) / 10, round(lo_ * 10) / 10)
            c = cells.setdefault(k, [0, 0.0])
            c[0] += 1
            c[1] = max(c[1], frp)
        res["fires"] = {"status": "ok", "unit": "detections", "window": "24h", "source": "FIRMS", "source_type": "satellite",
                        "measured_at": stamp(max(f[0] for f in fires)), "from": stamp(lo), "to": stamp(hi), "credit": sources.CREDIT["FIRMS"],
                        "cells": [[k[0], k[1], v[0], round(v[1], 1)] for k, v in sorted(cells.items())]}
    return res


# ---------------------------------------------------------------- checks
def checks_file(out, now, logger):
    """Our check results (shot 2). From the logger's data when it is here; otherwise the last results are kept,
    each still carrying the dates it covers, so nothing is passed off as new."""
    if logger and os.path.isdir(os.path.join(logger, "google")):
        items = checks.compute(logger, stamp(now))
    else:
        prev = os.path.join(out, "checks.json")
        items = json.load(open(prev, encoding="utf-8")).get("checks", []) if os.path.exists(prev) else []
    return {"schema_version": "1", "generated_at": stamp(now), "checks": items}


def checks_only(out, logger, at=None):
    """Only checks.json, from the private logger's data: how the private audit Action publishes our Google checks to the public
    feed, which holds no token for the logger. The public feed Action then keeps these results, each with the dates it covers."""
    now = dt.datetime.fromisoformat(at).astimezone(TZ8) if at else dt.datetime.now(TZ8).replace(second=0, microsecond=0)
    obj = checks_file(out, now, logger)
    obj["credits"] = credits.block(["NEA", "OpenAQ"], now, ours=("checks",))
    errors = validate({"checks": obj})
    if errors:
        raise SystemExit("checks.json breaks its contract, nothing written:\n  " + "\n  ".join(errors[:10]))
    os.makedirs(out, exist_ok=True)
    write_json(os.path.join(out, "checks.json"), obj)
    return obj


# ---------------------------------------------------------------- the run
def validate(feed):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    schemas = {}
    for f in os.listdir(SCHEMA):
        if f.endswith(".schema.json"):
            schemas[f.replace(".schema.json", "")] = json.load(open(os.path.join(SCHEMA, f), encoding="utf-8"))
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    errors = []
    for name, obj in feed.items():
        for e in Draft202012Validator(schemas[name], registry=reg).iter_errors(obj):
            errors.append(f"{name}.json: {e.message[:160]} at {'/'.join(str(x) for x in e.absolute_path)}")
    return errors


def write_json(path, obj, compact=False):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(publish.rounded(obj), f, ensure_ascii=False, indent=None if compact else 1, separators=(",", ":") if compact else None)
    os.replace(tmp, path)


def fetch_all(jobs, now):
    """Every source side by side: ({name: answer or the Exception}, {name: status})."""
    got = {}
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = {pool.submit(fn): name for name, fn in jobs.items()}
        for fut in cf.as_completed(futs):
            try:
                got[futs[fut]] = fut.result()
            except Exception as e:   # every source is independent: 1 failing never stops the others
                got[futs[fut]] = e
    status = {name: {"ok": not isinstance(v, Exception), "checked_at": stamp(now)} for name, v in got.items()}
    for name, v in got.items():
        if isinstance(v, Exception):
            status[name]["error"] = str(v)[:200]
    return got, status


def measured_only(out, at=None, transport_=None):
    """Only what was measured (NEA, DOE and the community sensors) merged into out/history/, nothing else written: what the AI
    chat audit scores against when the public feed is over 90 minutes old (audit/run.py). No grid, so it takes about a minute."""
    if transport_ is not None:
        transport.TRANSPORT = transport_
    now = dt.datetime.fromisoformat(at).astimezone(TZ8) if at else dt.datetime.now(TZ8).replace(second=0, microsecond=0)
    os.makedirs(out, exist_ok=True)
    got, status = fetch_all({"NEA": lambda: fetchers.fetch_singapore(now), "DOE": lambda: fetchers.fetch_malaysia(now),
                             "OpenAQ": lambda: fetchers.fetch_openaq(now)}, now)
    merge_history(out, got, status, now)
    return status


def build(out, at=None, transport_=None, cache=None, quiet=False, logger=None):
    if transport_ is not None:
        transport.TRANSPORT = transport_
    now = dt.datetime.fromisoformat(at).astimezone(TZ8) if at else dt.datetime.now(TZ8).replace(second=0, microsecond=0)
    cache = cache or os.path.join(ROOT, ".cache")
    places = json.load(open(os.path.join(HERE, "places.json"), encoding="utf-8"))["places"]
    os.makedirs(out, exist_ok=True)
    jobs = {"NEA": lambda: fetchers.fetch_singapore(now), "DOE": lambda: fetchers.fetch_malaysia(now), "OpenAQ": lambda: fetchers.fetch_openaq(now),
            "CAMS": lambda: fetchers.fetch_cams(places), "FIRMS": lambda: fetchers.fetch_firms(now), "aqicn": lambda: fetchers.fetch_aqicn(now),
            "Open-Meteo": lambda: grid_day(now, cache),
            "Open-Meteo daily": lambda: weather_day(now, cache, places)}
    got, status = fetch_all(jobs, now)
    merge_history(out, got, status, now)
    return finish_build(out, at, now, places, got, status, quiet, logger)


def merge_history(out, got, status, now):
    """history/: refill whatever the sources still keep (about 2 days), so skipped runs leave no gap. Only the sources in `got`."""
    if "NEA" in got and not isinstance(got["NEA"], Exception):
        rows = got["NEA"]
        status["NEA"]["hours_added"] = history.merge(out, "nea", {"source": "NEA", "unit": "µg/m³", "window": "1h", "note": "series = region, hourly PM2.5",
                                                            "credits": credits.block(["NEA"], now)},
                                                     [(r["region"], r["t"], r["pm25_1h"]) for r in rows])
        history.merge(out, "nea_psi", {"source": "NEA", "unit": "PSI", "window": "24h", "note": "series = region, 24-hour PSI", "credits": credits.block(["NEA"], now)},
                      [(r["region"], r["t"], r["psi_24h"]) for r in rows])
        status["NEA"]["latest"] = max(r["t"] for r in rows) + "+08:00"
    if "DOE" in got and not isinstance(got["DOE"], Exception):
        stations, rows, errs = got["DOE"]
        status["DOE"]["hours_added"] = history.merge(out, "doe", {"source": "DOE", "unit": "API", "window": "24h", "note": "series = DOE station id",
                                                            "credits": credits.block(["DOE"], now)},
                                                     [(r["station_id"], r["t"], r["api"]) for r in rows])
        status["DOE"]["latest"] = max(r["t"] for r in rows) + "+08:00"
        if errs:
            status["DOE"]["error"] = f"{len(errs)} of the hourly tables did not answer"
    if "OpenAQ" in got and not isinstance(got["OpenAQ"], Exception):
        sensors, errs = got["OpenAQ"]
        # only locations under an open licence are kept (none without a licence, none share-alike): each with its licence and owner
        kept = [s for s in sensors if s.get("licence") in sources.OPEN_LICENCES]
        locations = {s["id"]: {"name": s["name"], "provider": s["provider"], "owner": s["owner"], "licence": s["licence"], "attribution": s["owner"] or s["provider"],
                               "lat": s["lat"], "lon": s["lon"]} for s in kept}
        status["OpenAQ"]["hours_added"] = history.merge(out, "openaq", {"source": "OpenAQ", "unit": "µg/m³", "window": "1h",
                                                                        "note": "series = OpenAQ location id; community sensors under CC BY 4.0 or CC0 1.0 only",
                                                                        "credits": credits.block(["OpenAQ"], now), "locations": locations},
                                                        [(s["id"], t, v) for s in kept for t, v in s["readings"].items()])
        if errs:
            status["OpenAQ"]["error"] = f"{len(errs)} sensors did not answer"
    if "CAMS" in got and not isinstance(got["CAMS"], Exception):
        cut = now.strftime("%Y-%m-%dT%H:%M")
        status["CAMS"]["hours_added"] = history.merge(out, "cams", {"source": "CAMS", "unit": "µg/m³", "window": "1h", "note": "series = place id; model estimate",
                                                              "credits": credits.block(["CAMS"], now)},
                                                      [(pid, t, round(v, 1)) for pid, s in got["CAMS"].items() for t, v in s.items() if t <= cut])


def finish_build(out, at, now, places, got, status, quiet, logger):
    """now.json, outlook.json, grid.json, checks.json and the rest, from this run's answers (history/ already merged)."""
    # now.json: from this run's answers only (invariant 10)
    out_places = []
    for p in places:
        if p["country"] == "SG":
            hour, index = singapore_place(p, got["NEA"], now)
            nearby, rule = [], "nea_region"
        else:
            hour, index, nearby = malaysia_place(p, got["DOE"], got["OpenAQ"], now)
            rule = "sensor_within_10km"
        out_places.append({"id": p["id"], "country": p["country"], "name": p["name"], "short": p["short"], "region": p["region"], "lat": p["lat"],
                           "lon": p["lon"], "aliases": p["aliases"], "lead": "hour" if hour["status"] == "ok" else "index", "hour_rule": rule,
                           "hour": hour, "index": index, "nearby": nearby,
                           "others": [r for r in (model_row(p, got["CAMS"], now), aqicn_row(p, got["aqicn"], now)) if r is not None]})
    now_json = {"schema_version": "1", "generated_at": stamp(now)}
    if at:
        now_json["replay_of"] = stamp(now)
    now_json["sources"] = dict(sorted(status.items()))
    now_json["places"] = out_places
    now_json["credits"] = credits.block(sources.sources_in(now_json["places"]), now, ours=("advice",))
    feed = {"now": now_json, "outlook": outlook(places, got["CAMS"], now, out, got["Open-Meteo daily"]), "grid": grid(now, got["Open-Meteo"], got["FIRMS"]),
            "checks": checks_file(out, now, logger)}
    # every public JSON names the sources it holds, with each one's required credit line (docs/TERMS-CHECK-2026-10-15.md)
    feed["outlook"]["credits"] = credits.block(["CAMS", "NEA", "DOE", "Open-Meteo"], now)
    feed["grid"]["credits"] = credits.block(["CAMS", "Open-Meteo", "FIRMS"], now)
    feed["checks"]["credits"] = credits.block(["NEA", "OpenAQ"], now, ours=("checks",))
    sources.assert_allowed(feed)   # invariant 6: refuse, never publish
    errors = validate(feed)
    if errors:
        raise SystemExit("the feed breaks its contract, nothing written:\n  " + "\n  ".join(errors[:10]))
    for name, obj in feed.items():
        write_json(os.path.join(out, f"{name}.json"), obj, compact=(name == "grid"))
    write_json(os.path.join(out, "scales.json"), {**bands.SCALES, "credits": credits.block(["NEA", "DOE"], now, ours=("advice",))})
    write_json(os.path.join(out, "status.json"), {"run": stamp(now), "sources": now_json["sources"], "credits": credits.block(credits.ALL, now)})
    with open(os.path.join(out, "ATTRIBUTION.md"), "w", encoding="utf-8") as f:
        f.write(credits.attribution_md())
    if not quiet:
        print(json.dumps(now_json["sources"], indent=1))
        lead = sum(1 for p in out_places if p["lead"] == "hour")
        print(f"{len(out_places)} places, {lead} with an hour; written to {out}")
    return feed


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.environ.get("FEED_OUT", os.path.join(ROOT, "web", "public", "feed")))
    ap.add_argument("--at", help="build as of this local time, e.g. 2026-10-15T04:12+08:00")
    ap.add_argument("--offline", action="store_true", help="replay the answers recorded on 15 Oct 2026 (default time 4:12 am)")
    ap.add_argument("--cache", default=os.path.join(ROOT, ".cache"), help="where the day's globe grid is kept")
    ap.add_argument("--checks-only", action="store_true", help="write only checks.json, from the logger's data (the private audit Action)")
    ap.add_argument("--logger", default=LOGGER_DATA, help="the private logger's data folder, for our Google checks")
    a = ap.parse_args()
    load_env()
    if a.checks_only:
        n = len(checks_only(a.out, a.logger)["checks"])
        print(f"checks.json: {n} checks written to {a.out}")
        return
    if a.offline:   # a replay reads no private data unless LOGGER_DATA is set on purpose
        build(a.out, at=a.at or REPLAY_AT, transport_=transport.Replay(), cache=os.path.join(a.cache, "replay"), logger=os.environ.get("LOGGER_DATA"))
    else:
        build(a.out, at=a.at, cache=a.cache, logger=a.logger)


if __name__ == "__main__":
    main()
