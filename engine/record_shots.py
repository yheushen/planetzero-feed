"""The record's pictures (session 8e, part 143i): what the site drew at a kept hour, drawn by the site itself, so the kept picture is the
site's own (its colours per band, its marks, its key and freshness line). Playwright opens the site's build (`record-site/`, copied to
the feed repository by `make feed-repo`) on Earth, Round 5, as a replay of the kept hour (part 143j: /earth?at=<hour>, the record
served at /record), with the browser's clock set to the hour the feed was built, so "this hour" and "Late" read as they did then and the
picture says "Kept: 17 Oct, 7:00 pm", never "Now" or "live". The standard layers: the smoke (adjusted to the monitors), the wind, the
fires, the monitors. 1280 by 800, WebP; a 640 by 400 thumbnail of each. Hidden: "Tap anywhere", the first visit's prompt to tap (a picture
is not tapped), and the replay's banner (the picture's place in the record dates it; the record's pages say it is kept).
"""
import datetime as dt
import gzip
import io
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

W, H = 1280, 800
TW, TH = 640, 400
QUALITY, THUMB_QUALITY = 78, 70
CHIPS = ("smoke", "wind", "fires", "monitors")
SEA_CENTRE, SEA_ZOOM = (6.0, 117.0), 3.5   # the Flat view's box at 1280 px: about 92 to 142 E


class Handler(SimpleHTTPRequestHandler):
    """The site's build at /, the record as it is at /record/ (a replay reads it there), the kept hour's data at /feed/ (each .json.gz
    served unzipped: the site as live, for the check that a kept picture matches it), the record's history/ and real/."""
    site = record = hour = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path.startswith("/record/"):
            src = Path(self.record) / path[len("/record/"):]
            if not src.is_file():
                self.send_error(404)
                return
            kinds = {".gz": "application/gzip", ".webp": "image/webp", ".json": "application/json"}
            return self.send_file(src, kinds.get(src.suffix, "application/octet-stream"))
        if path.startswith("/feed/"):
            rel = path[len("/feed/"):]
            base = Path(self.record)
            src = base / rel if rel.startswith("history/") else base / "hours" / self.hour / "data" / (rel + ".gz")
            if rel.startswith("history/"):
                return self.send_file(src, "application/json")
            if src.exists():
                return self.send_blob(gzip.decompress(src.read_bytes()), "application/json")
            self.send_error(404)
            return
        if path.startswith("/real/"):
            return self.send_file(Path(self.record) / path.lstrip("/"), "image/webp")
        if "." not in path.rsplit("/", 1)[-1]:   # the site's own pages (/earth): its index.html
            return self.send_file(Path(self.site) / "index.html", "text/html")
        return super().do_GET()

    def send_file(self, p, ctype):
        if not p.exists():
            self.send_error(404)
            return
        self.send_blob(p.read_bytes(), ctype)

    def send_blob(self, blob, ctype):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(blob)))
        self.end_headers()
        self.wfile.write(blob)


def serve(site, record):
    h = type("H", (Handler,), {"site": str(site), "record": str(record)})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(h, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, h


def webp(png, size, quality):
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=quality, method=6)
    return out.getvalue()


def shoot(page, base, view, built, hour=None):
    """1 view of the kept hour: Globe or Flat, Real Earth or Plain, the standard layers on; as a replay of the hour when given (else the
    site as live, reading /feed/)."""
    page.clock.install(time=built)
    if hour:   # the banner hidden before the page lays Earth out, so the picture has the live page's size
        page.add_init_script("window.__pzRecordBase = '/record'; document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style'); "
                             "s.textContent = '[data-kept-banner] { display: none !important }'; document.head.appendChild(s) })")
    page.goto(base + ("/earth?at=" + hour if hour else "/earth"), wait_until="domcontentloaded")
    page.wait_for_selector("[data-earth-stage][data-shown='yes']", timeout=90000)
    # "Tap anywhere" asks for a tap; a picture has none
    page.add_style_tag(content="[data-earth-hint] { display: none !important }")
    kind, base_ = view.split("-")
    if kind == "flat":   # Flat over Southeast Asia, about 92 to 142 E and 12 S to 24 N (the page's own map, moved by its hook)
        page.click("[data-view='flat']")
        page.wait_for_function("() => window.__pzMap && window.__pzMap.loaded()", timeout=60000)
        page.evaluate(f"() => window.__pzMap.go({SEA_CENTRE[0]}, {SEA_CENTRE[1]}, {SEA_ZOOM})")
    if base_ == "plain":
        page.click("[data-base='plain']")
    for c in CHIPS:
        box = page.locator(f"input[data-chip='{c}']")
        if box.count() and not box.first.is_checked() and box.first.is_enabled():
            box.first.check()
    page.wait_for_timeout(4000 if kind == "flat" else 2500)
    return page.screenshot(type="png")


def draw(record, due, site, browser=None):
    """Each (hour, view, full?) due: record/hours/<hour>/<view>.webp at full size when full, and <view>-thumb.webp always. Returns the
    seconds each took."""
    from playwright.sync_api import sync_playwright
    record, site = Path(record), Path(site)
    srv, h = serve(site, record)
    took = []
    try:
        with sync_playwright() as pw:
            b = browser or pw.chromium.launch()
            for hour, view, full in due:
                man = json.loads((record / "hours" / hour / "manifest.json").read_text(encoding="utf-8"))
                if not (record / "hours" / hour / "data").exists():
                    continue
                built = dt.datetime.fromisoformat(man["feed_generated_at"]) + dt.timedelta(minutes=2)
                h.hour = hour
                ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=1)
                ctx.add_init_script("try { localStorage.setItem('pz-earth-tour', 'done'); localStorage.setItem('pz-compare', JSON.stringify({ layout: 'after', site: 'after' })) } catch (e) {}")
                t0 = time.monotonic()
                try:
                    png = shoot(ctx.new_page(), f"http://127.0.0.1:{srv.server_address[1]}", view, built, hour)
                finally:
                    ctx.close()
                out = record / "hours" / hour
                if full:
                    (out / f"{view}.webp").write_bytes(webp(png, (W, H), QUALITY))
                (out / f"{view}-thumb.webp").write_bytes(webp(png, (TW, TH), THUMB_QUALITY))
                took.append((hour, view, round(time.monotonic() - t0, 1)))
            if not browser:
                b.close()
    finally:
        srv.shutdown()
    return took
