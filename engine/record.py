"""The record (session 8e, part 143i; the owner, 17 Oct 2026, 7:39 pm and 8:05 pm): what the site showed, kept every hour, so anyone can go
back and check. Not an audit: there is no independent truth to compare a picture against. Each hour, after the feed is built:

  hours/<YYYY-MM-DDTHH>/data/      the hour's data as a small feed the site reads (part 143j replays it), each file gzipped (name.json.gz,
                                   about a fifth of the size; the replay unzips it in the browser): the page files (now,
                                   outlook, checks, status, scales, grid, audit.json and Gemini's index without its long list), earth.json
                                   with its layers' frames cut to the hour, the hour's smoke (the model and the field adjusted to the
                                   monitors), wind, fires, monitors, Highest now, satellites, poles. The day's Real Earth picture once a
                                   day at real/<date>-2048.webp (earth.json points there).
  hours/<YYYY-MM-DDTHH>/manifest.json  the hour (Malaysia time and UTC), the feed's times, the model's run, the monitors the adjustment
                                   used, the fires' window and count, the wind's time, NEA's and DOE's newest, the layers and what was left
                                   out and why, the code's sha, the credit line, the pictures.
  hours/<...>/*.webp               pictures of what the site drew (record_shots.py): the default view's thumbnail every hour, full size
                                   every 3 hours; each day's worst hour over Southeast Asia in 4 views, made the morning after.
  history/                         the feed's history/ once (it only grows: a replay reads the hours before the kept one from it).
  days/<date>.json, index.json     each day's hours, its worst hour and pictures; every hour kept, with its files.

Size (session 8e, Amendment 1): about 1 MB of data an hour, compressed. Past 14 days, an hour's data is kept only every 3 hours and at the
day's worst hour (thin()); the pictures stay. GitHub Pages publishes at most 1 GB.

Terms (docs/TERMS-CHECK-RECORD-2026-10-18.md): aqicn's value is never kept (removed from now.json); OpenAQ locations under CC BY-SA 4.0
are left out of the kept monitors (live only, as in history/); Google is never in the feed; NASA's daily layers other than Real Earth
are kept as the date to ask GIBS for. Standard library only (the pictures need Playwright: record_shots.py).
"""
import argparse
import datetime as dt
import gzip
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TZ8 = dt.timezone(dt.timedelta(hours=8))
SEA = (92.0, -12.0, 142.0, 24.0)   # Southeast Asia: lon from, lat from, lon to, lat to (the Flat view's box)
HIGH = 151                       # NEA's hourly PM2.5 bands: High from 151 µg/m³ (engine/schema/scales.json)
LIVE_ONLY = {"CC BY-SA 4.0"}     # licences whose locations are shown live and never kept (as in history/)
PAGE_FILES = ("now.json", "outlook.json", "checks.json", "status.json", "scales.json", "grid.json", "audit.json")
FULL_EVERY_H = 3
HOURLY_DAYS = 14                 # every hour's data for the last 14 days; then every 3 hours and the day's worst hour
VIEWS = ("globe-real", "globe-plain", "flat-real", "flat-plain")
DEFAULT_VIEW = "globe-real"
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
    """The monitors file without the locations whose licence allows showing them live only."""
    li = m["columns"].index("licence")
    live_only = {i for i, name in enumerate(m["licences"]) if name in LIVE_ONLY}
    rows = [r for r in m["rows"] if r[li] not in live_only]
    return {**m, "rows": rows}, len(m["rows"]) - len(rows)


def keep_hour(feed, record, backfilled=False, commit=None, now=None):
    """The hour's data into record/hours/<hour>/data/, its manifest, the day's and the master index. Returns the manifest."""
    feed, record = Path(feed), Path(record)
    t = hour_of(feed)
    name = hour_name(t)
    root = record / "hours" / name
    data = root / "data"
    if data.exists():
        shutil.rmtree(data)
    data.mkdir(parents=True)
    left_out, files = [], []

    def put(rel, blob):
        dst = data / (rel + ".gz")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(gzip.compress(blob, compresslevel=9, mtime=0))
        files.append(rel)

    def copy(rel):
        src = feed / rel
        if src.exists():
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
            info[lid] = {"made_at": lay.get("made_at"), "at": (lay.get("covers") or {}).get("at"), "frame": f and f["at"]}
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
            if gone:
                left_out.append({"what": "monitors under CC BY-SA 4.0", "count": gone, "why": "share-alike: shown live, never kept (as in history/)"})
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
        "left_out": left_out, "high_area_km2": area, "high_area_from": area_from, "renderer": sha(), "credit": CREDIT, "files": sorted(files),
        "backfilled": bool(backfilled), **({"commit": commit} if commit else {}), "kept_at": stamp(now or dt.datetime.now(TZ8)), "pictures": [],
    }
    old = root / "manifest.json"
    if old.exists():
        man["pictures"] = read(old).get("pictures", [])
    write(root / "manifest.json", man)
    return man


def keep_history(feed, record):
    """The feed's history/ once at the record's root: it only grows, so the latest copy holds every hour before a kept one."""
    src = Path(feed) / "history"
    if src.is_dir():
        dst = Path(record) / "history"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def pictures_due(record, t, kept_hours=None):
    """What to draw at hour t: the default view's thumbnail (every hour), full size every 3 hours; and once a day, at the first kept hour of a
    new day, the day before's worst hour in 4 views. [(hour name, view, full?)]."""
    record = Path(record)
    name = hour_name(t)
    due = [(name, DEFAULT_VIEW, t.hour % FULL_EVERY_H == 0)]
    day = t.astimezone(TZ8).date()
    prev = (day - dt.timedelta(days=1)).isoformat()
    worst = worst_hour(record, prev)
    if worst and not (record / "hours" / worst / "flat-plain.webp").exists():
        due += [(worst, v, True) for v in VIEWS]
    return due


