# get_json copied from ~/projects/05_planet-zero/haze-logger/logger.py on 2026-10-15; changed: it now goes
# through 1 swappable object, so the same fetchers run live, record, or replay recorded answers offline.
"""How the engine talks to the outside world.

Every fetcher calls get_json(url, headers) or get_text(url, headers) from this module. They go through
TRANSPORT, which is 1 of:
  Live()      urllib with retries (the logger's get_json), IPv4 only like the logger.
  Recorder()  Live, and also saves each answer under engine/tests/recorded/ (gzipped).
  Replay()    answers only from engine/tests/recorded/, so tests and `make dev` run offline.
  Failing()   raises for chosen sources, to prove a failed fetch is shown as missing (F6).

A recorded answer is found by request_key(url): the host, the path and the query, minus anything secret
(the FIRMS key in the path, any key or token) and minus the time window parameters that change with the
clock. The engine filters every answer by its own clock afterwards, so a recording made later in the day
replays correctly for an earlier hour.
"""
import gzip
import hashlib
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

# GitHub's runners have no IPv6 route and some servers (NASA FIRMS) advertise one first: keep every connection on IPv4
_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: [ai for ai in _getaddrinfo(*a, **k) if ai[0] == socket.AF_INET] or _getaddrinfo(*a, **k)

RECORDED = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "recorded")
# query parameters that move with the clock or carry secrets: never part of a key
VOLATILE = {"datetime_from", "datetime_to", "past_days", "forecast_days", "start_date", "end_date", "token", "key", "api_key"}
FIRMS_PATH = re.compile(r"^(/api/area/csv/)[^/]+/([^/]+)/([^/]+)(?:/.*)?$")


class FetchError(Exception):
    """A source did not answer, or answered with something unusable."""


def request_key(url):
    p = urllib.parse.urlsplit(url)
    path = p.path
    m = FIRMS_PATH.match(path)
    if m:   # /api/area/csv/<KEY>/<SATELLITE>/<BOX>/<DAYS>/<DATE>: keep the satellite and the box only
        path = f"{m.group(1)}{m.group(2)}/{m.group(3)}"
    q = sorted((k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True) if k not in VOLATILE)
    return p.netloc + path + ("?" + urllib.parse.urlencode(q) if q else "")


def key_file(key):
    tail = re.sub(r"[^A-Za-z0-9]+", "_", urllib.parse.urlsplit("//" + key).path)[-40:].strip("_")
    return f"{tail}_{hashlib.sha1(key.encode()).hexdigest()[:10]}.gz"


class Live:
    def fetch(self, url, headers=None, tries=4, timeout=60):
        req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
        err = None
        for i in range(tries):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                err = FetchError(f"HTTP {e.code} from {urllib.parse.urlsplit(url).netloc}")
                if e.code in (400, 401, 403, 404):
                    break   # asking again will not help
            except Exception as e:
                err = FetchError(f"{type(e).__name__} from {urllib.parse.urlsplit(url).netloc}")
            time.sleep(4 + 6 * i)
        raise err


class Recorder(Live):
    def fetch(self, url, headers=None, tries=4, timeout=60):
        body = super().fetch(url, headers, tries, timeout)
        key = request_key(url)
        os.makedirs(RECORDED, exist_ok=True)
        with gzip.open(os.path.join(RECORDED, key_file(key)), "wb") as f:
            f.write(body)
        index_path = os.path.join(RECORDED, "index.json")
        index = json.load(open(index_path)) if os.path.exists(index_path) else {}
        index[key] = key_file(key)
        json.dump(dict(sorted(index.items())), open(index_path, "w"), indent=1)
        return body


class Replay:
    def __init__(self, folder=RECORDED):
        self.folder = folder
        self.asked = []

    def fetch(self, url, headers=None, tries=4, timeout=60):
        key = request_key(url)
        self.asked.append(key)
        path = os.path.join(self.folder, key_file(key))
        if not os.path.exists(path):
            raise FetchError(f"no recorded answer for {key}")
        with gzip.open(path, "rb") as f:
            return f.read()


class Failing:
    """Wraps another transport and fails every request to the given hosts."""

    def __init__(self, inner, hosts):
        self.inner, self.hosts = inner, set(hosts)

    def fetch(self, url, headers=None, tries=4, timeout=60):
        if urllib.parse.urlsplit(url).netloc in self.hosts:
            raise FetchError(f"{urllib.parse.urlsplit(url).netloc} did not answer (test)")
        return self.inner.fetch(url, headers, tries, timeout)


TRANSPORT = Live()


def get_bytes(url, headers=None, tries=4, timeout=60):
    return TRANSPORT.fetch(url, headers, tries, timeout)


def get_json(url, headers=None, tries=4, timeout=60):
    body = get_bytes(url, headers, tries, timeout)
    try:
        return json.loads(body)
    except ValueError:
        raise FetchError(f"not JSON from {urllib.parse.urlsplit(url).netloc}")


def get_text(url, headers=None, tries=4, timeout=60):
    return get_bytes(url, headers, tries, timeout).decode("utf-8", "replace")
