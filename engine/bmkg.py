"""BMKG's hourly PM2.5 in Indonesia (session 8f, part 154), by the owner's decision of 18 Oct 2026, about 12:00 am: "if there is data, use
it. ignore the terms." Cowork advised against, as with Gemini, and the owner decided. BMKG's terms (8 Jul 2026) forbid automated collection
and republishing without its written permission (docs/TERMS-CHECK-INDONESIA-2026-10-18.md); docs/DATA-TERMS.md records the exception.

What it is for: where the smoke starts (Palangka Raya, Pontianak, Palembang) there is no open monitor, so the answers AI chats give about
the air there could not be checked. BMKG's stations are government monitors, measured each hour. Their readings go into Earth's monitors
(the map shows them, "BMKG, a government monitor") and the scorer reads them there (audit/measured.py, at_point).

Safeguards:
  - 1 request per page an hour, from the feed's Action only: the fetch runs only with BMKG_ON=1 in the environment (the Action sets it),
    never on a laptop or in a test; the answer is kept in the run's cache for the hour, so Earth built again in the same hour asks nothing;
    no retry.
  - A user agent naming planetzero.ai, with the contact address from CONTACT_EMAIL when it is set (never printed, never in the feed).
  - A 403 or 429 stops the fetch for 24 hours. The stop and its reason are kept in earth.json's monitors layer (`bmkg`), carried from run
    to run, and written in status.json's sources, so the next report says so.
  - Never in history/ (sources.NO_HISTORY), the record (record.py leaves BMKG's monitors out, named), a download (the History page's
    downloads hold only history/) or the connector (mcp/earth_answers.py leaves them out). Not used to adjust the smoke field or for
    Highest now, which the record and the connector keep (earth.open_monitors).
"""
import datetime as dt
import json
import os
import re

from transport import FetchError, get_bytes

TZ8 = dt.timezone(dt.timedelta(hours=8))
PROVIDER = "BMKG"
STOP_H = 24
LATE_H, DROP_H = 3, 8            # invariant 4, as Earth's other monitors
LICENCE = "None: BMKG's terms forbid automated collection; shown by the owner's decision of 18 Oct 2026"
CREDIT = ("Hourly PM2.5 from BMKG (Badan Meteorologi, Klimatologi, dan Geofisika), Indonesia, read from its public pages, shown by the owner's "
          "decision of 18 Oct 2026 although BMKG's terms forbid automated collection; never kept.")
PAGES = ("https://www.bmkg.go.id/kualitas-udara/pm25",)   # BMKG's public PM2.5 page: its station list is in the page itself


def user_agent():
    """planetzero.ai, and the contact address when CONTACT_EMAIL is set (addendum E). Never printed."""
    mail = os.environ.get("CONTACT_EMAIL", "").strip()
    return "planetzero.ai (air quality; https://planetzero.ai)" + (f"; contact {mail}" if mail else "")


def on():
    """Only the feed's Action fetches BMKG (BMKG_ON=1 in its environment)."""
    return os.environ.get("BMKG_ON", "").strip() == "1"


def clock(t):
    return f"{t.day} {t:%b}, {(t.hour % 12) or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def stopped(prev, now):
    """The stop carried from the last run (earth.json's monitors layer `bmkg`), while it lasts; else None."""
    b = (prev or {}).get("bmkg") or {}
    until = b.get("stopped_until")
    if b.get("status") == "stopped" and until and dt.datetime.fromisoformat(until) > now:
        return b
    return None


def stop_for(err, now):
    """A 403 or 429: the fetch stops for 24 hours, the reason in words. Anything else: None (a failed hour, tried again next hour)."""
    m = re.search(r"HTTP (\d{3})", str(err))
    if not m or m.group(1) not in ("403", "429"):
        return None
    until = now + dt.timedelta(hours=STOP_H)
    word = "refused our request (403)" if m.group(1) == "403" else "asked us to slow down (429)"
    return {"status": "stopped", "code": int(m.group(1)), "stopped_at": now.isoformat(timespec="minutes"), "stopped_until": until.isoformat(timespec="minutes"),
            "why": f"BMKG {word} at {clock(now)}: its fetch stops for {STOP_H} hours, until {clock(until)}."}


def fetch(url, cache, now):
    """1 request for 1 page this hour (no retry), kept in the run's cache for the hour; a second ask in the same hour reads the cache."""
    name = re.sub(r"[^A-Za-z0-9]+", "_", url)[-60:]
    path = os.path.join(cache, f"bmkg-{now:%Y-%m-%dT%H}-{name}") if cache else None
    if path and os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    body = get_bytes(url, {"User-Agent": user_agent(), "Accept": "application/json, text/html"}, tries=1, timeout=45)
    if path:
        os.makedirs(cache, exist_ok=True)
        for old in os.listdir(cache):   # only this hour's answer is kept
            if old.startswith("bmkg-") and not old.startswith(f"bmkg-{now:%Y-%m-%dT%H}"):
                os.remove(os.path.join(cache, old))
        with open(path, "wb") as f:
            f.write(body)
    return body


