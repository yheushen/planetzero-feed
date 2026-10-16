# Copied from ~/projects/05_planet-zero/haze-logger/logger.py and backfill.py on 2026-10-15: log_singapore, log_malaysia,
# points/fetch_cams, log_firms, log_openaq/backfill_openaq. Changed: each returns rows instead of writing CSVs; every
# request goes through transport (live, recorded or replayed); everything is cut at the run's clock, so a replay of
# an earlier hour never sees later data; NEA reaches 3 days back so a 2-day gap always refills; OpenAQ takes each
# sensor's hourly averages (the end of the hour is the time), 60 hours back; FIRMS covers the globe's box.
# log_google and log_aqicn_daily are NOT copied: their sources may not enter the public feed (docs/DATA-TERMS.md). log_waqi's
# current-value call is (fetch_aqicn, session 3): aqicn's current value may be shown with credit, never kept in history/.
"""The public sources, 1 function each. Times are local (UTC+8) 'YYYY-MM-DDTHH:MM' strings."""
import csv
import datetime as dt
import os
import time
import urllib.parse

import grid_spec
import transport
from transport import FetchError, get_json, get_text

TZ8 = dt.timezone(dt.timedelta(hours=8))
DOE = "https://eqms.doe.gov.my/api3/publicportalapims/"
DOE_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://eqms.doe.gov.my/APIMS/main", "Accept": "application/json"}
NEA = "https://api-open.data.gov.sg/v2/real-time/api/"
OAQ = "https://api.openaq.org/v3/"
AQ = "https://air-quality-api.open-meteo.com/v1/air-quality"
FIRMS_BOX = "84,-15,130,16"   # west, south, east, north: the globe's 1 degree box
SG_REGIONS = ("north", "south", "east", "west", "central")


def local(t):
    return t.astimezone(TZ8).strftime("%Y-%m-%dT%H:%M")


def pause(seconds):
    """Be polite to live servers; replays do not wait."""
    if isinstance(transport.TRANSPORT, transport.Live):
        time.sleep(seconds)


# ---------------------------------------------------------------- Singapore: NEA via data.gov.sg
def fetch_singapore(now):
    """Rows (time, region, pm25_1h, pm25_24h, psi_24h) for today and the 2 days before, up to now."""
    rows = []
    cut = local(now)
    for back in (0, 1, 2):
        d = (now - dt.timedelta(days=back)).strftime("%Y-%m-%d")
        pm = get_json(NEA + "pm25?date=" + d)
        ps = get_json(NEA + "psi?date=" + d)
        pmh = {it["timestamp"][:16]: it["readings"].get("pm25_one_hourly", {}) for it in (pm.get("data", {}) or {}).get("items", []) or []}
        psh = {it["timestamp"][:16]: it["readings"] for it in (ps.get("data", {}) or {}).get("items", []) or []}
        for ts in sorted(set(pmh) | set(psh)):
            if ts > cut:
                continue
            a, b = pmh.get(ts, {}), psh.get(ts, {})
            for reg in SG_REGIONS:
                rows.append({"t": ts, "region": reg, "pm25_1h": a.get(reg), "pm25_24h": (b.get("pm25_twenty_four_hourly") or {}).get(reg),
                             "psi_24h": (b.get("psi_twenty_four_hourly") or {}).get(reg)})
        pause(1)
    if not rows:
        raise FetchError("NEA answered with no readings")
    return rows


# ---------------------------------------------------------------- Malaysia: DOE's API index
def fetch_malaysia(now):
    """(stations by id, rows (time, station id, api)). The hourly tables hold 25 hours per state; 2 per state cover 49 hours."""
    j = get_json(DOE + "mapcaqm", DOE_HEADERS)
    stations = {s["STATION_ID"]: s for s in j.get("data", []) or []}
    if not stations:
        raise FetchError("DOE answered with no stations")
    cut = local(now)
    rows = []
    for s in stations.values():
        if s.get("API") is not None and s.get("RECORD_DT") and s["RECORD_DT"][:16] <= cut:
            rows.append({"t": s["RECORD_DT"][:16], "station_id": s["STATION_ID"], "api": s["API"]})
    errors = []
    for sid in sorted({s["STATE_ID"] for s in stations.values()}):
        for back in (0, 24):
            t = (now - dt.timedelta(hours=back)).replace(minute=0, second=0, microsecond=0)
            url = DOE + "apitablehourly?" + urllib.parse.urlencode({"stateid": sid, "datetime": t.strftime("%Y-%m-%dT%H:00:00")}) + "&"
            try:
                tj = get_json(url, DOE_HEADERS, tries=2)
            except FetchError as e:
                errors.append(f"state {sid}: {e}")
                continue
            for r in tj.get("api_table_hourly", []) or []:
                if r.get("API") is None or not r.get("DATETIME") or r["DATETIME"][:16] > cut:
                    continue
                rows.append({"t": r["DATETIME"][:16], "station_id": r["STATION_ID"], "api": r["API"]})
            pause(0.5)
    return stations, rows, errors


