"""Real Earth as 1 finished picture a day (session 7e, parts 114 and 116): `earth/real/<date>-2048.webp` and `-4096.webp`, each with a
JPEG fallback, and `earth/real/<date>.json`, its record. The page showed the planet in 3 stages (Blue Marble, then the day's photo, then
the poles a step later); now it shows this picture, finished, at once. Built from NASA GIBS's pictures (earth.py's credit block):

  - NOAA-20 of the date on top wherever it saw the ground; Suomi NPP and NOAA-21 of the date, then NOAA-20 of the day before, only
    where it saw nothing; Blue Marble last, its near-black ocean recoloured to the satellite's ocean tone (part 80).
  - The joins (part 116): each strip's edge trimmed TRIM_PX at 4,096 wide (from 286 strip edges of NOAA-20 on 12 Oct 2026, the 3
    pixels before GIBS's black are the JPEG's ringing, R + G + B medians 15, 7 and 26, then the strip's dim edge, 34%, 57% and 79% of
    its 374, and 96% at the seventh); each filler matched to the main photo, colour by colour, its mean and spread where both saw, in
    squares of MATCH_DEG degrees, smoothed between squares (a square with nothing shared takes its neighbours', and past about 30
    degrees from anything shared leans back to the filler as it is), the gain clipped to GAIN; each photo laid with a weight rising from
    0 at the edge of what it saw to 1 at BLEND_DEG inside, eased. Never a straight hard edge. Clouds that moved between passes cannot be
    lined up: the join is softened, not hidden.
  - The poles completed in it (part 107, as web/src/earth/base.ts did a step later): over 60 to 90 degrees the photos of 7, 14 and 21
    days before where the day's saw nothing; then each pole's cap as earth.json's `poles` says: the last full-sun photo, its 180 degree
    seam blended and its brightness matched to the photos' ring of 76 to 80 degrees, in full from 82 degrees; or Blue Marble matched
    locally (the ratio of the blurred photos to blurred Blue Marble carried row by row into the gap, clipped 0.6 to 1.4), joined softly.
  - The 180 degree seam feathered (the 2 sides of a day's picture are about 24 hours apart).

When is a new day in? GIBS adds a day's passes for about 3 hours after they are made, so the share of NOAA-20's picture of the date that
saw the ground between 60 S and 60 N (720 by 240 px, JPEG, gaps as below) tells. Measured on live GIBS on 17 Oct 2026, 3:59 am: whole
days 8 to 15 Oct (but 12) saw 99.96% to 100.0%; 16 Oct, still arriving, 65.2%; 12 Oct, when all 3 satellites missed hours of passes,
58.9% for good. So a day is in at READY_SHARE (99.5%); a day that never gets there is built READY_AFTER_H hours after it began (12:00
UTC the next day, 8:00 pm in Malaysia), with what NASA has, the other satellites and the day before filling. Until then the previous
day's picture stays, and 1 small picture an hour asks again.

GIBS's WMS allows 20,000 by 20,000 px (its GetCapabilities: MaxWidth, MaxHeight); 1 whole-world picture at 4,096 by 2,048 took 17.6 s
(2.1 MB JPEG), so each is asked whole, 4 at a time. Built at the largest size; the smaller is the same picture made smaller.

Pillow and numpy only here (pinned in engine/requirements-earth.txt); the rest of the engine is standard library. earth.py imports this
module inside a try: without them the picture is left out and the page builds it from GIBS as before.
"""
import concurrent.futures as cf
import datetime as dt
import io
import json
import os
import time
import urllib.parse

import numpy as np
from PIL import Image

import credits
from transport import FetchError, get_bytes

