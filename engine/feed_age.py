#!/usr/bin/env python3
"""How old a feed is, from its now.json's generated_at. The public feed's backup run builds only when the feed is over 40
minutes old (the outside timer's run already made this hour's); the audit builds fresh measurements only past 90 minutes.

    python engine/feed_age.py FEED_DIR MINUTES   # prints due=yes or due=no, for a GitHub step output

No now.json, or one that cannot be read, counts as too old: a build is due, never skipped on a broken feed.
"""
import argparse
import datetime as dt
import json
import os


def age_minutes(feed, now=None):
    """Minutes since the feed in `feed` was built, or None when its now.json is missing or cannot be read."""
    try:
        with open(os.path.join(feed, "now.json"), encoding="utf-8") as f:
            built = dt.datetime.fromisoformat(json.load(f)["generated_at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    now = now or dt.datetime.now(dt.timezone.utc)
    return round((now - built).total_seconds() / 60, 1)


def older_than(feed, minutes, now=None):
    age = age_minutes(feed, now)
    return age is None or age > minutes


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("feed", help="the feed folder (its now.json)")
    ap.add_argument("minutes", type=float, help="a build is due when the feed is older than this")
    a = ap.parse_args()
    print("due=" + ("yes" if older_than(a.feed, a.minutes) else "no"))


if __name__ == "__main__":
    main()