# ---------------------------------------------------------------- OpenAQ: community sensors (needs OPENAQ_KEY)
def fetch_openaq(now, hours=60):
    """Community sensors in Malaysia and Singapore with their hourly PM2.5, `hours` back. Reference monitors are left out."""
    key = os.environ.get("OPENAQ_KEY", "").strip()
    if not key and isinstance(transport.TRANSPORT, transport.Live):
        raise FetchError("no OPENAQ_KEY")
    hdr = {"X-API-Key": key, "User-Agent": "Mozilla/5.0"}
    since = (now - dt.timedelta(hours=hours)).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:00:00Z")
    active_from = (now - dt.timedelta(days=3)).strftime("%Y-%m-%d")
    cut = local(now)
    sensors, errors = [], []
    for iso in ("MY", "SG"):
        j = get_json(OAQ + f"locations?iso={iso}&limit=200", hdr)
        for x in j.get("results", []) or []:
            if x.get("isMonitor") or (((x.get("datetimeLast") or {}).get("utc") or "")[:10]) < active_from:
                continue
            pm = next((s for s in x.get("sensors", []) if (s.get("parameter") or {}).get("name") == "pm25"), None)
            if not pm or not x.get("coordinates"):
                continue
            try:
                h = get_json(OAQ + f"sensors/{pm['id']}/hours?datetime_from={since}&limit=1000", hdr, tries=2)
            except FetchError as e:
                errors.append(f"{x.get('name')}: {e}")
                continue
            readings = {}
            for m in h.get("results", []) or []:
                t = (((m.get("period") or {}).get("datetimeTo") or {}).get("local") or "")[:16]
                if t and t <= cut and m.get("value") is not None and m["value"] >= 0:
                    readings[t] = m["value"]
            lic = (x.get("licenses") or [{}])[0] or {}
            att = lic.get("attribution") or {}
            sensors.append({"id": str(x["id"]), "name": x.get("name", ""), "provider": (x.get("provider") or {}).get("name", ""),
                            "lat": x["coordinates"]["latitude"], "lon": x["coordinates"]["longitude"], "readings": readings,
                            # each location's licence and owner, as OpenAQ gives them (docs/TERMS-CHECK-2026-10-15.md, OpenAQ)
                            "licence": lic.get("name"), "owner": att.get("name") or (x.get("owner") or {}).get("name") or "",
                            "owner_url": att.get("url")})
            pause(0.6)   # OpenAQ allows 60 calls a minute; each call takes about 1 second itself
        pause(1.1)
    if not sensors:
        raise FetchError("OpenAQ answered with no active community sensors")
    return sensors, errors


# ---------------------------------------------------------------- CAMS at every place, via Open-Meteo
def fetch_cams(places):
    """{place id: {time: PM2.5}}: 4 days back (3 days to compare with the measured index, plus 1 for its 24 hours) and 5 days ahead, in 1 call (weight: 1 per place)."""
    q = {"latitude": ",".join(f"{p['lat']:.4f}" for p in places), "longitude": ",".join(f"{p['lon']:.4f}" for p in places),
         "hourly": "pm2_5", "past_days": 4, "forecast_days": 5, "timezone": "Asia/Singapore"}
    res = get_json(AQ + "?" + urllib.parse.urlencode(q))
    res = res if isinstance(res, list) else [res]
    if len(res) != len(places):
        raise FetchError(f"Open-Meteo answered for {len(res)} of {len(places)} places")
    out = {}
    for p, r in zip(places, res):
        h = r.get("hourly", {})
        out[p["id"]] = {t: v for t, v in zip(h.get("time", []), h.get("pm2_5", [])) if v is not None}
    return out


# ---------------------------------------------------------------- the daily wind and rain at every place (shot 2)
WX = "https://api.open-meteo.com/v1/forecast"


def fetch_weather(places):
    """{place id: {"time", "wind_direction_10m_dominant", "precipitation_sum"}}: 5 days, for the outlook's why line."""
    q = {"latitude": ",".join(f"{p['lat']:.4f}" for p in places), "longitude": ",".join(f"{p['lon']:.4f}" for p in places),
         "daily": "wind_direction_10m_dominant,precipitation_sum", "forecast_days": 5, "timezone": "Asia/Singapore"}
    res = get_json(WX + "?" + urllib.parse.urlencode(q))
    res = res if isinstance(res, list) else [res]
    if len(res) != len(places):
        raise FetchError(f"Open-Meteo weather answered for {len(res)} of {len(places)} places")
    return {p["id"]: r.get("daily", {}) for p, r in zip(places, res)}