TZ8 = dt.timezone(dt.timedelta(hours=8))
UTC = dt.timezone.utc
WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
MAIN = "VIIRS_NOAA20_CorrectedReflectance_TrueColor"
FILLS = ("VIIRS_SNPP_CorrectedReflectance_TrueColor", "VIIRS_NOAA21_CorrectedReflectance_TrueColor")
BASE = "BlueMarble_NextGeneration"
SIZES = (2048, 4096)                              # widths; equirectangular, so half as tall
WEBP_BUDGET = {2048: 600_000, 4096: 2_500_000}    # a phone on 4G shows the 2,048 within 3 s
WEBP_QUALITY = (82, 76, 70, 64, 58, 52, 46, 40)   # tried in turn until the picture is within its budget
JPEG_QUALITY = 80                                 # the fallback, for browsers without WebP
KEEP_DAYS = 2
READY_SHARE = 0.995
READY_AFTER_H = 36
GAP = 5                                           # R + G + B under this is a gap: GIBS's "nothing" is pure black (0 to 4 inside
                                                  # 4 million gap pixels of 12 Oct); clear dark ocean is 5 to 17, with blue, in specks
                                                  # (the page's 18 took those for gaps: with a wide blend, Blue Marble showed through)
OCEAN_TONE = (60, 65, 82)                         # the satellite's ocean, about (part 80)
TRIM_PX = 6                                       # at 4,096 wide; 3 at 2,048
MATCH_DEG = 10
BLEND_DEG = 1.5
GAIN = (0.67, 1.5)
POLE_BACK = (7, 14, 21)
WORKERS = 4


def stamp(t):
    return t.astimezone(TZ8).strftime("%Y-%m-%dT%H:%M+08:00")


def days_before(date, k):
    return (dt.date.fromisoformat(date) - dt.timedelta(days=k)).isoformat()


# ---------------------------------------------------------------- GIBS
def wms_url(layer, date, w, h, box=(-180, -90, 180, 90)):
    """1 GIBS picture, EPSG:4326 (WMS 1.3.0 names the box south, west, north, east), as JPEG."""
    west, south, east, north = box
    q = {"SERVICE": "WMS", "REQUEST": "GetMap", "VERSION": "1.3.0", "LAYERS": layer, "CRS": "EPSG:4326",
         "BBOX": f"{south},{west},{north},{east}", "WIDTH": w, "HEIGHT": h, "FORMAT": "image/jpeg"}
    if date:
        q["TIME"] = date
    return WMS + "?" + urllib.parse.urlencode(q)


def fetch(layer, date, w, h, box=(-180, -90, 180, 90)):
    """The picture as an array of h rows, w columns, RGB."""
    blob = get_bytes(wms_url(layer, date, w, h, box), timeout=300, tries=2)
    try:
        im = Image.open(io.BytesIO(blob))
        im.load()
    except Exception:
        raise FetchError(f"GIBS sent no picture for {layer} of {date}")
    if im.size != (w, h):
        im = im.resize((w, h), Image.LANCZOS)
    return np.asarray(im.convert("RGB"))


def seen_share(date):
    """The share of NOAA-20's picture of the date that saw the ground between 60 S and 60 N."""
    px = fetch(MAIN, date, 720, 240, (-180, -60, 180, 60))
    return float(saw(px).mean())


def ready(date, now):
    """(is the day in, why)."""
    share = seen_share(date)
    if share >= READY_SHARE:
        return True, f"NOAA-20 of {date} saw {share:.1%} between 60 S and 60 N"
    began = dt.datetime.combine(dt.date.fromisoformat(date), dt.time(0), UTC)
    if now >= began + dt.timedelta(hours=READY_AFTER_H):
        return True, f"NOAA-20 of {date} saw {share:.1%} between 60 S and 60 N, {READY_AFTER_H} hours after the day began: built with what there is"
    return False, f"NOAA-20 of {date} saw {share:.1%} between 60 S and 60 N so far (a whole day sees 99.96% to 100%); the picture of the day before stays"


