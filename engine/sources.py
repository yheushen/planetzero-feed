"""Which sources may enter the public feed (invariant 6) and how each is credited.

The allow list mirrors the "In the public feed" column of docs/DATA-TERMS.md: only rows that say "Show".
evals/feed (F2) parses that file and fails if this list ever names a source the file does not mark "Show".
Google, IQAir and aqicn's archive stay in the private logger; they never reach this engine. aqicn's current value may be shown
with credit (the owner confirmed its terms, 15 Oct 2026), but never kept: NO_HISTORY.
"""
ALLOW = ("NEA", "DOE", "OpenAQ", "CAMS", "Open-Meteo", "FIRMS", "aqicn",
         # Earth (session 7, part 68; docs/TERMS-CHECK-EARTH-2026-10-16.md)
         "GIBS", "GFS", "CelesTrak", "CAMS-ADS", "NaturalEarth")
# shown now, never archived: history.merge refuses these (docs/DATA-TERMS.md: no redistribution of aqicn's archive)
NO_HISTORY = ("aqicn",)

# the row of docs/DATA-TERMS.md each source falls under
TERMS_ROW = {
    "NEA": "NEA via data.gov.sg",
    "DOE": "DOE Malaysia (APIMS / MyEQMS)",
    "OpenAQ": "OpenAQ (AirGradient, Sensor.Community)",
    "CAMS": "CAMS via Open-Meteo",
    "Open-Meteo": "CAMS via Open-Meteo",
    "FIRMS": "NASA FIRMS",
    "aqicn": "aqicn / WAQI",
    "GIBS": "NASA GIBS (Earth's pictures)",
    "GFS": "NOAA GFS via NOMADS",
    "CelesTrak": "CelesTrak",
    "CAMS-ADS": "CAMS global via the Atmosphere Data Store",
    "NaturalEarth": "Natural Earth",
}
# Earth's worldwide monitors come from OpenAQ under its own row (the 16 Oct check); the row Earth's OpenAQ layer answers to
EARTH_OPENAQ_ROW = "OpenAQ, worldwide"

CREDIT = {
    "NEA": "NEA via data.gov.sg",
    "DOE": "DOE Malaysia (APIMS)",
    "CAMS": "Copernicus CAMS via Open-Meteo",
    "Open-Meteo": "Open-Meteo weather models",
    "FIRMS": "NASA FIRMS (VIIRS, Suomi NPP and NOAA-20)",
    "aqicn": "aqicn.org (World Air Quality Index project)",
    "GIBS": "NASA GIBS",
    "GFS": "NOAA GFS via NOMADS",
    "CelesTrak": "CelesTrak",
    "CAMS-ADS": "Copernicus CAMS global (Atmosphere Data Store)",
    "NaturalEarth": "Natural Earth",
}


def aqicn_credit(agency):
    return f"aqicn.org (World Air Quality Index project), relaying {'NEA' if agency == 'NEA' else 'DOE Malaysia'}. Data not verified by aqicn."


# community sensors whose readings may be kept in the public history: an open licence (docs/TERMS-CHECK-2026-10-15.md)
OPEN_LICENCES = ("CC BY 4.0", "CC0 1.0")

# Earth's monitors worldwide (docs/TERMS-CHECK-EARTH-2026-10-16.md, section 5): shown live only under these licences, as OpenAQ names
# them; never kept in history/. Locations with no licence given, or under terms not yet read, stay off.
EARTH_LICENCES = ("CC BY 4.0", "CC0 1.0", "US Public Domain", "政府標準利用規約（第2.0版） (Government Standard Terms of Use v2.0)", "ODC-BY",
                  'UK OGL "Open Government License"', "CC BY-SA 4.0")
# providers never shown, whatever their licence on OpenAQ: invariant 6 (IQAir is never fetched)
NEVER_PROVIDERS = ("IQAir",)


def openaq_credit(provider, owner=None, licence=None):
    who = f"{owner} ({provider})" if owner and provider and owner != provider else (owner or provider or "Community sensor")
    return f"{who}, via OpenAQ" + (f", {licence}" if licence else ", no licence given")


def sources_in(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "source" and isinstance(v, str):
                out.add(v)
            sources_in(v, out)
    elif isinstance(obj, list):
        for v in obj:
            sources_in(v, out)
    return out


def assert_allowed(feed):
    """Raise ValueError if any value in the feed comes from a source not on the allow list."""
    bad = sorted(sources_in({k: v for k, v in feed.items() if k != "checks"}) - set(ALLOW))
    if bad:
        raise ValueError(f"not allowed in the public feed (docs/DATA-TERMS.md): {', '.join(bad)}")