# ---------------------------------------------------------------- NASA FIRMS (needs FIRMS_MAP_KEY)
def fetch_firms(now):
    """Fire detections in the last 24 hours over the globe's box, from 2 satellites: (time UTC, lat, lon, frp)."""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key and isinstance(transport.TRANSPORT, transport.Live):
        raise FetchError("no FIRMS_MAP_KEY")
    start = (now - dt.timedelta(days=1)).astimezone(dt.timezone.utc).strftime("%Y-%m-%d")
    lo, hi = now - dt.timedelta(hours=24), now
    out = []
    for sat in ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT"):
        text = get_text(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key or 'KEY'}/{sat}/{FIRMS_BOX}/2/{start}", timeout=180)
        if not text.startswith("latitude"):
            raise FetchError(f"FIRMS {sat}: not a CSV answer")
        for rec in csv.DictReader(text.splitlines()):
            if not rec.get("acq_date"):
                continue
            t = dt.datetime.strptime(rec["acq_date"] + rec["acq_time"].zfill(4), "%Y-%m-%d%H%M").replace(tzinfo=dt.timezone.utc)
            if lo < t <= hi:
                out.append((t, float(rec["latitude"]), float(rec["longitude"]), float(rec.get("frp") or 0)))
        pause(1)
    if not out:
        raise FetchError("FIRMS answered with 0 fires in 24 hours over the box")   # the logger's rule: empty means failed
    return out


# ---------------------------------------------------------------- aqicn: the current value only (needs WAQI_TOKEN)
WAQI = "https://api.waqi.info/map/bounds/"


def fetch_aqicn(now):
    """aqicn's current value at every station in the box (DOE's and NEA's monitors, which aqicn relays on the US AQI scale):
    [{"uid", "name", "lat", "lon", "aqi", "t"}]. Copied from the logger's log_waqi; changed: aqicn gives its times with an offset
    (+09:00 on 15 Oct 2026), so they are converted to local time, not cut. The current value only: never kept in history/."""
    tok = os.environ.get("WAQI_TOKEN", "").strip()
    if not tok and isinstance(transport.TRANSPORT, transport.Live):
        raise FetchError("no WAQI_TOKEN")
    j = get_json(WAQI + "?" + urllib.parse.urlencode({"latlng": "-6,95,7,120", "token": tok or "TOKEN"}))
    if j.get("status") != "ok":
        raise FetchError(f"aqicn answered {j.get('status')!r}")
    out = []
    for st in j.get("data") or []:
        try:
            v = float(st.get("aqi"))
            when = dt.datetime.fromisoformat((st.get("station") or {}).get("time") or "")
        except (TypeError, ValueError):
            continue   # "-" when a station has no value
        if when.tzinfo is None or when > now or v < 0:
            continue
        out.append({"uid": str(st.get("uid")), "name": st["station"].get("name", ""), "lat": float(st["lat"]), "lon": float(st["lon"]),
                    "aqi": int(v) if v.is_integer() else v,
                    "t": local(when)})
    if not out:
        raise FetchError("aqicn answered with no stations")
    return out


# ---------------------------------------------------------------- the globe's grid, once a day
def fetch_grid(day):
    """{kind: [{time: values}] per point, in grid_spec order} for the given local day and the next (the smoke: 5 days ahead).
    About 4,000 Open-Meteo calls; paced to stay under 600 a minute."""
    nxt = (dt.date.fromisoformat(day) + dt.timedelta(days=1)).isoformat()
    # the smoke 5 days ahead for Earth's time line (session 7, part 69): the same number of calls, since Open-Meteo counts a
    # location as 1 call up to 2 weeks of data
    ahead = (dt.date.fromisoformat(day) + dt.timedelta(days=5)).isoformat()
    out = {"smoke": [], "wind": [], "hemi": []}
    for kind, url, pts, hourly in grid_spec.requests():
        q = {"latitude": ",".join(str(a) for a, b in pts), "longitude": ",".join(str(b) for a, b in pts), "hourly": hourly,
             "timezone": "Asia/Singapore", "start_date": day, "end_date": ahead if kind == "smoke" else nxt}
        res = get_json(url + "?" + urllib.parse.urlencode(q), timeout=120)
        res = res if isinstance(res, list) else [res]
        if len(res) != len(pts):
            raise FetchError(f"Open-Meteo grid: {len(res)} of {len(pts)} points")
        for r in res:
            h = r.get("hourly", {})
            names = hourly.split(",")
            out[kind].append({t: [h[n][i] for n in names] for i, t in enumerate(h.get("time", []))})
        pause(len(pts) / 550 * 60)
    return out
