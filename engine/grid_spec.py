"""The globe's grid: which points, in which order, fetched in which calls.

Open-Meteo counts each location in a call as 1 call (free limit: 600 a minute, 10,000 a day), so the grid is
fetched once a day and sliced to the hour on every run (docs/SPEC.md section 5).
  smoke  CAMS PM2.5, 1 degree, 84 to 130 E and 15 S to 16 N (the box of ../_build/globe_grid_fetch.py)
  wind   10 m wind, the same 1 degree box
  hemi   10 m wind, 5 degrees, over the hemisphere the globe shows (20 to 190 E, 70 S to 70 N)
"""
AQ = "https://air-quality-api.open-meteo.com/v1/air-quality"
WX = "https://api.open-meteo.com/v1/forecast"
CHUNK = 100

BOX = {"lat0": -15, "lon0": 84, "step": 1, "nlat": 32, "nlon": 47}
HEMI = {"lat0": -70, "lon0": 20, "step": 5, "nlat": 29, "nlon": 35}


def points(g):
    """Grid points in row order (south to north, then west to east); longitudes past 180 wrap to negative."""
    out = []
    for i in range(g["nlat"]):
        for j in range(g["nlon"]):
            lon = g["lon0"] + j * g["step"]
            out.append((g["lat0"] + i * g["step"], lon - 360 if lon > 180 else lon))
    return out


def chunks(pts):
    return [pts[i:i + CHUNK] for i in range(0, len(pts), CHUNK)]


def requests():
    """(kind, url, points, hourly variables) for every call of 1 daily fetch."""
    out = []
    for c in chunks(points(BOX)):
        out.append(("smoke", AQ, c, "pm2_5"))
    for c in chunks(points(BOX)):
        out.append(("wind", WX, c, "wind_speed_10m,wind_direction_10m"))
    for c in chunks(points(HEMI)):
        out.append(("hemi", WX, c, "wind_speed_10m,wind_direction_10m"))
    return out
