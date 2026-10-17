"""The smoke field adjusted to the monitors (session 8, part 125; docs/prompts/session-8.md): the hour's model (CAMS) times a factor
that is each nearby monitor's ratio to the model, fading back to the model alone as monitors get fewer and further.

  For each monitor used: r = log((measured + OFFSET) / (model at its place + OFFSET)), the ratio held between RATIO[0] and RATIO[1].
  At each cell: the weighted mean of r over the monitors within RADIUS_KM, weight (1 - d / RADIUS_KM)^3, times the coverage (the sum
  of the weights / 2, at most 1); smoothed over SMOOTH_KM (a Gaussian that wide at half height, down and across); adjusted = model times e to
  that power. A lone monitor so moves its own cell by the square root of its ratio (coverage 1/2); 3 within about 30 km by all of it.

numpy only here; earth.py imports this module inside a try (without numpy the file is left out; the run goes on). Which monitors are
used, and the file around the numbers, are earth.py's (field_monitors, adjusted_file).
"""
import math

import numpy as np

RADIUS_KM = 180
RATIO = (0.25, 6)
OFFSET = 3
SMOOTH_KM = 30
KM_PER_DEG = 111.2
EARTH_KM = 6371.0


def distance_km(lat, lon, lats, lons):
    """Great-circle km from 1 point to a grid of points (lats down, lons across)."""
    p1, p2 = math.radians(lat), np.radians(lats)
    a = np.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * np.cos(p2) * np.sin(np.radians(lons - lon) / 2) ** 2
    return EARTH_KM * 2 * np.arcsin(np.minimum(1.0, np.sqrt(a)))


def shifted_sum(f, weights, axis, wrap):
    """Each cell the weighted mean of its neighbours along 1 axis: `weights` is (2 R + 1,) for every line, or (lines, 2 R + 1) per line;
    across a whole world it wraps, else the weights are those of the cells there are."""
    n = f.shape[axis]
    R = (weights.shape[-1] - 1) // 2
    out = np.zeros_like(f)
    norm = np.zeros_like(f)
    for t, d in enumerate(range(-R, R + 1)):
        w = weights[..., t]
        w = w[:, None] if (w.ndim == 1 and axis == 1) else w
        if wrap:
            src, ok = np.roll(f, -d, axis=axis), 1.0
        else:
            src = np.zeros_like(f)
            okm = np.zeros_like(f)
            a, b = max(0, -d), n - max(0, d)   # cell j takes j + d where it exists
            sl_dst = [slice(None)] * 2
            sl_src = [slice(None)] * 2
            sl_dst[axis], sl_src[axis] = slice(a, b), slice(a + d, b + d)
            src[tuple(sl_dst)] = f[tuple(sl_src)]
            okm[tuple(sl_dst)] = 1.0
            ok = okm
        out += w * src * ok
        norm += w * ok
    return out / np.maximum(norm, 1e-12)


def smooth(f, lats, step, wrap):
    """A Gaussian SMOOTH_KM wide at half its height (spread SMOOTH_KM / 2.355), down and across (across, wider in cells towards the
    poles). On the live feed's 0.4 degree cells (44 km) it only softens; a spread of 30 km would lower a cluster's peak by about 20%."""
    if SMOOTH_KM <= 0:
        return f
    sy = SMOOTH_KM / 2.355 / (step * KM_PER_DEG)
    ry = max(1, math.ceil(2 * sy))
    f = shifted_sum(f, np.exp(-0.5 * (np.arange(-ry, ry + 1) / sy) ** 2), 0, False)
    sx = np.minimum(sy / np.maximum(np.cos(np.radians(lats)), 1e-3), 4.0)
    rx = max(1, math.ceil(2 * float(sx.max())))
    k = np.exp(-0.5 * (np.arange(-rx, rx + 1)[None, :] / sx[:, None]) ** 2)
    return shifted_sum(f, k, 1, wrap)


def field(spec, values, monitors):
    """The model `values` (row by row from lat0 northwards, each from lon0 eastwards; None where it has none) adjusted to `monitors`,
    [(lat, lon, measured, model at its place)]. Returns a list like `values`: floats, None where the model has none."""
    nlat, nlon, step = spec["nlat"], spec["nlon"], spec["step"]
    wrap = abs(nlon * step - 360) < 1e-6
    lats = spec["lat0"] + np.arange(nlat) * step
    lons = spec["lon0"] + np.arange(nlon) * step
    sw = np.zeros((nlat, nlon))
    swr = np.zeros((nlat, nlon))
    lo_r, hi_r = math.log(RATIO[0]), math.log(RATIO[1])
    reach = RADIUS_KM / KM_PER_DEG
    for la, lo, measured, model in monitors:
        r = min(hi_r, max(lo_r, math.log((measured + OFFSET) / (model + OFFSET))))
        i0 = max(0, math.ceil((la - reach - spec["lat0"]) / step))
        i1 = min(nlat - 1, math.floor((la + reach - spec["lat0"]) / step))
        if i0 > i1:
            continue
        ii = np.arange(i0, i1 + 1)
        widest = min(89.0, max(abs(la - reach), abs(la + reach)))
        span = min(180.0, reach / max(math.cos(math.radians(widest)), 1e-3))
        c = ((lo - spec["lon0"]) % 360) / step
        if wrap and 2 * span / step + 3 >= nlon:
            jj = np.arange(nlon)
        elif wrap:
            jj = np.arange(math.floor(c - span / step), math.ceil(c + span / step) + 1) % nlon
        else:
            jj = np.arange(max(0, math.floor(c - span / step)), min(nlon - 1, math.ceil(c + span / step)) + 1)
        if not len(jj):
            continue
        d = distance_km(la, lo, lats[ii][:, None], lons[jj][None, :])
        w = np.where(d < RADIUS_KM, (1 - np.minimum(d, RADIUS_KM) / RADIUS_KM) ** 3, 0.0)
        sw[np.ix_(ii, jj)] += w
        swr[np.ix_(ii, jj)] += w * r
    with np.errstate(invalid="ignore", divide="ignore"):
        f = np.where(sw > 0, swr / np.where(sw > 0, sw, 1) * np.minimum(1.0, sw / 2), 0.0)
    f = smooth(f, lats, step, wrap)
    m = np.array([np.nan if v is None else v for v in values], dtype=np.float64).reshape(nlat, nlon)
    adj = (m * np.exp(f)).ravel()
    return [None if v != v else float(v) for v in adj.tolist()]
