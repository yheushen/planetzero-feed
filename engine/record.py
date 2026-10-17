"""Planet Zero's record (session 8e, part 143i; the owner, 17 Oct 2026, 7:39 pm and 8:05 pm): what the site showed, kept every hour, so anyone can go
back and check. Not an audit: there is no independent truth to compare a picture against. Each hour, after the feed is built:

  hours/<YYYY-MM-DDTHH>/data/      the hour's data as a small feed the site reads (part 143j replays it), each file gzipped (name.json.gz,
                                   about a fifth of the size; the replay unzips it in the browser): the page files (now,
                                   outlook, checks, status, scales, grid, audit.json and Gemini's index without its long list), earth.json
                                   with its layers' frames cut to the hour, the hour's smoke (the model and the field adjusted to the
                                   monitors), wind, fires, monitors, Highest now, satellites, poles; and (part 152) the feed's history/ cut
                                   to the 48 hours up to the hour (history/<source>/<YYYY-MM>.json.gz), so a replay reads the history as it
                                   stood then. The day's Real Earth picture once a day at real/<date>-2048.webp (earth.json points there).
  hours/<YYYY-MM-DDTHH>/manifest.json  the hour (Malaysia time and UTC), the feed's times, the model's run and source, the monitors the
                                   adjustment used, the fires' window and count, the wind's time and source, NEA's and DOE's newest, the layers
                                   and what was left out and why, the code's sha, the credit line, each data file with its bytes.
  hours/<...>/*.webp               pictures of the map the site drew (record_shots.py, part 153: the map alone, never the site's header,
                                   menu or panels, with a 2-line strip of key and times under it): the default view's thumbnail every hour,
                                   full size every 3 hours; each day's worst hour over Southeast Asia in 4 views, landed once when the day ends.
  days/<date>.json, index.json     each day's hours (with each picture's strip), its worst hour, its 4 views and their thumbnails; every hour.
  today.json                       which hour today's 4 views show, on the branch `today` (below).
  timelapse/                       1 frame a day at its worst hour, Real Earth and Plain, MP4 and GIF (part 143j, record_timelapse.py),
                                   made when a day has ended.

Written once (part 152, the owner, 17 Oct, 11:30 pm: keep every hour, nothing thinned, nothing deleted): a kept hour's data and manifest
are written by the first build of that hour and never again; a picture on main is written once. Only the indexes (index.json, days/,
today.json) change from hour to hour. What is drawn again during a day lives on a branch that is replaced, never on main: today's 4 views
(drawn at each 3-hourly capture, the branch `today`, 1 commit) and the time-lapse (the branch `timelapse`). The day's final 4 views land on
main once, the first hour after the day ends. The feed's history/ is no longer copied to the record's root every hour (that rewrote this
month's files every hour): each hour keeps its own 48 hours; the root's history/ stays as it was on 18 Oct 2026 (nothing deleted).

Size (session 8e): about 0.8 MB of data an hour, compressed, plus about 35 KB of history; every hour kept. GitHub Pages publishes at most
1 GB (the projection: PROGRESS.md).

Terms (docs/TERMS-CHECK-RECORD-2026-10-18.md): aqicn's value is never kept (removed from now.json); OpenAQ locations under CC BY-SA 4.0
are left out of the kept monitors (live only, as in history/); BMKG's readings are left out of the kept monitors (part 154: the owner's
exception to its terms covers the live map and the scorer only); Google is never in the feed; NASA's daily layers other than Real Earth
are kept as the date to ask GIBS for. Standard library only (the pictures need Playwright: record_shots.py).
"""
import argparse
import datetime as dt
import gzip
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TZ8 = dt.timezone(dt.timedelta(hours=8))
SEA = (92.0, -12.0, 142.0, 24.0)   # Southeast Asia: lon from, lat from, lon to, lat to (the Flat view's box)
HIGH = 151                       # NEA's hourly PM2.5 bands: High from 151 µg/m³ (engine/schema/scales.json)
LIVE_ONLY = {"CC BY-SA 4.0"}     # licences whose locations are shown live and never kept (as in history/)
NOT_KEPT_PROVIDERS = {"BMKG"}    # part 154: shown live by the owner's exception to its terms, never kept
PAGE_FILES = ("now.json", "outlook.json", "checks.json", "status.json", "scales.json", "grid.json", "audit.json")
FULL_EVERY_H = 3                 # full size every 3 hours; today's 4 views drawn at the same captures
HISTORY_H = 48                   # each hour keeps the feed's history of the 48 hours to it (a monitor's card reads the last 24)
VIEWS = ("globe-real", "globe-plain", "flat-real", "flat-plain")
DEFAULT_VIEW = "globe-real"
TODAY = ".today"                 # today's 4 views, drawn here and pushed by the Action as the branch `today` (1 commit, replaced)
TODAY_BASE = "https://raw.githubusercontent.com/yheushen/planetzero-record/today/"
CREDIT = ("Kept by Planet Zero from what its site showed. Smoke: generated using Copernicus Atmosphere Monitoring Service information 2026, "
          "adjusted to the monitors; neither the European Commission nor ECMWF is responsible for any use. Wind: NOAA GFS via NOMADS. Fires: NASA "
          "FIRMS (LANCE, ESDIS). Pictures: NASA GIBS (ESDIS). Monitors: NEA via data.gov.sg (Singapore Open Data Licence 1.0), DOE Malaysia "
          "(Malaysian Government Open Data Terms of Use 1.0), OpenAQ and each owner under its licence. Made with Natural Earth. Maps: "
          "OpenFreeMap, © OpenMapTiles, © OpenStreetMap contributors.")