def fetch_inputs(date, caps, W):
    """Every picture the day's picture is made of, at W wide, asked WORKERS at a time; a picture that does not come is left out (its
    gaps fall to the next), except NOAA-20 of the date and Blue Marble, without which nothing is built this hour."""
    H = W // 2
    rows = round(H / 6)
    span = rows * 180 / H
    boxes = {"north": (-180, 90 - span, 180, 90), "south": (-180, -90, 180, -90 + span)}
    world = [(MAIN, date, "main"), (FILLS[0], date, "fill"), (FILLS[1], date, "fill"), (MAIN, days_before(date, 1), "fill"), (BASE, None, "base")]
    asks = {("world", i): (layer, d, W, H, (-180, -90, 180, 90)) for i, (layer, d, _) in enumerate(world)}
    for pole, box in boxes.items():
        for k in POLE_BACK:
            asks[("pole", pole, k)] = (MAIN, days_before(date, k), W, rows, box)
        cap = (caps or {}).get(pole) or {}
        if cap.get("kind") == "photo" and cap.get("date"):
            asks[("cap", pole)] = (MAIN, cap["date"], W, rows, box)
    t0 = time.monotonic()
    got = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(fetch, *a): key for key, a in asks.items()}
        for fut in cf.as_completed(futs):
            try:
                got[futs[fut]] = fut.result()
            except FetchError:
                got[futs[fut]] = None
    if got[("world", 0)] is None or got[("world", 4)] is None:
        raise FetchError(f"NOAA-20 of {date} or Blue Marble did not come from GIBS")
    made_from = [{"layer": layer, "date": d, "role": role} for i, (layer, d, role) in enumerate(world) if got[("world", i)] is not None]
    made_from += [{"layer": MAIN, "date": days_before(date, k), "role": "pole"} for k in POLE_BACK
                  if any(got.get(("pole", p, k)) is not None for p in boxes)]
    capped = {p: got.get(("cap", p)) for p in boxes}
    made_from += [{"layer": MAIN, "date": caps[p]["date"], "role": "cap", "where": p} if capped[p] is not None else
                  {"layer": BASE, "date": None, "role": "cap", "where": p} for p in boxes]
    return {"date": date, "main": got[("world", 0)], "fills": [got[("world", i)] for i in (1, 2, 3) if got[("world", i)] is not None],
            "base": got[("world", 4)], "older": {p: [got[("pole", p, k)] for k in POLE_BACK if got.get(("pole", p, k)) is not None] for p in boxes},
            "caps": capped, "made_from": made_from, "took_s": round(time.monotonic() - t0, 1)}