def worst_hour(record, date):
    """The day's hour with the most area High or worse over Southeast Asia (the earliest on a tie), from the kept manifests."""
    best = None
    for m in sorted((Path(record) / "hours").glob(f"{date}T*/manifest.json")):
        a = read(m).get("high_area_km2")
        if a is not None and (best is None or a > best[0]):
            best = (a, m.parent.name)
    return best and best[1]


def thin(record, today):
    """Past HOURLY_DAYS days, an hour's data stays only every 3 hours and at the day's worst hour; its manifest and pictures stay."""
    record = Path(record)
    cut = (dt.date.fromisoformat(today) - dt.timedelta(days=HOURLY_DAYS)).isoformat()
    gone = 0
    for m in sorted((record / "hours").glob("*/manifest.json")):
        name = m.parent.name
        if name[:10] >= cut or int(name[11:13]) % FULL_EVERY_H == 0 or worst_hour(record, name[:10]) == name:
            continue
        if (m.parent / "data").exists():
            shutil.rmtree(m.parent / "data")
            man = read(m)
            man["data_thinned"] = True
            write(m, man)
            gone += 1
    return gone


def index(record, today=None):
    """days/<date>.json and index.json from the kept manifests and the pictures on disk."""
    record = Path(record)
    hours = []
    for m in sorted((record / "hours").glob("*/manifest.json")):
        man = read(m)
        pics = sorted(p.name for p in m.parent.glob("*.webp"))
        if pics != man.get("pictures"):
            man["pictures"] = pics
            write(m, man)
        hours.append({"hour": man["hour"], "name": m.parent.name, "backfilled": man.get("backfilled", False), "high_area_km2": man.get("high_area_km2"),
                      "data": (m.parent / "data").exists(),
                      "pictures": pics, "late": [x["id"] for x in man.get("layers", []) if x.get("late")], "left_out": [x["what"] for x in man.get("left_out", [])]})
    days = {}
    for h in hours:
        days.setdefault(h["name"][:10], []).append(h)
    shutil.rmtree(record / "days", ignore_errors=True)
    for d, hs in days.items():
        w = worst_hour(record, d)
        complete = today is None or d < today
        write(record / "days" / f"{d}.json", {"date": d, "hours": hs, "worst": w, "worst_final": complete, "credit": CREDIT})
    write(record / "index.json", {"schema_version": "1", "what": "What the Planet Zero site showed, kept every hour: the data each view was drawn from, "
                                  "and pictures of what it drew. A record, not a measurement: the smoke is an estimate from a computer model, adjusted "
                                  "to the monitors.", "first": hours[0]["hour"] if hours else None, "last": hours[-1]["hour"] if hours else None,
                                  "days": [{"date": d, "worst": worst_hour(record, d), "hours": len(hs)} for d, hs in sorted(days.items())],
                                  "hours": hours, "credit": CREDIT})
    return hours


def backfill(repo, record, site=None, since=None):
    """Session 8e, part 143i: every hour the feed's git history holds (its latest build of each hour), kept the same way, marked backfilled
    with the commit it came from, its pictures drawn as if it were that hour. Returns the hours kept."""
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
        want = [f for f in (*PAGE_FILES, "audit/index-gemini.json", "earth.json") if f in have] + (["earth"] if any(h.startswith("earth/") for h in have) else [])
        with tempfile.TemporaryDirectory(prefix="pz-backfill-") as tmp:
            with tarfile.open(fileobj=io.BytesIO(git("archive", sha_, *want))) as t:
                t.extractall(tmp, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
            try:
                man = keep_hour(tmp, record, backfilled=True, commit=sha_[:7])
            except Exception as e:   # an hour the code of today cannot read is said, never guessed
                print(f"{name}: not kept ({type(e).__name__}: {str(e)[:120]})")
                continue
        t = dt.datetime.fromisoformat(man["hour"])
        if site:
            sys.path.insert(0, str(HERE))
            import record_shots
            record_shots.draw(record, pictures_due(record, t), site)
        index(record, today=t.date().isoformat())
        kept.append(man["hour"])
        print(f"backfilled {man['hour']} from {sha_[:7]}: {len(man['files'])} files")
    return kept


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--feed", help="the feed folder just built (or checked out at an hour)")
    ap.add_argument("--backfill", metavar="REPO", help="instead: every hour the feed repository's git history holds (a full clone of its feed branch)")
    ap.add_argument("--record", required=True, help="the record repository's folder")
    ap.add_argument("--shots", metavar="SITE", help="also draw the pictures due, with the site's build in this folder (record_shots.py)")
    ap.add_argument("--backfilled", action="store_true")
    ap.add_argument("--commit")
    a = ap.parse_args()
    if a.backfill:
        hours = backfill(a.backfill, a.record, a.shots)
        print(f"backfilled {len(hours)} hours, {hours[0] if hours else '-'} to {hours[-1] if hours else '-'}")
        return
    man = keep_hour(a.feed, a.record, backfilled=a.backfilled, commit=a.commit)
    keep_history(a.feed, a.record)
    t = dt.datetime.fromisoformat(man["hour"])
    if a.shots:
        sys.path.insert(0, str(HERE))
        import record_shots
        record_shots.draw(a.record, pictures_due(a.record, t), a.shots)
    thin(a.record, t.date().isoformat())
    index(a.record, today=t.date().isoformat())
    print(f"kept {man['hour']}: {len(man['files'])} files, {len(man['left_out'])} left out, High or worse over Southeast Asia {man['high_area_km2']} km²")


if __name__ == "__main__":
    main()
