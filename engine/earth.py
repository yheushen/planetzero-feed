"""Earth's layers for the public feed (session 7, part 69; docs/SPEC.md section 27): `earth.json` and the `earth/` folder.

    python engine/earth.py --out web/public/feed            # live, after build_feed.py (it reads now.json and the day's grid)
    python engine/earth.py --out DIR --offline              # replay of 16 Oct 2026, 8:49 am, from engine/tests/recorded_earth/

Every layer says its kind (measured, from space, estimated), unit, source, credit, the time it covers and the time it was made;
a layer that failed says why and holds nothing old (invariant 10). Each source is fetched on its own; 1 failing never stops the
others, and Earth failing never touches now.json (the Action runs this as its own step).

  smoke       estimated   CAMS PM2.5. Global at 0.4 degrees from the Copernicus Atmosphere Data Store when ADS_KEY is set (the
                          owner's free account); until then the regional 1 degree CAMS grid of grid.json, which says so.
  wind        estimated   NOAA GFS 10 m wind, 1 degree, every 6 hours to 5 days, from NOMADS, read by grib2.py.
  fires       from space  NASA FIRMS VIIRS (Suomi NPP, NOAA-20), worldwide, the last 24 hours, as 0.1 degree cells with counts;
                          and each of the last 7 days, kept once.
  monitors    measured    OpenAQ's latest PM2.5 worldwide, only under the licences of sources.EARTH_LICENCES, never IQAir's;
                          NEA's 5 regions and DOE's 68 monitors from now.json. Late after 3 hours, dropped after 8 (invariant 4).
  satellites  from space  CelesTrak's elements for 8 satellites, fetched at most once per 2-hour update (its usage policy).
  pictures    from space  NASA GIBS (Real Earth, smoke from space, carbon monoxide): named, never copied.
"""
import argparse
import concurrent.futures as cf
import csv
import datetime as dt
import gzip
import json
import math
import os
import sys
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bands  # noqa: E402
import credits  # noqa: E402
import grib2  # noqa: E402
import publish  # noqa: E402
import sources  # noqa: E402
import transport  # noqa: E402
from transport import FetchError, get_bytes, get_json, get_text  # noqa: E402

TZ8 = dt.timezone(dt.timedelta(hours=8))
UTC = dt.timezone.utc
REPLAY_AT = "2026-10-16T08:49+08:00"
RECORDED = os.path.join(HERE, "tests", "recorded_earth")

LATE_H, DROP_H = 3, 8          # invariant 4
PAST_DAYS = 7
FRAME_STEP_H = 3               # smoke frames every 3 hours, past and ahead; the hour itself in smoke-now
GFS = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_1p00.pl"
GFS_STEPS = tuple(range(0, 121, 6))
GFS_READY_H = 3.5              # a GFS cycle reaches NOMADS about 3.5 hours after its time
FIRMS = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
FIRMS_SATS = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT")
OAQ = "https://api.openaq.org/v3/"
CELESTRAK = "https://celestrak.org/NORAD/elements/gp.php"
CELESTRAK_EVERY_H = 2          # "For GP data, updates are once every 2 hours" (celestrak.org/usage-policy.php)
SATELLITES = (("suomi-npp", "Suomi NPP", 37849), ("noaa-20", "NOAA-20", 43013), ("noaa-21", "NOAA-21", 54234), ("aqua", "Aqua", 27424),
              ("terra", "Terra", 25994), ("sentinel-5p", "Sentinel-5P", 42969), ("himawari-9", "Himawari-9", 41836), ("iss", "ISS", 25544))
ADS = "https://ads.atmosphere.copernicus.eu/api"
ADS_DATASET = "cams-global-atmospheric-composition-forecasts"
KIND_WORD = {"measured": "Measured", "from_space": "From space", "estimated": "Estimated"}

# the pictures, loaded by the browser straight from NASA (docs/TERMS-CHECK-EARTH-2026-10-16.md, section 1)
GIBS_WMTS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/{layer}/default/{date}/{matrix}/{z}/{y}/{x}.{ext}"
GIBS_WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
PICTURES = (
    {"id": "real_earth", "name": "Real Earth", "layer": "VIIRS_NOAA20_CorrectedReflectance_TrueColor", "fill": "BlueMarble_NextGeneration",
     "matrix": "GoogleMapsCompatible_Level9", "max_level": 9, "ext": "jpg", "metres": 375,
     "what": "The planet as the camera on NOAA-20 saw it the day before: clouds, deserts and the haze itself. NASA's Blue Marble where it saw nothing.",
     "colours": "True colour.", "satellite": "NOAA-20, VIIRS"},
    {"id": "smoke_space", "name": "Smoke from space", "layer": "MODIS_Terra_Aerosol", "matrix": "GoogleMapsCompatible_Level6", "max_level": 6,
     "ext": "png", "metres": 10000, "what": "How much light the smoke and dust in the air block, seen from above. Gaps are where the satellite did not pass.",
     "colours": "Pale yellow (a little) to dark red (a lot), as NASA draws it.", "satellite": "Terra, MODIS"},
    {"id": "co", "name": "Carbon monoxide", "layer": "AIRS_L2_Carbon_Monoxide_500hPa_Volume_Mixing_Ratio_Day", "matrix": "GoogleMapsCompatible_Level6",
     "max_level": 6, "ext": "png", "metres": 45000, "what": "A gas from burning, about 5 km up.",
     "colours": "Pale yellow (a little) through orange and red to purple (a lot), as NASA draws it.", "satellite": "Aqua, AIRS"},
)


# ---------------------------------------------------------------- small helpers
def stamp(t):
    return t.astimezone(TZ8).strftime("%Y-%m-%dT%H:%M+08:00")


