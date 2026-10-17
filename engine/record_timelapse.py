"""The kept time-lapse (session 8e, part 143j; Amendment 3; part 153): 1 frame a day, each day's worst hour over Southeast Asia, in 2
looks, Real Earth and Plain (the globe), each as an MP4 and a GIF, kept in the record at timelapse/. Each frame is the day's kept picture
of the globe (part 153: the map alone on its paper with its strip of key and times, never the site's page), the date, the hour and the
view stamped in an ink block in its corner; the credit line is the last frame. Frames of different heights (a strip of 3 lines against 4)
are padded with white to the tallest. Made by the feed's Action once a day, when a day has ended and its 4 views are drawn (record.py
calls make() every hour; it does nothing until the days change). ffmpeg makes the MP4 (the system's, else the one imageio-ffmpeg brings);
Pillow makes the GIF.

Where it is kept: its manifest (timelapse.json) on the record's main branch; the 4 files, rewritten whole each day, on the record's own
branch `timelapse`, replaced each day by 1 commit (the Action force-pushes it when timelapse/.made is there), so the old copies do not
pile up in the record's history (about 0.35 MB more a day: 27 MB of files by 31 Dec, which kept in history would have been about 1 GB).
They are downloaded from raw.githubusercontent.com (TIMELAPSE_BASE).
"""
import datetime as dt
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

LOOKS = {"real": ("globe-real", "Real Earth"), "plain": ("globe-plain", "Plain")}
DAY_S, CREDIT_S = 1, 4             # each day 1 second; the credit 4
GIF_W, GIF_COLOURS = 360, 128   # about 90 KB a day (480 px and 256 colours: 190 KB), small enough to share in a chat
TIMELAPSE_BASE = "https://raw.githubusercontent.com/yheushen/planetzero-record/timelapse/"
INK, WHITE, GREY = (21, 32, 43), (255, 255, 255), (88, 98, 110)
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def clock(name):
    """'2026-10-16T15' as '3:00 pm'."""
    h = int(name[11:13])
    return f"{(h % 12) or 12}:00 {'am' if h < 12 else 'pm'}"


def day_words(date):
    return f"{int(date[8:10])} {MONTHS[int(date[5:7]) - 1]} {date[:4]}"


def frames_due(record):
    """Every day that has ended, in order, with its worst hour and that hour's 2 globe pictures; a day without them is listed as missing."""
    record = Path(record)
    out, missing = [], []
    for f in sorted((record / "days").glob("*.json")):
        d = read(f)
        w = d.get("worst")
        if not d.get("worst_final") or not w:
            continue
        pics = {look: f"hours/{w}/{view}.webp" for look, (view, _) in LOOKS.items()}
        if all((record / p).exists() for p in pics.values()):
            out.append({"date": d["date"], "hour": w, "pictures": pics})
        else:
            missing.append(d["date"])
    return out, missing


def fonts(site=None):
    """The site's own Public Sans (its build holds it as WOFF, which Pillow reads), else Pillow's own font."""
    from PIL import ImageFont
    found = {}
    for weight in ("400", "700"):
        hits = sorted(Path(site).glob(f"assets/public-sans-latin-{weight}-normal*.woff")) if site else []
        if not hits:
            hits = sorted(Path(__file__).resolve().parents[1].glob(f"web/node_modules/@fontsource/public-sans/files/public-sans-latin-{weight}-normal.woff"))
        found[weight] = (lambda size, p=hits[0]: ImageFont.truetype(str(p), size)) if hits else (lambda size: ImageFont.load_default(size))
    return found


def stamp_words(f, look):
    return day_words(f["date"]) + ", " + clock(f["hour"]), "Globe, " + LOOKS[look][1] + ". The day's worst hour over Southeast Asia"


def frame(record, f, look, font):
    """1 day: the kept picture of the globe as it is (the map alone and its strip), the date, hour and view in an ink block in its top
    left corner."""
    from PIL import Image, ImageDraw
    im = Image.open(Path(record) / f["pictures"][look]).convert("RGB")
    top, sub = stamp_words(f, look)
    d = ImageDraw.Draw(im)
    big, small = font["700"](26), font["400"](15)
    w = max(d.textlength(top, font=big), d.textlength(sub, font=small)) + 28
    d.rectangle((0, 0, w, 66), fill=INK)
    d.text((14, 9), top, font=big, fill=WHITE)
    d.text((14, 42), sub, font=small, fill=WHITE)
    return im


def wrap(d, text, font, width):
    lines, line = [], ""
    for word in text.split():
        t = (line + " " + word).strip()
        if d.textlength(t, font=font) > width and line:
            lines.append(line)
            line = word
        else:
            line = t
    return lines + ([line] if line else [])


