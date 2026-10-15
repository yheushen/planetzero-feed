"""Coordinates in public files: 2 decimals, about 1 km (Cowork's run 2 review, item 3). The site needs no more than the
distance, which the engine works out from the exact positions before anything is written; sensor owners stay named, as
CC BY asks. Every public JSON goes through rounded() on its way to disk (build_feed.write_json, history.merge)."""
COORD_KEYS = {"lat", "lon", "lng", "latitude", "longitude"}
DECIMALS = 2


def rounded(o):
    """A copy of o with every coordinate rounded to 2 decimals, at any depth."""
    if isinstance(o, dict):
        return {k: round(v, DECIMALS) if k.lower() in COORD_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool) else rounded(v)
                for k, v in o.items()}
    if isinstance(o, list):
        return [rounded(x) for x in o]
    return o