def clock(t):
    h = t.hour % 12 or 12
    return f"{h}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def pause(seconds):
    if isinstance(transport.TRANSPORT, transport.Live):
        time.sleep(seconds)


def round2(x):
    return round(x + 0.0, 2)


def km(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(min(1.0, math.sqrt(a)))


def write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(publish.rounded(obj), f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def hour_name(t):
    """'2026-10-16T08': a frame's file name, local time."""
    return t.astimezone(TZ8).strftime("%Y-%m-%dT%H")


def from_name(name):
    return dt.datetime.strptime(name, "%Y-%m-%dT%H").replace(tzinfo=TZ8)


def missing(layer, why):
    return {**layer, "status": "missing", "reason": why}


# ---------------------------------------------------------------- wind: NOAA GFS through NOMADS
def gfs_url(run, step):
    q = {"dir": f"/gfs.{run:%Y%m%d}/{run:%H}/atmos", "file": f"gfs.t{run:%H}z.pgrb2.1p00.f{step:03d}",
         "var_UGRD": "on", "var_VGRD": "on", "lev_10_m_above_ground": "on"}
    return GFS + "?" + urllib.parse.urlencode(q)


def gfs_runs(now):
    """The GFS cycles to try, newest first: the last one that should be on NOMADS, then 2 before it."""
    t = now.astimezone(UTC) - dt.timedelta(hours=GFS_READY_H)
    first = t.replace(hour=t.hour - t.hour % 6, minute=0, second=0, microsecond=0)
    return [first - dt.timedelta(hours=6 * k) for k in range(3)]


def wind_frame(blob):
    """A GFS file's 10 m wind as km/h, whole numbers, rows south to north: ({grid}, u, v)."""
    g, u, v, _hours = grib2.wind_10m(blob)
    spec = {"lat0": g["lat0"], "lon0": g["lo1"], "step": g["di"], "nlat": g["nj"], "nlon": g["ni"]}
    return spec, [round(x * 3.6) for x in u], [round(x * 3.6) for x in v]


def coarser(spec, u, v, k=2):
    """Every k-th row and column (2 degrees from 1): for the frames ahead, which are many and less looked at."""
    rows = range(0, spec["nlat"], k)
    cols = range(0, spec["nlon"], k)
    pick = [r * spec["nlon"] + c for r in rows for c in cols]
    return ({**spec, "step": spec["step"] * k, "nlat": len(rows), "nlon": len(cols)}, [u[i] for i in pick], [v[i] for i in pick])


def fetch_gfs(now, cache):
    """(run, {step: (spec, u, v)}) from the newest GFS cycle on NOMADS; decoded steps are kept in the cache for the run's 6 hours,
    so each step is asked for once (NOMADS allows 120 hits a minute; a new run takes 21)."""
    os.makedirs(cache, exist_ok=True)
    errors = []
    for run in gfs_runs(now):
        frames = {}
        for step in GFS_STEPS:
            p = os.path.join(cache, f"gfs-{run:%Y%m%d%H}-f{step:03d}.json")
            got = read_json(p)
            if got:
                frames[step] = (got["grid"], got["u"], got["v"])
                continue
            try:
                spec, u, v = wind_frame(get_bytes(gfs_url(run, step), timeout=90, tries=2))
            except (FetchError, grib2.GribError) as e:
                if step == 0:
                    errors.append(f"{run:%d %b %H}z: {e}")
                    break   # this cycle is not out yet: try the one before
                continue    # a step not out yet: the frames ahead stop earlier, and the next run asks again
            frames[step] = (spec, u, v)
            write_json(p, {"grid": spec, "u": u, "v": v})
            pause(0.6)
        if frames:
            for old in os.listdir(cache):   # earlier runs' steps
                if old.startswith("gfs-") and not old.startswith(f"gfs-{run:%Y%m%d%H}"):
                    os.remove(os.path.join(cache, old))
            return run, frames
    raise FetchError("no GFS run on NOMADS in the last 18 hours: " + "; ".join(errors))


# ---------------------------------------------------------------- fires: NASA FIRMS, worldwide
def firms_rows(text):
    if not text.startswith("latitude"):
        raise FetchError("FIRMS: not a CSV answer")
    out = []
    for rec in csv.DictReader(text.splitlines()):
        if not rec.get("acq_date"):
            continue
        t = dt.datetime.strptime(rec["acq_date"] + rec["acq_time"].zfill(4), "%Y-%m-%d%H%M").replace(tzinfo=UTC)
        out.append((t, float(rec["latitude"]), float(rec["longitude"])))
    return out


def fetch_firms_world(start_utc_date, days):
    """Every VIIRS detection worldwide from both satellites for `days` UTC days from the date: [(time UTC, lat, lon)]."""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key and isinstance(transport.TRANSPORT, transport.Live):
        raise FetchError("no FIRMS_MAP_KEY")
    out = []
    for sat in FIRMS_SATS:
        out += firms_rows(get_text(f"{FIRMS}{key or 'KEY'}/{sat}/world/{days}/{start_utc_date}", timeout=300))
        pause(1)
    return out


def fire_cells(rows, lo, hi):
    """Detections with lo < time <= hi as 0.1 degree cells: [[lat, lon, count]], sorted; and how many detections they hold."""
    cells = {}
    for t, la, lo_ in rows:
        if lo < t <= hi:
            k = (round(la * 10), round(lo_ * 10))
            cells[k] = cells.get(k, 0) + 1
    return [[a / 10, b / 10, n] for (a, b), n in sorted(cells.items())], sum(cells.values())


# ---------------------------------------------------------------- monitors: OpenAQ worldwide, NEA and DOE
def openaq_headers():
    key = os.environ.get("OPENAQ_KEY", "").strip()
    if not key and isinstance(transport.TRANSPORT, transport.Live):
        raise FetchError("no OPENAQ_KEY")
    return {"X-API-Key": key, "User-Agent": "Mozilla/5.0"}


def pages(path, hdr, most=60):
    out = []
    for page in range(1, most + 1):
        j = get_json(OAQ + f"{path}{'&' if '?' in path else '?'}limit=1000&page={page}", hdr, timeout=120)
        res = j.get("results", []) or []
        out += res
        if len(res) < 1000:
            return out
        pause(1.1)   # 60 a minute
    return out


def openaq_locations(now, cache):
    """{location id: {name, provider, owner, licence, monitor}} for every PM2.5 location, fetched once a day (about 21 calls)."""
    p = os.path.join(cache, f"openaq-locations-{now:%Y-%m-%d}.json")
    got = read_json(p)
    if got:
        return got
    out = {}
    for x in pages("locations?parameters_id=2", openaq_headers()):
        lic = (x.get("licenses") or [None])[0] or {}
        att = lic.get("attribution") or {}
        out[str(x["id"])] = {"name": x.get("name") or "", "provider": (x.get("provider") or {}).get("name") or "",
                             "owner": att.get("name") or (x.get("owner") or {}).get("name") or "", "licence": lic.get("name") or "",
                             "monitor": bool(x.get("isMonitor"))}
    os.makedirs(cache, exist_ok=True)
    for old in os.listdir(cache):
        if old.startswith("openaq-locations-"):
            os.remove(os.path.join(cache, old))
    write_json(p, out)
    return out


def fetch_openaq_world(now, cache):
    """(the latest PM2.5 of every location, the locations): about 22 calls for the readings, 21 once a day for the licences."""
    latest = pages("parameters/2/latest", openaq_headers())
    return latest, openaq_locations(now, cache)


def openaq_monitors(latest, locations, now):
    """The rows Earth may show, and what was left out and why: invariant 4 (late after 3 hours, dropped after 8) and the
    licences of docs/TERMS-CHECK-EARTH-2026-10-16.md (never IQAir's locations, invariant 6). 1 row per location, its newest."""
    best = {}
    for r in latest:
        lid = str(r.get("locationsId"))
        t = ((r.get("datetime") or {}).get("utc") or "")
        v = r.get("value")
        c = r.get("coordinates") or {}
        if not t or v is None or v < 0 or v > 2000 or c.get("latitude") is None:
            continue
        if lid not in best or t > best[lid][0]:
            best[lid] = (t, v, c["latitude"], c["longitude"])
    rows, left = [], {"old": 0, "licence": 0, "never": 0, "unknown": 0}
    for lid, (t, v, la, lo) in best.items():
        when = dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        age = (now - when).total_seconds() / 3600
        loc = locations.get(lid)
        if age > DROP_H or age < -0.5:
            left["old"] += 1
        elif loc is None:
            left["unknown"] += 1
        elif loc["provider"] in sources.NEVER_PROVIDERS:
            left["never"] += 1
        elif loc["licence"] not in sources.EARTH_LICENCES:
            left["licence"] += 1
        else:
            rows.append({"lat": la, "lon": lo, "value": round(v, 1), "unit": "µg/m³", "window": "latest", "at": stamp(when),
                         "late": age > LATE_H, "source": "OpenAQ", "name": loc["name"], "owner": loc["owner"] or loc["provider"],
                         "provider": loc["provider"], "licence": loc["licence"], "monitor": loc["monitor"]})
    return rows, left


def agency_monitors(now_json, now):
    """NEA's 5 regions (1-hour PM2.5) and DOE's monitors (24-hour API, as the Now page shows it) from this run's now.json."""
    rows = []
    for p in (now_json or {}).get("places", []):
        r = p.get("hour") if p["country"] == "SG" else p.get("index")
        if not r or r.get("status") != "ok" or r.get("value") is None:
            continue
        when = dt.datetime.fromisoformat(r["measured_at"])
        age = (now - when).total_seconds() / 3600
        if age > DROP_H:
            continue
        src = "NEA" if p["country"] == "SG" else "DOE"
        st = r.get("station") or {}
        row = {"lat": st.get("lat", p["lat"]), "lon": st.get("lon", p["lon"]), "value": r["value"], "unit": r["unit"], "window": r.get("window", "1h"),
               "at": r["measured_at"], "late": age > LATE_H, "source": src, "name": (f"{st['name']} (NEA)" if src == "NEA" else f"{st['name']} (DOE)") if st.get("name") else p["name"],
               "owner": src, "provider": src,
               "licence": credits.CREDITS["sources"][src]["licence"], "monitor": True}
        if src == "DOE":   # its band on its own scale, and the 24-hour µg/m³ it stands for (engine/convert.py), as the ruler says it
            import convert
            row["pm25_24h"] = round(convert.to_pm25(r["value"], "api"), 1)
        rows.append(row)
    return rows


def monitor_file(rows, now, left, status):
    """earth/monitors.json, compact: names, owners, providers and licences listed once and pointed to."""
    names, owners, provs, lics = [], [], [], []

    def idx(lst, x):
        if x not in lst:
            lst.append(x)
        return lst.index(x)
    units = ["µg/m³", "API"]
    out = []
    for r in sorted(rows, key=lambda r: (r["lat"], r["lon"])):
        band = bands.band(r["value"], "hourly_pm25" if r["unit"] == "µg/m³" else "api")
        out.append([round2(r["lat"]), round2(r["lon"]), r["value"], units.index(r["unit"]), r["at"][:16], 1 if r["late"] else 0,
                    idx(provs, r["provider"]), idx(owners, r["owner"]), idx(lics, r["licence"]), idx(names, r["name"]), 1 if r["monitor"] else 0,
                    band, r.get("pm25_24h")])
    return {"schema_version": "1", "generated_at": stamp(now), "status": status,
            "columns": ["lat", "lon", "value", "unit", "at", "late", "provider", "owner", "licence", "name", "government", "band", "pm25_24h"],
            "units": units, "windows": {"µg/m³": "1h or the latest reading", "API": "24h"},
            "providers": provs, "owners": owners, "licences": lics, "names": names, "rows": out, "left_out": left,
            "rule": f"Late after {LATE_H} hours; left out after {DROP_H}. OpenAQ's locations only under the licences that allow showing them; never IQAir's."}


# ---------------------------------------------------------------- satellites: CelesTrak
def fetch_satellites(now, prev):
    """(elements, fetched_at, note): the kept elements when they are under 2 hours old (no request at all); else each satellite
    asked once, stopping at the first answer that is not 200 or not elements (CelesTrak's policy: stop and tell a human)."""
    if prev and prev.get("fetched_at") and now - dt.datetime.fromisoformat(prev["fetched_at"]) < dt.timedelta(hours=CELESTRAK_EVERY_H):
        return prev["elements"], prev["fetched_at"], prev.get("note", "")
    els = dict((prev or {}).get("elements") or {})
    for sid, _name, cat in SATELLITES:
        try:
            got = get_json(f"{CELESTRAK}?CATNR={cat}&FORMAT=json", tries=1, timeout=60)
        except FetchError as e:
            return els, (prev or {}).get("fetched_at"), f"CelesTrak answered {e} at {clock(now)}; we stopped asking until the next 2-hour update, as its policy asks."
        if not isinstance(got, list) or not got or got[0].get("NORAD_CAT_ID") != cat:
            return els, (prev or {}).get("fetched_at"), f"CelesTrak did not send elements for {cat} at {clock(now)}; we stopped asking, as its policy asks."
        els[sid] = got[0]
        pause(1)
    return els, stamp(now), ""


# ---------------------------------------------------------------- smoke: CAMS
def regional_frames(g, now):
    """{local hour: values} of the regional 1 degree box from the day's grid (build_feed.grid_day): every hour it holds."""
    hours = sorted({t for pt in g["smoke"] for t in pt})
    out = {}
    for h in hours:
        vals = [(pt.get(h) or [None])[0] for pt in g["smoke"]]
        if any(v is not None for v in vals):
            out[h] = [None if v is None else round(v, 1) for v in vals]
    return out


def ads_request(now):
    """The request for CAMS global PM2.5: the newest 00 or 12 UTC run that should be ready (about 10 hours after), 0 to 120 hours."""
    t = now.astimezone(UTC) - dt.timedelta(hours=10)
    run = t.replace(hour=0 if t.hour < 12 else 12, minute=0, second=0, microsecond=0)
    return run, {"variable": ["particulate_matter_2.5um"], "date": [f"{run:%Y-%m-%d}/{run:%Y-%m-%d}"], "time": [f"{run:%H}:00"],
                 "leadtime_hour": [str(h) for h in range(0, 121, FRAME_STEP_H)], "type": ["forecast"], "data_format": "grib"}


def fetch_ads(now, cache, key):
    """CAMS global PM2.5 through the Atmosphere Data Store's REST API (the same calls as ECMWF's datastores client): submit, wait,
    download; kept in the cache for its run. (run, {valid time UTC: (spec, µg/m³ values)})."""
    run, req = ads_request(now)
    p = os.path.join(cache, f"cams-{run:%Y%m%d%H}.grib")
    if not os.path.exists(p):
        hdr = {"PRIVATE-TOKEN": key, "User-Agent": "planetzero", "Content-Type": "application/json"}
        job = transport.post_json(f"{ADS}/retrieve/v1/processes/{ADS_DATASET}/execution", {"inputs": req}, hdr)
        jid = job.get("jobID")
        if not jid:
            raise FetchError("the Atmosphere Data Store did not take the request")
        for _ in range(60):   # up to about 20 minutes, within the Action's own limit
            st = get_json(f"{ADS}/retrieve/v1/jobs/{jid}", hdr).get("status")
            if st == "successful":
                break
            if st in ("failed", "dismissed", "rejected"):
                raise FetchError(f"the Atmosphere Data Store's job {st}")
            pause(20)
        else:
            raise FetchError("the Atmosphere Data Store's job did not finish in 20 minutes")
        href = ((get_json(f"{ADS}/retrieve/v1/jobs/{jid}/results", hdr).get("asset") or {}).get("value") or {}).get("href")
        if not href:
            raise FetchError("the Atmosphere Data Store gave no file")
        os.makedirs(cache, exist_ok=True)
        with open(p + ".tmp", "wb") as f:
            f.write(get_bytes(href, timeout=600))
        os.replace(p + ".tmp", p)
    return run, cams_frames(open(p, "rb").read(), run)


def cams_frames(blob, run):
    """{valid time UTC: (grid spec, µg/m³)} from a CAMS GRIB file (PM2.5 in kg/m³). ECMWF's files may be GRIB 1, or GRIB 2 with
    packings grib2.py does not read (CCSDS): ecCodes reads them when it is installed (the Action installs it only when ADS_KEY is
    set); else grib2.py, which raises on anything it does not know (a missing layer, never a wrong one)."""
    try:
        import eccodes  # noqa: F401
    except ImportError:
        return cams_frames_grib2(blob, run)
    return cams_frames_eccodes(blob, run)


def cams_frames_eccodes(blob, run):
    import eccodes
    out = {}
    i = 0
    while i < len(blob):
        h = eccodes.codes_new_from_message(blob[i:])
        try:
            n = eccodes.codes_get(h, "totalLength")
            ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
            la1, la2 = eccodes.codes_get(h, "latitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "latitudeOfLastGridPointInDegrees")
            lo1, di = eccodes.codes_get(h, "longitudeOfFirstGridPointInDegrees"), eccodes.codes_get(h, "iDirectionIncrementInDegrees")
            step = eccodes.codes_get(h, "step")
            vals = list(eccodes.codes_get_values(h))
        finally:
            eccodes.codes_release(h)
        if la1 > la2:
            vals = [v for r in range(nj - 1, -1, -1) for v in vals[r * ni:(r + 1) * ni]]
        spec = {"lat0": min(la1, la2), "lon0": lo1, "step": di, "nlat": nj, "nlon": ni}
        out[run + dt.timedelta(hours=step)] = (spec, [round(v * 1e9, 1) for v in vals])
        i += n
    return out


def cams_frames_grib2(blob, run):
    out = {}
    for m in grib2.messages(blob):
        g = m["grid"]
        spec = {"lat0": g["lat0"], "lon0": g["lo1"], "step": g["di"], "nlat": g["nj"], "nlon": g["ni"]}
        out[run + dt.timedelta(hours=m["product"]["hours"])] = (spec, [None if v is None else round(v * 1e9, 1) for v in m["values"]])
    return out


def regional_where_finer(global_spec, gvals, region_spec, rvals):
    """The rule of the prompt: the regional grid only where its cells are finer than the global ones (never, at 1 against 0.4
    degrees). Returns the global values, or the regional ones' values laid onto the global grid where the regional is finer."""
    if region_spec["step"] >= global_spec["step"]:
        return gvals
    out = list(gvals)
    for i in range(global_spec["nlat"]):
        la = global_spec["lat0"] + i * global_spec["step"]
        for j in range(global_spec["nlon"]):
            lo = global_spec["lon0"] + j * global_spec["step"]
            ri = round((la - region_spec["lat0"]) / region_spec["step"])
            rj = round(((lo - region_spec["lon0"]) % 360) / region_spec["step"])
            if 0 <= ri < region_spec["nlat"] and 0 <= rj < region_spec["nlon"]:
                v = rvals[ri * region_spec["nlon"] + rj]
                if v is not None:
                    out[i * global_spec["nlon"] + j] = v
    return out


# ---------------------------------------------------------------- the build
def frame_hours(now, ahead_h):
    """The 3-hourly marks from 7 days back to `ahead_h` ahead, local time."""
    t0 = now.astimezone(TZ8).replace(minute=0, second=0, microsecond=0)
    t0 -= dt.timedelta(hours=t0.hour % FRAME_STEP_H)
    first = t0 - dt.timedelta(days=PAST_DAYS)
    n = int((PAST_DAYS * 24 + ahead_h) / FRAME_STEP_H) + 1
    return [first + dt.timedelta(hours=FRAME_STEP_H * k) for k in range(n)]


def prune(folder, keep_from, pattern_len=13):
    """Frames older than 7 days go (each file is named by its local hour or day)."""
    if not os.path.isdir(folder):
        return
    for f in os.listdir(folder):
        stem = f.split(".")[0]
        if len(stem) >= 10 and stem[:pattern_len] < keep_from[:pattern_len] and stem not in ("now",):
            os.remove(os.path.join(folder, f))


def credit_block(ids, now):
    return credits.block(ids, now)


def build_earth(out, at=None, transport_=None, cache=None, grid_day=None, quiet=False):
    """Write earth.json and earth/ into `out` (the feed folder, holding this run's now.json). Returns earth.json's content."""
    t0 = time.monotonic()
    if transport_ is not None:
        transport.TRANSPORT = transport_
    now = dt.datetime.fromisoformat(at).astimezone(TZ8) if at else dt.datetime.now(TZ8).replace(second=0, microsecond=0)
    cache = os.path.join(cache or os.path.join(ROOT, ".cache"), "earth")
    folder = os.path.join(out, "earth")
    os.makedirs(folder, exist_ok=True)
    keep_from = hour_name(now - dt.timedelta(days=PAST_DAYS))
    prev_sats = read_json(os.path.join(folder, "satellites.json"))
    ads_key = os.environ.get("ADS_KEY", "").strip()
    utc_today = now.astimezone(UTC).date()
    jobs = {"wind": lambda: fetch_gfs(now, cache),
            "fires": lambda: fetch_firms_world((utc_today - dt.timedelta(days=1)).isoformat(), 2),
            "monitors": lambda: fetch_openaq_world(now, cache),
            "satellites": lambda: fetch_satellites(now, prev_sats)}
    if grid_day is not None:
        jobs["smoke_regional"] = lambda: grid_day(now, os.path.dirname(cache))
    if ads_key:
        jobs["smoke_global"] = lambda: fetch_ads(now, cache, ads_key)
    got, took = {}, {}
    with cf.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futs = {pool.submit(lambda f=fn: (time.monotonic(), f())): name for name, fn in jobs.items()}
        for fut in cf.as_completed(futs):
            name = futs[fut]
            try:
                started, got[name] = fut.result()
                took[name] = round(time.monotonic() - started, 1)
            except Exception as e:   # each source on its own (invariant 10: missing, said so)
                got[name] = e
    layers = []

    # smoke
    smoke = {"id": "smoke", "name": "Smoke", "kind": "estimated", "unit": "µg/m³", "window": "1h", "words": "sand to brown",
             "what": "Fine smoke (PM2.5) at the surface, as a computer model works it out.", "colours": "By NEA's 4 bands: Normal sage, Elevated amber, High dark orange, Very high brown.",
             "updates": "Every hour, and 5 days ahead", "numbers": "Yes: tap, or ask your AI", "band_scale": "hourly_pm25"}
    sdir = os.path.join(folder, "smoke")
    glob_ok = ads_key and not isinstance(got.get("smoke_global"), Exception)
    reg = got.get("smoke_regional")
    if glob_ok:
        run, frames = got["smoke_global"]
        reg_now = regional_frames(reg, now) if reg is not None and not isinstance(reg, Exception) else {}
        smoke.update(source="CAMS-ADS", credit=credits.CREDITS["sources"]["CAMS-ADS"]["short"], scope="global", made_at=stamp(run), fetched_at=stamp(now))
        files = write_smoke_frames(sdir, now, {t.astimezone(TZ8): v for t, v in frames.items()},
                                   {dt.datetime.fromisoformat(h).replace(tzinfo=TZ8): v for h, v in reg_now.items()}, keep_from, "CAMS-ADS")
    elif reg is not None and not isinstance(reg, Exception):
        import grid_spec
        hourly = regional_frames(reg, now)
        frames = {dt.datetime.fromisoformat(h).replace(tzinfo=TZ8): (grid_spec.BOX, v) for h, v in hourly.items()}
        smoke.update(source="CAMS", via="Open-Meteo", credit=credits.CREDITS["sources"]["CAMS"]["short"], scope="regional",
                     scope_note="Southeast Asia only for now: the global model needs a key we do not have yet.", made_at=stamp(now), fetched_at=stamp(now))
        if ads_key:
            smoke["scope_note"] = f"Southeast Asia only this hour: the global model did not arrive ({str(got['smoke_global'])[:120]})."
        files = write_smoke_frames(sdir, now, frames, {}, keep_from, "CAMS")
    else:
        why = reg if isinstance(reg, Exception) else "no grid"
        files = None
        smoke = missing({**smoke, "source": "CAMS", "credit": credits.CREDITS["sources"]["CAMS"]["short"], "made_at": stamp(now), "fetched_at": stamp(now)},
                        f"The smoke model did not answer at {clock(now)} ({str(why)[:120]}).")
    if files:
        now_name, frame_list, cell = files
        smoke.update(status="ok", now=f"earth/smoke/{now_name}.json", covers={"at": stamp(from_name(now_name))}, frames=frame_list,
                     cell_deg=cell, cell_km=round(cell * 111.2))
    elif smoke.get("status") != "missing":
        smoke = missing(smoke, f"The smoke model held no value for {clock(now)}.")
    layers.append(smoke)

    # wind
    wind = {"id": "wind", "name": "Wind", "kind": "estimated", "unit": "km/h", "window": "at the time shown", "source": "GFS", "words": "white",
            "credit": credits.CREDITS["sources"]["GFS"]["short"], "what": "Wind 10 m above the ground. It shows where the smoke is going.",
            "colours": "White lines moving with the wind on Real Earth; grey blue on Plain. Faster and brighter where stronger.",
            "updates": "Every 6 hours, and 5 days ahead", "numbers": "Yes: tap, or ask your AI", "fetched_at": stamp(now)}
    if isinstance(got["wind"], Exception):
        layers.append(missing({**wind, "made_at": stamp(now)}, f"NOAA's wind model did not answer at {clock(now)} ({str(got['wind'])[:160]})."))
    else:
        run, steps = got["wind"]
        layers.append({**wind, **write_wind_frames(os.path.join(folder, "wind"), now, run, steps, keep_from), "status": "ok", "made_at": stamp(run)})

    # fires
    fires = {"id": "fires", "name": "Fires", "kind": "from_space", "unit": "detections", "window": "24h", "source": "FIRMS", "words": "red",
             "credit": credits.CREDITS["sources"]["FIRMS"]["short"], "what": "Heat seen from space, 375 m across, in the last 24 hours.",
             "colours": "Red dots.", "updates": "Several passes a day", "numbers": "Yes: counts near a point", "cell_deg": 0.1, "cell_km": 11,
             "fetched_at": stamp(now)}
    lo, hi = now - dt.timedelta(hours=24), now
    if isinstance(got["fires"], Exception):
        layers.append(missing({**fires, "made_at": stamp(now), "covers": {"from": stamp(lo), "to": stamp(hi)}},
                              f"NASA FIRMS did not answer at {clock(now)} ({str(got['fires'])[:120]})."))
    else:
        rows = got["fires"]
        cells, n = fire_cells(rows, lo, hi)
        newest = max((t for t, _a, _b in rows if lo < t <= hi), default=None)
        write_json(os.path.join(folder, "fires.json"), {"schema_version": "1", "generated_at": stamp(now), "from": stamp(lo), "to": stamp(hi),
                                                        "columns": ["lat", "lon", "count"], "cells": cells, "detections": n,
                                                        "credits": credit_block(["FIRMS"], now)})
        days = fire_days(os.path.join(folder, "fires"), now, rows)
        fires.update(status="ok", file="earth/fires.json", covers={"from": stamp(lo), "to": stamp(hi)}, detections=n, cells=len(cells),
                     made_at=stamp(newest) if newest else stamp(now), days=days)
        if n == 0:
            fires = missing(fires, f"NASA FIRMS answered with 0 fires worldwide in 24 hours at {clock(now)}.")   # the logger's rule
        layers.append(fires)

    # monitors
    mon = {"id": "monitors", "name": "Monitors", "kind": "measured", "unit": "µg/m³", "window": "1h or the latest reading", "source": "OpenAQ",
           "words": "by band", "credit": credits.CREDITS["sources"]["OpenAQ-world"]["short"],
           "what": "Fine smoke, PM2.5, from government monitors and community sensors, each at its place.",
           "colours": "Dots by NEA's 4 bands: sage Normal, amber Elevated, dark orange High, brown Very high. Rings: DOE's 24-hour index, by the smoke it stands for.",
           "updates": "Every hour", "numbers": "Yes: tap, or ask your AI", "fetched_at": stamp(now)}
    agency = agency_monitors(read_json(os.path.join(out, "now.json")), now)
    if isinstance(got["monitors"], Exception):
        rows, left, status = agency, {}, f"OpenAQ did not answer at {clock(now)} ({str(got['monitors'])[:100]}): NEA and DOE only."
    else:
        rows, left = openaq_monitors(*got["monitors"], now)
        rows, status = rows + agency, "ok"
    if rows:
        mf = monitor_file(rows, now, left, status)
        mf["credits"] = credit_block(["OpenAQ-world", "NEA", "DOE"], now)
        write_json(os.path.join(folder, "monitors.json"), mf)
        ats = sorted(r["at"] for r in rows)
        mon.update(status="ok", file="earth/monitors.json", count=len(rows), late=sum(1 for r in rows if r["late"]), left_out=left,
                   covers={"from": ats[0], "to": ats[-1]}, made_at=ats[-1], note="" if status == "ok" else status)
        layers.append(mon)
    else:
        layers.append(missing({**mon, "made_at": stamp(now)}, f"No monitor answered at {clock(now)}."))

    # satellites
    sat = {"id": "satellites", "name": "Satellites", "kind": "from_space", "unit": "km", "window": "live", "source": "CelesTrak", "words": "white",
           "credit": credits.CREDITS["sources"]["CelesTrak"]["short"], "what": "Where the satellites that take these pictures are now, and where they passed in the last 50 minutes.",
           "colours": "White, with dotted white trails for the last 50 minutes.", "updates": "Live", "numbers": "Yes: name and height"}
    if isinstance(got["satellites"], Exception):
        layers.append(missing({**sat, "made_at": stamp(now)}, f"CelesTrak did not answer at {clock(now)}."))
    else:
        els, fetched, note = got["satellites"]
        if els:
            write_json(os.path.join(folder, "satellites.json"), {"schema_version": "1", "generated_at": stamp(now), "fetched_at": fetched, "note": note,
                                                                 "satellites": [{"id": s, "name": n, "catalog": c} for s, n, c in SATELLITES],
                                                                 "elements": els, "credits": credit_block(["CelesTrak"], now)})
            epochs = sorted(e["EPOCH"] for e in els.values())
            sat.update(status="ok", file="earth/satellites.json", count=len(els), covers={"elements_from": epochs[0][:16] + "Z", "elements_to": epochs[-1][:16] + "Z"},
                       made_at=fetched, note=note)
            layers.append(sat)
        else:
            layers.append(missing({**sat, "made_at": stamp(now)}, note or f"CelesTrak sent nothing at {clock(now)}."))

    # pictures, from NASA GIBS: named, never copied
    day = (now - dt.timedelta(days=1)).strftime("%Y-%m-%d")
    for pic in PICTURES:
        layers.append({"id": pic["id"], "name": pic["name"], "kind": "from_space", "unit": "picture", "picture": True, "status": "ok", "source": "GIBS",
                       "credit": credits.CREDITS["sources"]["GIBS"]["short"], "words": "yesterday" if pic["id"] == "real_earth" else "picture",
                       "what": pic["what"], "colours": pic["colours"], "updates": "Once a day, the day before", "numbers": "Picture only",
                       "covers": {"date": day}, "made_at": day, "satellite": pic["satellite"], "metres": pic["metres"],
                       "gibs": {"layer": pic["layer"], "fill": pic.get("fill"), "matrix": pic["matrix"], "max_level": pic["max_level"], "ext": pic["ext"],
                                "wmts": GIBS_WMTS, "wms": GIBS_WMS}})

    earth = {"schema_version": "1", "generated_at": stamp(now)}
    if at:
        earth["replay_of"] = stamp(now)
    earth["kinds"] = KIND_WORD
    earth["layers"] = layers
    earth["took_s"] = {**took, "all": round(time.monotonic() - t0, 1)}
    used = sorted({l["source"] for l in layers} | ({"OpenAQ-world", "NEA", "DOE"} if any(l["id"] == "monitors" and l["status"] == "ok" for l in layers) else set()))
    earth["credits"] = credit_block([s for s in used if s in credits.ALL] + ["NaturalEarth"], now)
    bad = sorted({l["source"] for l in layers} - set(sources.ALLOW))
    if bad:
        raise SystemExit(f"not allowed in the public feed (docs/DATA-TERMS.md): {bad}")
    write_json(os.path.join(out, "earth.json"), earth)
    if not quiet:
        print(json.dumps({l["id"]: l.get("status") + (f": {l.get('reason')}" if l.get("reason") else "") for l in layers}, indent=1, ensure_ascii=False))
        print(f"earth.json and earth/ written to {out} in {earth['took_s']['all']} s")
    return earth


def write_smoke_frames(sdir, now, frames, regional, keep_from, source):
    """The hour itself (full resolution) and the 3-hourly marks (7 days back, as far ahead as the model goes). A past mark is
    written once and kept; marks ahead are rewritten with every new run. Returns (the hour's file name, the frame list, cell size)."""
    os.makedirs(sdir, exist_ok=True)
    hour = now.astimezone(TZ8).replace(minute=0, second=0, microsecond=0)
    by_hour = {t.astimezone(TZ8).replace(minute=0, second=0, microsecond=0): v for t, v in frames.items()}
    if hour not in by_hour:
        return None
    cell = None
    for t, (spec, vals) in by_hour.items():
        name = hour_name(t)
        is_mark = t.hour % FRAME_STEP_H == 0
        if t == hour or (is_mark and (t > hour or not os.path.exists(os.path.join(sdir, f"{name}.json")))):
            if t < now - dt.timedelta(days=PAST_DAYS):
                continue
            if regional and t in regional:
                import grid_spec
                vals = regional_where_finer(spec, vals, grid_spec.BOX, regional[t])
            write_json(os.path.join(sdir, f"{name}.json"), {"at": stamp(t), "grid": spec, "values": vals, "unit": "µg/m³", "kind": "estimated",
                                                             "source": source, "credits": credit_block([source], now)})
            if t == hour:
                cell = spec["step"]
    prune(sdir, keep_from)
    listed = []
    for f in sorted(os.listdir(sdir)):
        stem = f.split(".")[0]
        if len(stem) != 13:
            continue
        t = from_name(stem)
        if t.hour % FRAME_STEP_H == 0 or t == hour:
            listed.append({"at": stamp(t), "file": f"earth/smoke/{f}", "when": "now" if t == hour else ("past" if t < hour else "ahead")})
        elif t < hour:   # an hour that is neither a mark nor now: not listed, removed
            os.remove(os.path.join(sdir, f))
    return hour_name(hour), listed, cell


def write_wind_frames(wdir, now, run, steps, keep_from):
    """The step nearest now at 1 degree, every step ahead at 2 degrees; past frames kept as written. Returns the layer's fields."""
    os.makedirs(wdir, exist_ok=True)
    valid = {run + dt.timedelta(hours=s): s for s in steps}
    nearest = min(valid, key=lambda t: abs((t - now).total_seconds()))
    for t, s in valid.items():
        name = hour_name(t)
        p = os.path.join(wdir, f"{name}.json")
        if t < nearest and os.path.exists(p):
            continue   # the past as it was shown
        spec, u, v = steps[s]
        if t != nearest:
            spec, u, v = coarser(spec, u, v)
        if t < now - dt.timedelta(days=PAST_DAYS):
            continue
        write_json(p, {"at": stamp(t), "run": stamp(run), "grid": spec, "u": u, "v": v, "unit": "km/h", "kind": "estimated", "source": "GFS",
                       "credits": credit_block(["GFS"], now)})
    prune(wdir, keep_from)
    frames = []
    for f in sorted(os.listdir(wdir)):
        stem = f.split(".")[0]
        t = from_name(stem)
        frames.append({"at": stamp(t), "file": f"earth/wind/{f}", "when": "now" if t == nearest else ("past" if t < nearest else "ahead")})
    return {"now": f"earth/wind/{hour_name(nearest)}.json", "covers": {"at": stamp(nearest)}, "frames": frames, "cell_deg": 1.0, "cell_km": 111}


def fire_days(fdir, now, rows):
    """The last 7 whole local days, 1 file each, written once. The day before yesterday and older come from rows when they cover
    them, else from their own request (2 UTC days hold 1 local day). Returns [{date, file, detections}]."""
    os.makedirs(fdir, exist_ok=True)
    today = now.astimezone(TZ8).date()
    out = []
    for k in range(PAST_DAYS, 0, -1):
        d = today - dt.timedelta(days=k)
        p = os.path.join(fdir, f"{d.isoformat()}.json")
        if not os.path.exists(p):
            lo = dt.datetime.combine(d, dt.time(0), TZ8)
            hi = lo + dt.timedelta(days=1)
            src = rows if rows and min(t for t, _a, _b in rows) <= lo.astimezone(UTC) else None
            if src is None:
                try:
                    src = fetch_firms_world((lo.astimezone(UTC).date()).isoformat(), 2)
                except FetchError:
                    continue   # that day says it has nothing; the next run asks again
            cells, n = fire_cells(src, lo, hi)
            if n == 0:
                continue
            write_json(p, {"schema_version": "1", "date": d.isoformat(), "from": stamp(lo), "to": stamp(hi), "columns": ["lat", "lon", "count"],
                           "cells": cells, "detections": n, "credits": credit_block(["FIRMS"], now)})
        got = read_json(p)
        if got:
            out.append({"date": d.isoformat(), "file": f"earth/fires/{d.isoformat()}.json", "detections": got["detections"]})
    for f in os.listdir(fdir):
        if f[:10] < (today - dt.timedelta(days=PAST_DAYS)).isoformat():
            os.remove(os.path.join(fdir, f))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.environ.get("FEED_OUT", os.path.join(ROOT, "web", "public", "feed")))
    ap.add_argument("--at", help="build as of this local time")
    ap.add_argument("--offline", action="store_true", help="replay the answers recorded on 16 Oct 2026 (8:49 am)")
    ap.add_argument("--cache", default=os.path.join(ROOT, ".cache"))
    a = ap.parse_args()
    import envfile
    envfile.load_env()
    import build_feed
    if a.offline:
        os.environ.pop("ADS_KEY", None)
        build_earth(a.out, at=a.at or REPLAY_AT, transport_=transport.Replay((RECORDED, transport.RECORDED)), cache=os.path.join(a.cache, "replay-earth"),
                    grid_day=build_feed.grid_day)
    else:
        build_earth(a.out, at=a.at, cache=a.cache, grid_day=build_feed.grid_day)


if __name__ == "__main__":
    main()