def stamp(t):
    return t.astimezone(TZ8).isoformat(timespec="minutes")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_if_changed(path, data):
    """An index written only when its content changes, so an hour's commit touches only the indexes that did."""
    path = Path(path)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def hour_of(feed):
    """The feed's hour, Malaysia time: the hour now.json was built in (an hourly build at :08 to :50 is that hour's)."""
    t = dt.datetime.fromisoformat(read(Path(feed) / "now.json")["generated_at"]).astimezone(TZ8)
    return t.replace(minute=0, second=0, microsecond=0)


def hour_name(t):
    return t.astimezone(TZ8).strftime("%Y-%m-%dT%H")


def sha():
    try:
        return subprocess.run(["git", "-C", str(HERE.parent), "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def high_area(adjusted):
    """Southeast Asia's area High or worse in the field adjusted to the monitors, in km² (each 0.4 degree cell by its latitude)."""
    import math
    g = adjusted["grid"]
    v = adjusted["values"]
    km = 111.2 * g["step"]
    area = 0.0
    for i in range(g["nlat"]):
        lat = g["lat0"] + i * g["step"]
        if not SEA[1] <= lat <= SEA[3]:
            continue
        row = i * g["nlon"]
        for j in range(g["nlon"]):
            lon = g["lon0"] + j * g["step"]
            lon = lon - 360 if lon > 180 else lon
            if SEA[0] <= lon <= SEA[2]:
                x = v[row + j]
                if x is not None and x >= HIGH:
                    area += km * km * math.cos(math.radians(lat))
    return round(area)


def frame_at(frames, t):
    """The frame a page shows at hour t: the latest at or before it, else the first."""
    best = None
    for f in frames:
        at = dt.datetime.fromisoformat(f["at"])
        if at <= t and (best is None or at > dt.datetime.fromisoformat(best["at"])):
            best = f
    return best or (frames[0] if frames else None)


def keep_monitors(m):
    """The monitors file without the locations that are shown live only: under a share-alike licence, or BMKG's (part 154).
    Returns (kept, [(what, count, why)])."""
    li = m["columns"].index("licence")
    pi = m["columns"].index("provider") if "provider" in m["columns"] else None
    live_only = {i for i, name in enumerate(m["licences"]) if name in LIVE_ONLY}
    providers = m.get("providers") or []

    def provider(r):
        if pi is None:
            return None
        p = r[pi]
        return providers[p] if isinstance(p, int) and p < len(providers) else p
    sa = [r for r in m["rows"] if r[li] in live_only]
    bmkg = [r for r in m["rows"] if r[li] not in live_only and provider(r) in NOT_KEPT_PROVIDERS]
    rows = [r for r in m["rows"] if r[li] not in live_only and provider(r) not in NOT_KEPT_PROVIDERS]
    gone = []
    if sa:
        gone.append(("monitors under CC BY-SA 4.0", len(sa), "share-alike: shown live, never kept (as in history/)"))
    if bmkg:
        gone.append(("BMKG's monitors", len(bmkg), "BMKG's terms forbid automated collection: shown live by the owner's exception (18 Oct 2026), never kept"))
    return {**m, "rows": rows}, gone


def history_slice(d, lo, hi):
    """A history file cut to the hours lo < t <= hi ('YYYY-MM-DDTHH:MM'): its description kept, its series and locations cut; None if empty."""
    ser = {}
    for sid, s in d.get("series", {}).items():
        cut = {k: v for k, v in s.items() if lo < k <= hi}
        if cut:
            ser[sid] = cut
    if not ser:
        return None
    out = {k: v for k, v in d.items() if k not in ("series", "locations")}
    out["series"] = ser
    if "locations" in d:
        out["locations"] = {k: v for k, v in d["locations"].items() if k in ser}
    return out


def history_files(hist, t):
    """{'history/<source>/<YYYY-MM>.json': the cut file} for the HISTORY_H hours to hour t, from a history/ folder."""
    hist = Path(hist)
    if not hist.is_dir():
        return {}
    lo = (t - dt.timedelta(hours=HISTORY_H)).strftime("%Y-%m-%dT%H:%M")
    hi = t.strftime("%Y-%m-%dT%H") + ":59"
    months = sorted({t.strftime("%Y-%m"), (t - dt.timedelta(hours=HISTORY_H)).strftime("%Y-%m")})
    out = {}
    for src in sorted(p for p in hist.iterdir() if p.is_dir()):
        for mo in months:
            f = src / f"{mo}.json"
            if f.exists():
                cut = history_slice(read(f), lo, hi)
                if cut:
                    out[f"history/{src.name}/{mo}.json"] = cut
    return out


def keep_hour(feed, record, backfilled=False, commit=None, now=None):
    """The hour's data into record/hours/<hour>/data/ and its manifest, written once: the first build of an hour is kept, and a later
    build in the same hour changes nothing (part 152). Returns the manifest (with kept_before when it was there already)."""
    feed, record = Path(feed), Path(record)
    t = hour_of(feed)
    name = hour_name(t)
    root = record / "hours" / name
    if (root / "manifest.json").exists():
        return {**read(root / "manifest.json"), "kept_before": True}
    data = root / "data"
    if data.exists():   # a run that failed before its manifest left half an hour (never committed): written again
        shutil.rmtree(data)
    data.mkdir(parents=True)
    left_out, files = [], {}

    def put(rel, blob):
        dst = data / (rel + ".gz")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(gzip.compress(blob, compresslevel=9, mtime=0))
        files[rel] = dst.stat().st_size

    def copy(rel):
        src = feed / rel
        if src.exists():
            if rel not in files:
                put(rel, src.read_bytes())
            return True
        return False

    def put_json(rel, obj):
        put(rel, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    for rel in PAGE_FILES:
        if rel == "now.json" and (feed / rel).exists():
            n = read(feed / rel)
            gone = 0
            for p in n.get("places", []):
                before = len(p.get("others", []))
                p["others"] = [o for o in p.get("others", []) if o.get("source") != "aqicn"]
                gone += before - len(p["others"])
            put_json(rel, n)
            if gone:
                left_out.append({"what": "aqicn's values", "count": gone, "why": "its terms: shown live with credit, never kept (docs/DATA-TERMS.md)"})
            continue
        copy(rel)
    gi = feed / "audit" / "index-gemini.json"
    if gi.exists():
        put_json("audit/index-gemini.json", {k: v for k, v in read(gi).items() if k != "answers"})
    e = read(feed / "earth.json")
    layers = []
    info = {}
    for lay in e.get("layers", []):
        lay = dict(lay)
        lid = lay.get("id")
        if lid in ("smoke", "wind") and lay.get("frames"):
            f = frame_at(lay["frames"], t)
            if lid == "smoke":
                info["smoke_fields"] = [x for x in ((lay.get("adjusted") or {}).get("file"), lay.get("now"), f and f["file"]) if x]
            lay["frames"] = [f] if f else []
            if f:
                copy(f["file"])
            if lay.get("now"):
                copy(lay["now"])
            if lid == "smoke" and lay.get("adjusted", {}).get("file"):
                copy(lay["adjusted"]["file"])
                info["adjusted"] = {"used": lay["adjusted"].get("used"), "left_out": lay["adjusted"].get("left_out")}
            info[lid] = {"made_at": lay.get("made_at"), "at": (lay.get("covers") or {}).get("at"), "frame": f and f["at"], "source": lay.get("source")}
        elif lid == "fires":
            for k in ("file", "sea_file"):
                if lay.get(k):
                    copy(lay[k])
            lay["days"] = []   # the 7 days' files are the live window's; the record keeps each hour's 24 hours
            info["fires"] = {"from": (lay.get("covers") or {}).get("from"), "to": (lay.get("covers") or {}).get("to"), "detections": lay.get("detections"),
                             "southeast_asia": lay.get("sea_fires")}
        elif lid == "monitors" and lay.get("file") and (feed / lay["file"]).exists():
            kept, gone = keep_monitors(read(feed / lay["file"]))
            put_json(lay["file"], kept)
            lay["count"] = len(kept["rows"])
            info["monitors"] = {"count": len(kept["rows"]), "made_at": lay.get("made_at")}
            left_out += [{"what": w, "count": c, "why": y} for w, c, y in gone]
        elif lid == "real_earth" and lay.get("day_picture"):
            dp = dict(lay["day_picture"])
            sizes = []
            for s in dp.get("sizes", []):
                if s.get("width") != 2048:
                    continue
                pic = record / "real" / Path(s["webp"]).name   # once a day at the record's root, not in every hour
                if not pic.exists() and (feed / s["webp"]).exists():
                    pic.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(feed / s["webp"], pic)
                up = f"../../../real/{Path(s['webp']).name}"
                sizes.append({**s, "webp": up, "jpg": up})
            dp["sizes"] = sizes
            lay["day_picture"] = dp
            info["real_earth"] = {"date": (lay.get("covers") or {}).get("date")}
        elif lay.get("file"):
            copy(lay["file"])
        if lay.get("gibs") or (lay.get("picture") and lid != "real_earth"):
            info.setdefault("gibs_dates", {})[lid] = (lay.get("covers") or {}).get("date")
        layers.append(lay)
    hi = e.get("highest") or {}
    if hi.get("file"):
        copy(hi["file"])
    if (feed / "earth" / "poles.json").exists():
        copy("earth/poles.json")
    for rel, cut in history_files(feed / "history", t).items():   # part 152: the history as it stood at this hour, its own
        put_json(rel, cut)
    put_json("earth.json", {**e, "layers": layers, "kept": {"hour": stamp(t), "note": "A kept hour: each layer's frames cut to this hour (engine/record.py)."}})
    st = read(feed / "status.json") if (feed / "status.json").exists() else {}
    # the day's worst hour is measured on the field adjusted to the monitors; before it existed (16 Oct), on the model's own at the hour
    area, area_from = None, None
    for rel in info.get("smoke_fields", []):
        if rel in files and (feed / rel).exists():
            fld = read(feed / rel)
            if fld.get("grid") and fld.get("values"):
                area, area_from = high_area(fld), ("adjusted" if "adjusted" in rel else "model")
                break
    n = read(feed / "now.json")
    man = {
        "schema_version": "1", "hour": stamp(t), "hour_utc": t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "feed_generated_at": n.get("generated_at"), "earth_generated_at": e.get("generated_at"),
        "smoke": {**info.get("smoke", {}), "adjusted": info.get("adjusted")}, "wind": info.get("wind"), "fires": info.get("fires"),
        "monitors": info.get("monitors"), "real_earth": info.get("real_earth"), "gibs_dates": info.get("gibs_dates", {}),
        "nea_newest": (st.get("sources", {}).get("NEA") or {}).get("latest"), "doe_newest": (st.get("sources", {}).get("DOE") or {}).get("latest"),
        "layers": [{"id": x.get("id"), "status": x.get("status"), "late": bool(x.get("late"))} for x in layers],
        "left_out": left_out, "high_area_km2": area, "high_area_from": area_from, "renderer": sha(), "credit": CREDIT,
        "files": sorted(files), "bytes": {k: files[k] for k in sorted(files)}, "history_hours": HISTORY_H,
        "backfilled": bool(backfilled), **({"commit": commit} if commit else {}), "kept_at": stamp(now or dt.datetime.now(TZ8)),
    }
    write(root / "manifest.json", man)
    return man


def size_problems(record, name):
    """A kept hour whose manifest's bytes are not its files' (part 152): [what differs]."""
    root = Path(record) / "hours" / name
    man = read(root / "manifest.json")
    out = []
    by = man.get("bytes")
    if by is None:
        return ["no bytes in the manifest"]
    if sorted(by) != sorted(set(man.get("files", []))):
        out.append("the files and the bytes list different files")
    for rel, n in by.items():
        f = root / "data" / (rel + ".gz")
        if not f.exists():
            out.append(f"{rel}: missing")
        elif f.stat().st_size != n:
            out.append(f"{rel}: {f.stat().st_size} bytes, the manifest says {n}")
    on_disk = {p.relative_to(root / "data").as_posix()[:-3] for p in (root / "data").rglob("*.gz")}
    out += [f"{rel}: on disk, not in the manifest" for rel in sorted(on_disk - set(by))]
    return out


# ---------------------------------------------------------------- the strip under a kept picture (part 153, frame 09 D)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Plain colours the smoke by the ramp (web/src/earth/ramp.ts, part 124), copied here; evals/record2 checks they are the same
RAMP = [(0, 118, 196, 214), (12, 72, 176, 168), (35, 118, 188, 98), (55, 204, 206, 72), (62, 246, 196, 84), (150, 238, 140, 45),
        (158, 222, 98, 40), (250, 186, 56, 30), (262, 136, 34, 50), (420, 80, 18, 52)]
RAMP_WORDS = [("Normal", "greens"), ("Elevated", "amber"), ("High", "orange red"), ("Very high", "maroon")]
RAMP_AT = (35, 100, 200, 330)    # each band's swatch: the ramp's colour inside it


def ramp_rgb(v):
    if v <= RAMP[0][0]:
        return RAMP[0][1:]
    for k in range(1, len(RAMP)):
        if v <= RAMP[k][0]:
            v0, *c0 = RAMP[k - 1]
            v1, *c1 = RAMP[k]
            f = (v - v0) / (v1 - v0)
            return tuple(round(a + (b - a) * f) for a, b in zip(c0, c1))
    return RAMP[-1][1:]


def key_of(view):
    """The smoke's 4 bands as the view draws them: [(word, colour's name, '#rrggbb')]. Real Earth: NEA's band colours (scales.json);
    Plain: the ramp's (part 124)."""
    if view.endswith("plain"):
        return [(w, c, "#%02X%02X%02X" % ramp_rgb(v)) for (w, c), v in zip(RAMP_WORDS, RAMP_AT)]
    bands = read(HERE / "schema" / "scales.json")["hourly_pm25"]["bands"]
    return [(b["word"], b["colour_name"], b["colour"]) for b in bands]


def clock(t):
    return f"{(t.hour % 12) or 12}:{t.minute:02d} {'am' if t.hour < 12 else 'pm'}"


def day_words(d):
    return f"{d.day} {MONTHS[d.month - 1]}"


def when_words(iso, on):
    """A time as the strip says it: '5:00 pm' on the kept hour's own day, '17 Oct, 11:00 pm' on another."""
    t = dt.datetime.fromisoformat(iso).astimezone(TZ8)
    return clock(t) if t.date() == on else f"{day_words(t)}, {clock(t)}"


def strip_words(man, view):
    """The strip under a kept picture (frame 09 D), from the hour's manifest: {"head", "smoke", "key": [(word, colour's name, hex)],
    "tail", "text"}. The hour in Malaysia time; the smoke an estimate from a computer model, its run; the key, each colour named; the
    wind's source and time; the fires' source and window; the base; "Kept by planetzero.ai." A layer late at the hour says so."""
    t = dt.datetime.fromisoformat(man["hour"]).astimezone(TZ8)
    on = t.date()
    late = {x["id"] for x in man.get("layers", []) if x.get("late")}
    lateness = lambda lid: ", late" if lid in late else ""   # noqa: E731
    sm = man.get("smoke") or {}
    src = sm.get("source") or "CAMS"
    src = "CAMS" if "CAMS" in src.upper() else src
    run = f", run of {when_words(sm['made_at'], on)}" if sm.get("made_at") else ""
    adj = ", adjusted to the monitors" if sm.get("adjusted") else ""
    smoke = f"Smoke: an estimate from a computer model ({src}{run}){adj}{lateness('smoke')}."
    tail = []
    w = man.get("wind") or {}
    if w.get("frame") or w.get("at"):
        tail.append(f"Wind: {w.get('source') or 'GFS'}, {when_words(w.get('frame') or w.get('at'), on)}{lateness('wind')}.")
    f = man.get("fires") or {}
    if f.get("from") and f.get("to"):
        hours = round((dt.datetime.fromisoformat(f["to"]) - dt.datetime.fromisoformat(f["from"])).total_seconds() / 3600)
        tail.append(f"Fires: NASA FIRMS, {hours} hours{lateness('fires')}.")
    if view.endswith("real"):
        d = (man.get("real_earth") or {}).get("date")
        tail.append(f"Photo: NASA GIBS, {day_words(dt.date.fromisoformat(d))}." if d else "Photo: NASA GIBS.")
    else:
        tail.append("Base: Natural Earth, OpenFreeMap." if view.startswith("flat") else "Base: Natural Earth.")
    tail.append("Kept by planetzero.ai.")
    head = f"{day_words(t)}, {clock(t)}, Malaysia time."
    key = key_of(view)
    text = " ".join([head, smoke, " ".join(f"■ {w_}, {c}" for w_, c, _ in key) + "."] + tail)
    return {"head": head, "smoke": smoke, "key": key, "tail": " ".join(tail), "text": text}


# ---------------------------------------------------------------- what is drawn when
def today_state(record):
    """today.json: which hour today's 4 views on the branch `today` show, or None."""
    f = Path(record) / "today.json"
    return read(f) if f.exists() else None


def pictures_due(record, t):
    """What to draw at hour t: [(hour name, view, full?, where)], where "main" (written once, never over a file already there) or "today"
    (the branch `today`, replaced). The default view's thumbnail every hour, full size every 3 hours; the day before's worst hour in its 4
    views on main, until they are there (the day's final 4 land once); at each 3-hourly capture, today's worst hour so far in 4 views on
    the branch `today`, unless they show that hour already."""
    record = Path(record)
    t = t.astimezone(TZ8)
    name = hour_name(t)
    capture = t.hour % FULL_EVERY_H == 0
    due = [(name, DEFAULT_VIEW, capture, "main")]
    prev = (t.date() - dt.timedelta(days=1)).isoformat()
    w = worst_hour(record, prev)
    if w:
        due += [(w, v, True, "main") for v in VIEWS if not (record / "hours" / w / f"{v}.webp").exists()]
    if capture:
        w = worst_hour(record, t.date().isoformat())
        st = today_state(record)
        if w and not (st and st.get("date") == t.date().isoformat() and st.get("hour") == w and sorted(st.get("views", [])) == sorted(VIEWS)):
            due += [(w, v, True, "today") for v in VIEWS]
    return due


def note_today(record, due, now=None):
    """After drawing: today.json (on main, an index) and the branch's own copy, when today's 4 views were drawn; and the mark that has the
    Action push the branch `today` this run. Returns the state, or None."""
    record = Path(record)
    hours = sorted({h for h, _, _, where in due if where == "today"})
    if len(hours) != 1:
        return None
    h = hours[0]
    views = [v for v in VIEWS if (record / TODAY / "hours" / h / f"{v}.webp").exists() and (record / TODAY / "hours" / h / f"{v}-thumb.webp").exists()]
    if not views:
        return None
    st = {"date": h[:10], "hour": h, "views": views, "drawn_at": stamp(now or dt.datetime.now(TZ8)), "base": TODAY_BASE,
          "what": "Today's worst hour so far over Southeast Asia, drawn at each 3-hourly capture on the branch today, replaced each time; the "
                  "day's final 4 land on main once, the first hour after the day ends."}
    write(record / "today.json", st)
    write(record / TODAY / "today.json", st)
    (record / TODAY / ".made").write_text(st["drawn_at"] + "\n", encoding="utf-8")
    return st


def worst_hour(record, date):
    """The day's hour with the most area High or worse over Southeast Asia (the earliest on a tie), from the kept manifests."""
    best = None
    for m in sorted((Path(record) / "hours").glob(f"{date}T*/manifest.json")):
        a = read(m).get("high_area_km2")
        if a is not None and (best is None or a > best[0]):
            best = (a, m.parent.name)
    return best and best[1]


def day_views(record, d, w, ended, st):
    """A day's 4 views and their thumbnails ({view: URL}) and the hour they show. On main (a URL relative to the record's root) for a
    day that has ended; today's from the branch `today` (absolute) once drawn, else what main has. A view not drawn is left out."""
    if not ended and st and st.get("date") == d:
        h = st["hour"]
        return ({v: f"{TODAY_BASE}hours/{h}/{v}.webp" for v in st["views"]}, {v: f"{TODAY_BASE}hours/{h}/{v}-thumb.webp" for v in st["views"]}, h)
    views, thumbs = {}, {}
    if w:
        for v in VIEWS:
            if (Path(record) / "hours" / w / f"{v}.webp").exists():
                views[v] = f"hours/{w}/{v}.webp"
            if (Path(record) / "hours" / w / f"{v}-thumb.webp").exists():
                thumbs[v] = f"hours/{w}/{v}-thumb.webp"
    return views, thumbs, w


def index(record, today=None):
    """days/<date>.json and index.json from the kept manifests and the pictures on disk; the manifests are only read (written once).
    Each day: its worst hour, whether it is final (ended, its 4 views on main), its 4 views and thumbnails, the hour they show; each
    hour in its day's file with the strip of each view."""
    record = Path(record)
    hours, strips = [], {}
    for m in sorted((record / "hours").glob("*/manifest.json")):
        man = read(m)
        pics = sorted(p.name for p in m.parent.glob("*.webp"))
        hours.append({"hour": man["hour"], "name": m.parent.name, "backfilled": man.get("backfilled", False), "high_area_km2": man.get("high_area_km2"),
                      "data": (m.parent / "data").exists(),
                      "pictures": pics, "late": [x["id"] for x in man.get("layers", []) if x.get("late")], "left_out": [x["what"] for x in man.get("left_out", [])]})
        strips[m.parent.name] = {v: strip_words(man, v)["text"] for v in VIEWS}
    days = {}
    for h in hours:
        days.setdefault(h["name"][:10], []).append(h)
    ignore_branch_files(record)
    st = today_state(record)
    out = []
    for d, hs in sorted(days.items()):
        w = worst_hour(record, d)
        ended = today is None or d < today
        views, thumbs, vh = day_views(record, d, w, ended, st)
        final = ended and all(views.get(v) == f"hours/{w}/{v}.webp" for v in VIEWS)
        item = {"date": d, "worst": w, "hours": len(hs), "final": final, "views_hour": vh, "views": views, "thumbs": thumbs}
        out.append(item)
        write_if_changed(record / "days" / f"{d}.json", {**item, "hours": [{**h, "strip": strips[h["name"]]} for h in hs], "worst_final": ended, "credit": CREDIT})
    for f in (record / "days").glob("*.json") if (record / "days").is_dir() else []:
        if f.stem not in days:
            f.unlink()
    write_if_changed(record / "index.json", {"schema_version": "1", "what": "What the Planet Zero site showed, kept every hour: the data each view was drawn from, "
                                             "and pictures of the map it drew. A record, not a measurement: the smoke is an estimate from a computer model, adjusted "
                                             "to the monitors.", "first": hours[0]["hour"] if hours else None, "last": hours[-1]["hour"] if hours else None,
                                             "days": out, "hours": hours, "timelapse": timelapse_of(record), "credit": CREDIT})
    return hours


def timelapse_of(record):
    """The time-lapse's days and files, for the record's pages (part 143j); None until the first day has ended."""
    f = Path(record) / "timelapse" / "timelapse.json"
    if not f.exists():
        return None
    t = read(f)
    import record_timelapse
    return {"days": [x["date"] for x in t.get("frames", [])], "made_at": t.get("made_at"), "base": record_timelapse.TIMELAPSE_BASE,
            "files": {look: {kind: v["path"] for kind, v in kinds.items()} for look, kinds in t.get("files", {}).items()}}


IGNORE = ("timelapse/*.mp4", "timelapse/*.gif", "timelapse/.made", f"{TODAY}/")


def ignore_branch_files(record):
    """The time-lapse's files and today's views live on their own branches (record_timelapse.py; the Action): main ignores them."""
    f = Path(record) / ".gitignore"
    have = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    want = [x for x in IGNORE if x not in have]
    if want:
        f.write_text("\n".join(have + ["# on their own branches, replaced: the time-lapse (`timelapse`, part 143j), today's 4 views (`today`, part 153)"] + want) + "\n",
                     encoding="utf-8")


ignore_timelapse = ignore_branch_files   # the name of part 143j


def backfill(repo, record, site=None, since=None):
    """Session 8e, part 143i: every hour the feed's git history holds (its latest build of each hour), kept the same way, marked backfilled
    with the commit it came from, its pictures drawn as if it were that hour. An hour already kept stays as it is. Returns the hours kept."""
    import io
    import tarfile
    import tempfile
    repo, record = Path(repo), Path(record)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], capture_output=True, check=True).stdout   # noqa: E731
    commits = [l.split() for l in git("log", "--reverse", "--format=%H %cI", "--", "earth.json").decode().splitlines() if l.strip()]
    by_hour = {}
    for sha_, when in commits:
        t = dt.datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(TZ8)
        if since and t < since:
            continue
        by_hour[hour_name(t)] = sha_   # the latest build in each hour
    kept = []
    for name, sha_ in sorted(by_hour.items()):
        have = set(git("ls-tree", "-r", "--name-only", sha_).decode().split())
        want = [f for f in (*PAGE_FILES, "audit/index-gemini.json", "earth.json") if f in have] + (["earth"] if any(h.startswith("earth/") for h in have) else []) \
            + (["history"] if any(h.startswith("history/") for h in have) else [])
        with tempfile.TemporaryDirectory(prefix="pz-backfill-") as tmp:
            with tarfile.open(fileobj=io.BytesIO(git("archive", sha_, *want))) as t:
                t.extractall(tmp, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
            try:
                man = keep_hour(tmp, record, backfilled=True, commit=sha_[:7])
            except Exception as e:   # an hour the code of today cannot read is said, never guessed
                print(f"{name}: not kept ({type(e).__name__}: {str(e)[:120]})")
                continue
        if man.get("kept_before"):
            continue
        t = dt.datetime.fromisoformat(man["hour"])
        if site:
            sys.path.insert(0, str(HERE))
            import record_shots
            due = pictures_due(record, t)
            record_shots.draw(record, due, site)
            note_today(record, due)
        index(record, today=t.date().isoformat())
        kept.append(man["hour"])
        print(f"backfilled {man['hour']} from {sha_[:7]}: {len(man['files'])} files")
    return kept


# ---------------------------------------------------------------- part 152 and 153's 1 migration of the hours kept before them
def migrate(record):
    """Once, for the hours kept before part 152 (16 to 18 Oct 2026): each hour gains its own history (cut from the root's history/, as it
    is on 18 Oct, to the 48 hours to the hour), and its manifest is written once more in today's shape: each file with its bytes, the
    pictures listed in the indexes (not in the manifest), the model's and the wind's source, the migration said. Returns the hours changed."""
    record = Path(record)
    changed = []
    for m in sorted((record / "hours").glob("*/manifest.json")):
        man = read(m)
        if man.get("bytes") is not None:
            continue
        root = m.parent
        t = dt.datetime.fromisoformat(man["hour"]).astimezone(TZ8)
        added = []
        for rel, cut in history_files(record / "history", t).items():
            dst = root / "data" / (rel + ".gz")
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(gzip.compress(json.dumps(cut, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), compresslevel=9, mtime=0))
                added.append(rel)
        e = json.loads(gzip.decompress((root / "data" / "earth.json.gz").read_bytes())) if (root / "data" / "earth.json.gz").exists() else {}
        src = {x.get("id"): x.get("source") for x in e.get("layers", [])}
        files = sorted(set(man.get("files", [])) | set(added))
        new = {k: v for k, v in man.items() if k != "pictures"}
        if new.get("smoke") is not None:
            new["smoke"] = {**new["smoke"], "source": new["smoke"].get("source") or src.get("smoke")}
        if new.get("wind") is not None:
            new["wind"] = {**new["wind"], "source": new["wind"].get("source") or src.get("wind")}
        new["files"] = files
        new["bytes"] = {rel: (root / "data" / (rel + ".gz")).stat().st_size for rel in files if (root / "data" / (rel + ".gz")).exists()}
        new["history_hours"] = HISTORY_H
        new["migrated"] = ("Part 152, 18 Oct 2026: kept before the record was written once; its history (the root's history/ of 18 Oct, cut to the "
                           f"{HISTORY_H} hours to the hour) and each file's bytes added, its pictures listed in the indexes.")
        write(m, new)
        changed.append(root.name)
    return changed


def redraw(record, site, today=None):
    """Part 153, once: every kept picture drawn again as the map alone with its strip, from the kept data. The old pictures (a screenshot
    of the whole page) are removed first; then each hour's default view (thumbnail, full every 3 hours), each ended day's worst hour in 4
    views on main, and today's worst hour so far in 4 views for the branch `today`. Returns the pictures drawn."""
    sys.path.insert(0, str(HERE))
    import record_shots
    record = Path(record)
    today = today or dt.datetime.now(TZ8).date().isoformat()
    for p in (record / "hours").glob("*/*.webp"):
        p.unlink()
    shutil.rmtree(record / TODAY, ignore_errors=True)
    (record / "today.json").unlink(missing_ok=True)
    due = []
    names = sorted(m.parent.name for m in (record / "hours").glob("*/manifest.json"))
    for name in names:
        due.append((name, DEFAULT_VIEW, int(name[11:13]) % FULL_EVERY_H == 0, "main"))
    for d in sorted({n[:10] for n in names}):
        w = worst_hour(record, d)
        if not w:
            continue
        where = "main" if d < today else "today"
        due += [(w, v, True, where) for v in VIEWS if not (where == "main" and v == DEFAULT_VIEW and int(w[11:13]) % FULL_EVERY_H == 0)]
        if where == "main" and int(w[11:13]) % FULL_EVERY_H != 0:   # the worst hour's default view full size too (its thumbnail is there)
            due = [x for x in due if not (x[0] == w and x[1] == DEFAULT_VIEW and x[3] == "main" and not x[2])] + [(w, DEFAULT_VIEW, True, "main")]
    took = record_shots.draw(record, due, site)
    note_today(record, due)
    return took


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--feed", help="the feed folder just built (or checked out at an hour)")
    ap.add_argument("--backfill", metavar="REPO", help="instead: every hour the feed repository's git history holds (a full clone of its feed branch)")
    ap.add_argument("--migrate", action="store_true", help="instead: part 152's 1 migration of the hours kept before it, then the indexes")
    ap.add_argument("--redraw", action="store_true", help="instead: part 153, every kept picture drawn again from the kept data (needs --shots)")
    ap.add_argument("--record", required=True, help="the record repository's folder")
    ap.add_argument("--shots", metavar="SITE", help="also draw the pictures due, with the site's build in this folder (record_shots.py)")
    ap.add_argument("--today", help="the day it is (YYYY-MM-DD, Malaysia time), for --migrate and --redraw; default today")
    ap.add_argument("--backfilled", action="store_true")
    ap.add_argument("--commit")
    a = ap.parse_args()
    if a.backfill:
        hours = backfill(a.backfill, a.record, a.shots)
        print(f"backfilled {len(hours)} hours, {hours[0] if hours else '-'} to {hours[-1] if hours else '-'}")
        return
    if a.migrate or a.redraw:
        today = a.today or dt.datetime.now(TZ8).date().isoformat()
        if a.migrate:
            print(f"migrated {len(migrate(a.record))} hours")
        if a.redraw:
            took = redraw(a.record, a.shots, today)
            print(f"drew {len(took)} pictures in {sum(x[2] for x in took):.0f} s")
        index(a.record, today=today)
        if a.redraw:
            import record_timelapse
            m = record_timelapse.make(a.record, a.shots, force=True)
            index(a.record, today=today)
            print("time-lapse:", "nothing" if m is None else f"{len(m['frames'])} days")
        return
    man = keep_hour(a.feed, a.record, backfilled=a.backfilled, commit=a.commit)
    t = dt.datetime.fromisoformat(man["hour"])
    if a.shots:
        sys.path.insert(0, str(HERE))
        import record_shots
        due = pictures_due(a.record, t)
        record_shots.draw(a.record, due, a.shots)
        note_today(a.record, due)
    index(a.record, today=t.date().isoformat())
    if a.shots:   # the time-lapse, when a day has ended and its 4 views are drawn (nothing otherwise)
        import record_timelapse
        if record_timelapse.make(a.record, a.shots):
            index(a.record, today=t.date().isoformat())
    said = "kept before: nothing rewritten" if man.get("kept_before") else f"{len(man['files'])} files, {len(man['left_out'])} left out"
    print(f"kept {man['hour']}: {said}, High or worse over Southeast Asia {man['high_area_km2']} km²")


if __name__ == "__main__":
    main()