def credit_frame(size, credit, first, last, look, font):
    """The last frame: what the time-lapse is, its days, and the credit line in full."""
    from PIL import Image, ImageDraw
    im = Image.new("RGB", size, WHITE)
    d = ImageDraw.Draw(im)
    x, y, width = 32, 36, size[0] - 64
    d.text((x, y), "The 2026 haze, day by day", font=font["700"](30), fill=INK)
    y += 48
    span = day_words(first) if first == last else f"{day_words(first)} to {day_words(last)}"
    for line in wrap(d, f"Globe, {LOOKS[look][1]}. 1 frame a day, each day's worst hour over Southeast Asia, {span}. The smoke is an estimate "
                        "from a computer model, adjusted to the monitors. Kept by Planet Zero, planetzero.ai.", font["400"](17), width):
        d.text((x, y), line, font=font["400"](17), fill=INK)
        y += 25
    y += 16
    for line in wrap(d, credit, font["400"](14), width):
        d.text((x, y), line, font=font["400"](14), fill=GREY)
        y += 20
    return im


def ffmpeg_exe():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def mp4(images, out):
    """1 second a day, the credit 4 (the frame repeated), 25 frames a second for players that dislike slow ones; H.264, yuv420p."""
    with tempfile.TemporaryDirectory() as tmp:
        k = 0
        for i, im in enumerate(images):
            for _ in range(CREDIT_S if i == len(images) - 1 else DAY_S):
                k += 1
                im.save(Path(tmp) / f"f{k:05d}.png")
        subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error", "-framerate", "1", "-i", str(Path(tmp) / "f%05d.png"), "-vf", "fps=25,format=yuv420p",
                        "-c:v", "libx264", "-crf", "23", "-movflags", "+faststart", str(out)], check=True)


def same_size(images):
    """Every frame the size of the largest, padded with white at the right and the foot; even sides (the MP4's colour format needs them)."""
    from PIL import Image
    w = max(im.size[0] for im in images)
    h = max(im.size[1] for im in images)
    w, h = w + w % 2, h + h % 2
    out = []
    for im in images:
        if im.size == (w, h):
            out.append(im)
            continue
        pad = Image.new("RGB", (w, h), WHITE)
        pad.paste(im, (0, 0))
        out.append(pad)
    return out


def gif(images, out):
    from PIL import Image
    small = [im.resize((GIF_W, round(im.size[1] * GIF_W / im.size[0])), Image.LANCZOS).quantize(colors=GIF_COLOURS, method=Image.Quantize.MEDIANCUT) for im in images]
    small[0].save(out, save_all=True, append_images=small[1:], duration=[DAY_S * 1000] * (len(small) - 1) + [CREDIT_S * 1000], loop=0, optimize=True)


def make(record, site=None, force=False, now=None):
    """timelapse/{real,plain}.{mp4,gif} and timelapse/timelapse.json, when the days that have ended changed (or force). Returns the
    manifest, or None when there was nothing new."""
    record = Path(record)
    frames, missing = frames_due(record)
    out = record / "timelapse"
    man_path = out / "timelapse.json"
    old = read(man_path) if man_path.exists() else None
    if not frames or (not force and old and old.get("frames") == frames):
        return None
    out.mkdir(parents=True, exist_ok=True)
    font = fonts(site)
    credit = read(record / "index.json").get("credit", "") if (record / "index.json").exists() else ""
    files = {}
    for look in LOOKS:
        images = same_size([frame(record, f, look, font) for f in frames])
        images.append(credit_frame(images[0].size, credit, frames[0]["date"], frames[-1]["date"], look, font))
        mp4(images, out / f"{look}.mp4")
        gif(images, out / f"{look}.gif")
        files[look] = {kind: {"path": f"timelapse/{look}.{kind}", "bytes": (out / f"{look}.{kind}").stat().st_size} for kind in ("mp4", "gif")}
    man = {"schema_version": "1", "made_at": (now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))).isoformat(timespec="minutes"),
           "what": "1 frame a day, each day's worst hour over Southeast Asia, the globe in Real Earth and in Plain, the date, hour and view "
                   "stamped in the corner, each frame the map alone with its strip; the credit line the last frame.",
           "seconds_a_day": DAY_S, "credit_seconds": CREDIT_S, "frames": frames, "missing": missing, "files": files, "credit": credit}
    man_path.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (out / ".made").write_text(man["made_at"] + "\n", encoding="utf-8")   # for the Action: push the files to their own branch this run
    return man


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--record", required=True)
    ap.add_argument("--site", help="the site's build, for its font")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    m = make(a.record, a.site, a.force)
    print("nothing new" if m is None else f"time-lapse of {len(m['frames'])} days: " + ", ".join(f"{k}.{x} {v[x]['bytes'] // 1024} KB" for k, v in m["files"].items() for x in v))
