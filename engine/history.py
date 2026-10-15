# The idea of merge_csv and month_path from ~/projects/05_planet-zero/haze-logger/logger.py (2026-10-15): append,
# deduplicate on a key, keep sorted, split by month. Changed: JSON instead of CSV, keyed by series and local hour.
"""Hourly history in the feed: history/<source>/<yyyy-mm>.json.

Each file: {"source", "unit", "window", "note", "credits", "series": {series id: {"YYYY-MM-DDTHH:MM": value}}}, and for
community sensors "locations": {id: {name, owner, licence, ...}}: only locations under an open licence are kept.
Every run refetches about 2 days from each source that keeps history and merges it here, so hours that
GitHub skipped are filled on the next run (SPEC section 5). The whole region is in 1 file per month, so the
browser can read it without ever saying where anyone is (invariant 7).
"""
import json
import os

import publish
from sources import NO_HISTORY


def path(out, source, month):
    return os.path.join(out, "history", source, month + ".json")


def merge(out, source, meta, rows, overwrite=True):
    """rows: (series id, local time 'YYYY-MM-DDTHH:MM', value). Returns how many distinct hours were new.
    overwrite=False keeps the values already there (a backfill never replaces what the feed fetched itself)."""
    if source in NO_HISTORY:
        raise ValueError(f"{source} may be shown now but never kept in history/ (docs/DATA-TERMS.md)")
    by_month = {}
    for sid, t, v in rows:
        if v is None or v == "":
            continue
        by_month.setdefault(t[:7], []).append((str(sid), t[:16], v))
    new_hours = set()
    for month, rs in by_month.items():
        p = path(out, source, month)
        have = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"series": {}}
        # the description and credits are the run's own (credits carry the day the data was fetched); locations add up
        locations = {**have.get("locations", {}), **meta.get("locations", {})}
        have = {**have, **{k: v for k, v in meta.items() if k != "series"}, "series": have["series"]}
        if locations:
            have["locations"] = dict(sorted(locations.items()))
        for sid, t, v in rs:
            s = have["series"].setdefault(sid, {})
            if t not in s:
                new_hours.add(t)
            elif not overwrite:
                continue
            s[t] = v
        have["series"] = {sid: dict(sorted(s.items())) for sid, s in sorted(have["series"].items())}
        if "locations" in meta:   # a file with licences per location keeps only those locations (it drops any kept before the rule)
            have["series"] = {sid: s for sid, s in have["series"].items() if sid in have.get("locations", {})}
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(publish.rounded(have), f, ensure_ascii=False, separators=(",", ":"))   # coordinates to 2 decimals
        os.replace(tmp, p)
    return len(new_hours)


def series(out, source, sid, months):
    s = {}
    for m in months:
        p = path(out, source, m)
        if os.path.exists(p):
            s.update(json.load(open(p, encoding="utf-8"))["series"].get(str(sid), {}))
    return s