# ---------------------------------------------------------------- the picture, with numpy
def ease(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def saw(px):
    """Where a picture saw something: not GIBS's pure black; a black speck under 3 px across is not a gap."""
    gap = (px[..., 0].astype(np.uint16) + px[..., 1] + px[..., 2]) < GAP
    return erode(~erode(gap, 1), 1)   # the gaps opened: shrunk 1 px, then grown back, so specks go


def erode(m, r):
    """A mask shrunk by r pixels each way (across, the world wraps at 180 degrees; down, the picture's edge is no edge)."""
    m = m.copy()
    for _ in range(r):
        h = m & np.roll(m, 1, 1) & np.roll(m, -1, 1)
        v = h.copy()
        v[1:] &= h[:-1]
        v[:-1] &= h[1:]
        m = v
    return m


def ramp(m, px):
    """The weight a picture is laid with: 0 at the edge of what it saw, rising to 1 at `px` pixels inside it, eased."""
    d = np.zeros(m.shape, np.float32)
    for _ in range(px):
        if not m.any():
            break
        d += m
        m = erode(m, 1)
    return ease(d / px)


def box(a, r, axis):
    """A moving average over 2 r + 1 pixels along 1 axis, over the pixels there are at the picture's edge (the page's boxPass)."""
    a = np.moveaxis(np.asarray(a, np.float64), axis, -1)
    n = a.shape[-1]
    c = np.concatenate([np.zeros(a.shape[:-1] + (1,)), np.cumsum(a, -1)], -1)
    i = np.arange(n)
    lo, hi = np.clip(i - r, 0, n), np.clip(i + r + 1, 0, n)
    return np.moveaxis(((c[..., hi] - c[..., lo]) / (hi - lo)).astype(np.float32), -1, axis)


def blurred(f, r):
    """2 box passes each way: close to a Gaussian (the page's `blurred`)."""
    for _ in range(2):
        f = box(box(f, r, 1), r, 0)
    return f


def seen_weight(px, er, bl):
    """The page's seenWeight: what a picture saw, eroded `er` px, blurred `bl` px, 0 in its gaps."""
    s = saw(px)
    return blurred(erode(s, er).astype(np.float32), bl) * s


def recolour(px):
    """Blue Marble's near-black ocean (about RGB 2, 5, 20) recoloured to the satellite's ocean tone, its texture kept (part 80)."""
    p = px.astype(np.float32)
    o = np.clip((90 - p.sum(2)) / 50, 0, 1) * ((p[..., 2] >= p[..., 0]) & (p[..., 2] >= p[..., 1]))
    for c, (tone, deep) in enumerate(zip(OCEAN_TONE, (2, 5, 20))):
        p[..., c] = p[..., c] * (1 - o) + (tone + (p[..., c] - deep) * 0.6) * o
    return p


def feather_dateline(px, r):
    """The 2 edges of a whole-world picture blended into each other over r px, half and half at the seam (in place)."""
    a = (0.5 * (1 - np.arange(r) / r))[None, :, None]
    left, right = px[:, :r].astype(np.float32), px[:, ::-1][:, :r].astype(np.float32)
    px[:, :r] = left * (1 - a) + right * a
    px[:, -r:] = (right * (1 - a) + left * a)[:, ::-1]


def squares(W, H, deg):
    nx, ny = max(1, round(360 / deg)), max(1, round(180 / deg))
    return np.linspace(0, W, nx + 1).round().astype(int), np.linspace(0, H, ny + 1).round().astype(int)


def fill_in(f, same=None, keep=0.5, full=3):
    """Squares with no value take the mean of their neighbours', again until every square has one (across, the world wraps). With
    `same` (the value that changes nothing), after the first `full` rings (about 30 degrees, well past any join) each further ring keeps only
    `keep` of the change: deep in a wide gap (12 Oct 2026: all 3 satellites missed 90 degrees of the eastern Pacific) the filler is laid
    as it is, not matched to squares far away."""
    f = f.copy()
    ring = 0
    while np.isnan(f[..., 0]).any():
        ring += 1
        bad = np.isnan(f[..., 0])
        ny, nx = bad.shape
        p = np.concatenate([f[:, -1:], f, f[:, :1]], 1)
        nan = np.full_like(p[:1], np.nan)
        p = np.concatenate([nan, p, nan], 0)
        st = np.stack([p[1 + dy:1 + dy + ny, 1 + dx:1 + dx + nx] for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx])
        ok = ~np.isnan(st)
        cnt = ok.sum(0)
        mean = np.where(ok, st, 0).sum(0) / np.maximum(cnt, 1)
        if same is not None and ring > full:
            mean = same + (mean - same) * keep
        f[bad] = np.where(cnt[bad] > 0, mean[bad], np.nan)
    return f


def smooth(f):
    """Each square the mean of itself and its 8 neighbours (across, the world wraps; at the poles, the edge row repeats)."""
    ny, nx = f.shape[:2]
    p = np.concatenate([f[:, -1:], f, f[:, :1]], 1)
    p = np.concatenate([p[:1], p, p[-1:]], 0)
    return sum(p[1 + dy:1 + dy + ny, 1 + dx:1 + dx + nx] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) / 9


def upsample(f, xs, ys):
    """A value per square to a value per pixel, linear between the squares' centres (across, the world wraps)."""
    W, H = xs[-1], ys[-1]
    cx, cy = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2
    ext = np.concatenate([f[:, -1:], f, f[:, :1]], 1)
    cxe = np.concatenate([[cx[-1] - W], cx, [cx[0] + W]])
    px = np.arange(W) + 0.5
    i = np.clip(np.searchsorted(cxe, px) - 1, 0, len(cxe) - 2)
    t = ((px - cxe[i]) / (cxe[i + 1] - cxe[i]))[None, :, None]
    across = ext[:, i] * (1 - t) + ext[:, i + 1] * t
    if len(cy) == 1:
        return np.repeat(across, H, 0).astype(np.float32)
    py = np.arange(H) + 0.5
    j = np.clip(np.searchsorted(cy, py) - 1, 0, len(cy) - 2)
    s = np.clip((py - cy[j]) / (cy[j + 1] - cy[j]), 0, 1)[:, None, None]
    return (across[j] * (1 - s) + across[j + 1] * s).astype(np.float32)


def matched(img, seen_img, ref, seen_ref, deg=MATCH_DEG):
    """`img` with each colour's mean and spread matched to `ref`'s where both saw, square by square, smoothed between squares."""
    H, W = img.shape[:2]
    xs, ys = squares(W, H, deg)
    both = (seen_img & seen_ref).astype(np.float64)

    def sums(a):
        return np.add.reduceat(np.add.reduceat(a, ys[:-1], 0), xs[:-1], 1)
    n = sums(both)
    ok = n >= np.maximum(25, 0.02 * np.outer(np.diff(ys), np.diff(xs)))
    if not ok.any():
        return img.astype(np.float32)   # nothing shared anywhere: as it is
    gain = np.full(n.shape + (3,), np.nan)
    off = np.full(n.shape + (3,), np.nan)
    for c in range(3):
        a, b = img[..., c].astype(np.float64), ref[..., c].astype(np.float64)
        nn = np.maximum(n, 1)
        ma, mb = sums(a * both) / nn, sums(b * both) / nn
        sa = np.sqrt(np.maximum(sums(a * a * both) / nn - ma * ma, 0))
        sb = np.sqrt(np.maximum(sums(b * b * both) / nn - mb * mb, 0))
        g = np.clip((sb + 2) / (sa + 2), *GAIN)
        gain[..., c] = np.where(ok, g, np.nan)
        off[..., c] = np.where(ok, mb - g * ma, np.nan)
    G = upsample(smooth(fill_in(gain, 1.0)), xs, ys)
    O = upsample(smooth(fill_in(off, 0.0)), xs, ys)
    return img.astype(np.float32) * G + O


def scaled(px, W):
    """A length in pixels at 4,096 wide, at W wide."""
    return max(1, round(px * W / 4096))


def composite(main, fills, base, match=True):
    """The day's photos over Blue Marble (recoloured): `main` on top, each of `fills` in turn only where those above saw nothing, each
    trimmed, matched to `main` (unless match is False) and laid with its weight. Returns (picture, the photos' premultiplied colour,
    their weight), all float32, for the poles to carry on from."""
    H, W = main.shape[:2]
    trim, blend = scaled(TRIM_PX, W), max(2, round(BLEND_DEG * W / 360))
    s_main = erode(saw(main), trim)
    layers = [(main.astype(np.float32), s_main)]
    for f in fills:
        s = erode(saw(f), trim)
        layers.append((matched(f, s, main, s_main) if match else f.astype(np.float32), s))
    acc = np.zeros((H, W, 3), np.float32)
    A = np.zeros((H, W), np.float32)
    for img, s in layers:
        a = ramp(s, blend) * (1 - A)
        acc += a[..., None] * img
        A += a
    return acc + (1 - A)[..., None] * recolour(base), acc, A


def complete_poles(res, acc, A, bm, older, caps):
    """Part 107 in the picture (in place): over 60 to 90 degrees the older photos where the day's saw nothing, then each pole's cap;
    joined to the rest of the picture over the box's first 2 degrees."""
    H, W = res.shape[:2]
    rows = round(H / 6)
    span = rows * 180 / H
    k = W / 2048   # the page's lengths were at 2,048 wide
    trim, blend = scaled(TRIM_PX, W), max(2, round(BLEND_DEG * W / 360))
    for pole in ("north", "south"):
        sl = slice(0, rows) if pole == "north" else slice(H - rows, H)
        centre = (np.arange(rows) + 0.5) * span / rows
        alat = 90 - centre if pole == "north" else 90 - span + centre
        pa, S = acc[sl].copy(), A[sl].copy()
        for img in older.get(pole, []):   # newest first, each only where those above saw nothing
            a = ramp(erode(saw(img), trim), blend) * (1 - S)
            pa += a[..., None] * img
            S += a
        ph = pa / np.maximum(S, 1e-6)[..., None]
        b = bm[sl]
        cap = caps.get(pole)
        if cap is not None:
            # the cap: 1 photo, its 180 degree seam blended, its brightness matched to the photos' ring of 76 to 80 degrees
            capf = cap.astype(np.float32)
            feather_dateline(capf, max(8, round(W / 85)))
            # its own small holes filled from around them, so Blue Marble's dark Arctic sea does not show through: GIBS leaves a line
            # of nothing at 0 degrees from the pole to about 85.6 N (1 px at 4,096 wide, R + G + B 13 to 300 on ice of about 690, its
            # neighbours dimmed by the JPEG), so a straight run down the picture of pixels under 85% of the ice 4 px either side, and
            # the pixel either side of it, count as holes too
            lum = cap.astype(np.float32).sum(2)
            beside = np.minimum(np.roll(lum, 4, 1), np.roll(lum, -4, 1))
            line = box(((lum < 0.85 * beside) & (beside > 300)).astype(np.float32), 3, 0) >= 0.7
            line |= np.roll(line, 1, 1) | np.roll(line, -1, 1)
            s = saw(cap) & ~line
            r1 = max(2, round(W / 400))
            den = blurred(s.astype(np.float32), r1)
            holes = ~s & (den > 0.02)
            for c in range(3):
                capf[..., c][holes] = (blurred(capf[..., c] * s, r1)[holes] / den[holes])
            Sc = seen_weight(np.clip(capf, 0, 255).astype(np.uint8), round(2 * k), round(2 * k))
            ring = ((alat >= 76) & (alat <= 80))[:, None] & (S > 0.9) & (Sc > 0.9)
            lum = lambda p: p[..., 0] * 0.3 + p[..., 1] * 0.59 + p[..., 2] * 0.11   # noqa: E731
            sp, sc = float(lum(ph)[ring].sum()), float(lum(capf)[ring].sum())
            f = min(1.4, max(0.7, sp / sc)) if sc > 0 else 1.0
            fill = b + (capf * f - b) * Sc[..., None]
            wc = ease((alat - 76) / 6)
        else:
            # Blue Marble matched locally: the ratio of the photos' blurred colour to Blue Marble's, carried into the gap row by row from
            # the photos towards the pole, smoothed along each row, clipped to 0.6 to 1.4
            r0 = max(4, round(W / 100))
            bS = blurred(S, r0)
            ratio = np.empty(ph.shape, np.float32)
            for c in range(3):
                bn, bd = blurred(ph[..., c] * S, r0), blurred(b[..., c] * S, r0)
                ratio[..., c] = np.where((bS > 0.15) & (bd > 1), bn / np.maximum(bd, 1e-6), np.nan)
            prev = None
            for r in (range(rows) if pole == "south" else range(rows - 1, -1, -1)):
                gap = np.isnan(ratio[r])
                ratio[r][gap] = 1.0 if prev is None else prev[gap]
                prev = ratio[r]
            for c in range(3):
                ratio[..., c] = box(box(ratio[..., c], r0, 1), r0, 1)
            fill = b * np.clip(ratio, 0.6, 1.4)
            wc = np.zeros(rows)
        # joined softly where the photos stop; for a photo cap, by latitude: the cap in full from 82 degrees, the photos up to 76
        soft = blurred(S, max(3, round(W / 230)))
        wp = np.minimum(S, ease(soft)) * (1 - wc)[:, None]
        out = fill + (ph - fill) * wp[..., None]
        j = ease((alat - (90 - span)) / 2)[:, None, None]
        res[sl] = res[sl] * (1 - j) + out * j
    return res


def make(inputs, W, poles=True):
    """The finished picture, W by W / 2, as RGB bytes."""
    res, acc, A = composite(inputs["main"], inputs["fills"], inputs["base"])
    if poles:
        complete_poles(res, acc, A, recolour(inputs["base"]), inputs["older"], inputs["caps"])
    feather_dateline(res, max(8, round(W / 85)))
    return np.clip(res + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- the files
def encode(img, fmt, quality):
    im = img if isinstance(img, Image.Image) else Image.fromarray(img)
    buf = io.BytesIO()
    if fmt == "WEBP":
        im.save(buf, "WEBP", quality=quality, method=6)
    else:
        im.save(buf, "JPEG", quality=quality, optimize=True, progressive=True)
    return buf.getvalue()


def fit(img, budget):
    """(WebP bytes, quality, over budget): the first of WEBP_QUALITY within the budget, else the lowest, said."""
    for q in WEBP_QUALITY:
        blob = encode(img, "WEBP", q)
        if budget is None or len(blob) <= budget:
            return blob, q, False
    return blob, q, True


def put(path, blob):
    with open(path + ".tmp", "wb") as f:
        f.write(blob)
    os.replace(path + ".tmp", path)


def build(rdir, date, now, caps):
    """The pictures of the date at every size and their record. Returns the record (earth.json's day_picture)."""
    W = max(SIZES)
    inputs = fetch_inputs(date, caps, W)
    t0 = time.monotonic()
    full = Image.fromarray(make(inputs, W))
    t1 = time.monotonic()
    sizes, quality, over = [], {}, []
    for w in sorted(SIZES):
        im = full if w == W else full.resize((w, w // 2), Image.LANCZOS)
        webp, q, too_big = fit(im, WEBP_BUDGET.get(w))
        jpg = encode(im, "JPEG", JPEG_QUALITY)
        name = f"{date}-{w}"
        put(os.path.join(rdir, f"{name}.webp"), webp)
        put(os.path.join(rdir, f"{name}.jpg"), jpg)
        sizes.append({"width": w, "height": w // 2, "webp": f"earth/real/{name}.webp", "jpg": f"earth/real/{name}.jpg",
                      "bytes": {"webp": len(webp), "jpg": len(jpg)}})
        quality[str(w)] = q
        if too_big:
            over.append(f"{w} px: {len(webp):,} bytes at quality {q}, over {WEBP_BUDGET[w]:,}")
    rec = {"date": date, "made_at": stamp(now), "projection": "equirectangular", "sizes": sizes, "made_from": inputs["made_from"],
           "poles": "completed", "joins": {"trim_px": TRIM_PX, "match_deg": MATCH_DEG, "blend_deg": BLEND_DEG}}
    side = {"schema_version": "1", "source": "GIBS", "day_picture": rec, "webp_quality": quality, "over_budget": over,
            "took_s": {"download": inputs["took_s"], "build": round(t1 - t0, 1), "encode": round(time.monotonic() - t1, 1)},
            "credits": credits.block(["GIBS"], now)}
    put(os.path.join(rdir, f"{date}.json"), json.dumps(side, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))   # last: a record means done
    return rec


def records(rdir):
    """{date: its record} for every day whose record and pictures are all there."""
    out = {}
    for f in os.listdir(rdir):
        if len(f) == 15 and f.endswith(".json"):
            try:
                with open(os.path.join(rdir, f), encoding="utf-8") as fh:
                    rec = json.load(fh).get("day_picture")
            except (OSError, ValueError):
                continue
            if rec and all(os.path.exists(os.path.join(rdir, os.path.basename(s[x]))) for s in rec.get("sizes", []) for x in ("webp", "jpg")):
                out[rec["date"]] = rec
    return out


def prune(rdir, have):
    """The last KEEP_DAYS days kept; every other file in earth/real deleted (an unfinished day's too)."""
    keep = set(sorted(have)[-KEEP_DAYS:])
    for f in os.listdir(rdir):
        if f[:10] not in keep:
            os.remove(os.path.join(rdir, f))
    for d in list(have):
        if d not in keep:
            del have[d]


def step(folder, now, caps=None):
    """The day's picture for earth.json's real_earth layer: (day_picture, what happened). The date is yesterday in Malaysia, as the layer
    names it. Asks GIBS nothing once that day's picture is built; until then 1 small picture an hour, and the previous day's stays."""
    rdir = os.path.join(folder, "real")
    os.makedirs(rdir, exist_ok=True)
    want = (now.astimezone(TZ8) - dt.timedelta(days=1)).date().isoformat()
    have = records(rdir)
    note = f"the picture of {want} is built"
    if want not in have:
        try:
            ok, note = ready(want, now)
            if not ok and not any(d < want for d in have):   # nothing to keep meanwhile (the first run): the day before, which is in
                before = days_before(want, 1)
                ok, why = ready(before, now)
                want, note = (before, why) if ok else (want, note)
            if ok:
                have[want] = build(rdir, want, now, caps)
                note = f"built the picture of {want}: {note}"
        except FetchError as e:
            note = f"GIBS did not answer ({str(e)[:160]}); asked again next hour"
    prune(rdir, have)
    served = [d for d in have if d <= want]
    return (have[max(served)], note) if served else (None, note)