def monitors(now, cache, prev, parse=None, pages=None):
    """BMKG's readings as Earth's monitor rows, and the state for earth.json's monitors layer (`bmkg`): ([rows], state).
    prev: last run's monitors layer (for a stop that still lasts). Without BMKG_ON=1: nothing asked, state "off"."""
    pages = PAGES if pages is None else pages
    parse = parse or parse_page
    held = stopped(prev, now)
    if held:
        return [], {**held, "asked": False}
    if not on():
        return [], {"status": "off", "why": "BMKG is fetched by the feed's Action only.", "asked": False}
    rows, left = [], {"no_reading": 0, "old": 0}
    for url in pages:
        try:
            body = fetch(url, cache, now)
        except FetchError as e:
            stop = stop_for(e, now)
            if stop:
                return [], {**stop, "asked": True}
            return [], {"status": "failed", "why": f"BMKG did not answer at {clock(now)} ({str(e)[:80]}).", "asked": True}
        got, lo = parse(body, now)
        rows += got
        for k, v in lo.items():
            left[k] = left.get(k, 0) + v
    return rows, {"status": "ok", "count": len(rows), "left_out": left, "checked_at": now.isoformat(timespec="minutes"), "asked": True}


def row(name, lat, lon, value, when, now):
    """1 station's reading as Earth's monitor row; None when it is over DROP_H hours old (invariant 4)."""
    age = (now - when).total_seconds() / 3600
    if age > DROP_H or age < -0.5:
        return None
    return {"lat": lat, "lon": lon, "value": round(float(value), 1), "unit": "µg/m³", "window": "1h", "at": when.astimezone(TZ8).isoformat(timespec="minutes"),
            "late": age > LATE_H, "source": PROVIDER, "name": name, "owner": PROVIDER, "provider": PROVIDER, "licence": LICENCE, "monitor": True}


WIB = dt.timezone(dt.timedelta(hours=7))   # BMKG gives its hour in WIB (UTC+7), 1 hour behind Malaysia: "22.00 WIB"
NUXT = re.compile(r'<script[^>]*id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
FIELDS = {"LOKASI", "JAM", "PM25", "LAT", "LON"}


def stations_of(body):
    """The stations in BMKG's PM2.5 page as its own page reads them: the list in the page's Nuxt data (__NUXT_DATA__, a flat array whose
    objects point to their values by index). [{id, name, hour (WIB, 0 to 23), value, lat, lon}]."""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    m = NUXT.search(text)
    if not m:
        raise FetchError("BMKG's page has no station list (__NUXT_DATA__)")
    flat = json.loads(m.group(1))
    out = []
    for x in flat:
        if not (isinstance(x, dict) and FIELDS <= set(x)):
            continue
        v = {k: (flat[i] if isinstance(i, int) and 0 <= i < len(flat) else None) for k, i in x.items()}
        try:
            out.append({"id": re.sub(r"\.xml$", "", str(v.get("nama_file") or v["LOKASI"])), "name": str(v["LOKASI"]).strip(), "hour": int(v["JAM"]),
                        "value": None if v["PM25"] in (None, "", "-") else float(v["PM25"]), "lat": float(v["LAT"]), "lon": float(v["LON"])})
        except (TypeError, ValueError, KeyError):
            continue
    if not out:
        raise FetchError("BMKG's page lists no station")
    return out


def when_of(hour, now):
    """The time of BMKG's hour (WIB, no date given): the latest such hour at or before now."""
    w = now.astimezone(WIB).replace(minute=0, second=0, microsecond=0)
    t = w.replace(hour=hour)
    return t if t <= w else t - dt.timedelta(days=1)


def parse_page(body, now):
    """BMKG's page as Earth's monitor rows (Malaysia time) and what was left out: ([rows], {why: count}). A station with no reading, or
    with a reading over DROP_H hours old, gives no row: never a 0 or an older value."""
    rows, left = [], {"no_reading": 0, "old": 0}
    for st in stations_of(body):
        if st["value"] is None or st["value"] < 0:
            left["no_reading"] += 1
            continue
        r = row(st["name"], st["lat"], st["lon"], st["value"], when_of(st["hour"], now), now)
        if r is None:
            left["old"] += 1
            continue
        r["id"] = st["id"]
        rows.append(r)
    return rows, left


# ---------------------------------------------------------------- the last 48 hours, for the scorer (earth/bmkg-hours.json)
SERIES_H = 48
SERIES_FILE = "earth/bmkg-hours.json"


def series(prev, rows, now):
    """BMKG's readings of the last SERIES_H hours, each station's hours as they arrived, for the scorer: BMKG gives its hour 2 to 3 hours
    late, so an answer is checked against its own hour when that hour comes in (audit/score.py, "not yet"). In the live feed only, written
    over every hour: never in history/, the record, a download or the connector."""
    cut = (now - dt.timedelta(hours=SERIES_H)).astimezone(TZ8).strftime("%Y-%m-%dT%H:00")
    st = dict((prev or {}).get("stations") or {})
    ser = {k: {t: v for t, v in s.items() if t >= cut} for k, s in ((prev or {}).get("series") or {}).items()}
    for r in rows:
        st[r["id"]] = {"name": r["name"], "lat": round(r["lat"], 4), "lon": round(r["lon"], 4)}
        ser.setdefault(r["id"], {})[r["at"][:13] + ":00"] = r["value"]
    ser = {k: dict(sorted(s.items())) for k, s in sorted(ser.items()) if s}
    return {"schema_version": "1", "generated_at": now.isoformat(timespec="minutes"), "source": PROVIDER, "unit": "µg/m³", "window": "1h",
            "times": "Malaysia time; BMKG's own hour is WIB, 1 hour behind", "kind": "measured", "owner": "BMKG, a government monitor",
            "what": f"BMKG's hourly PM2.5 at its stations, the last {SERIES_H} hours as they arrived, for checking AI answers about Indonesia at their own hour.",
            "terms": LICENCE, "credit": CREDIT, "stations": {k: st[k] for k in sorted(st) if k in ser}, "series": ser}
