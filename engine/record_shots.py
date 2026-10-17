"""The kept pictures (session 8e, part 143i; part 153, frame 09 D): the map the site drew at a kept hour, drawn by the site itself from the
kept data, so its colours per band and its marks are the site's own; and only the map, never the site's header, menu, tabs, panels or
banner (a picture of the site inside the site is wrong, and the time-lapse would be a film of a website). Playwright opens the site's
build (`record-site/`, copied to the feed repository by `make feed-repo`) on Earth as a replay of the kept hour (/earth?at=<hour>, the
record served at /record), the browser's clock set to the hour the feed was built; the standard layers on (the smoke adjusted to the
monitors, the wind, the fires, the monitors); the site's chrome hidden by injected CSS; the picture clipped to the map:

  Globe   the globe on its paper, 800 px square (drawn at 1.5 times and made smaller, so it is sharp)
  Flat    Southeast Asia, 1280 by 720 (the map's own corner credit kept: OpenStreetMap's terms want it there)

Under the map, a strip (white, 12 px text, a hairline round it; the system's face: Helvetica Neue or Arial, Liberation Sans on Linux,
else Public Sans) carries invariant 1: the hour in Malaysia time, the smoke "an estimate from a computer model" with its run, the key
with each colour named, the wind's source and time, the fires' source and window, the base, "Kept by planetzero.ai." Its words come from
the hour's manifest (record.strip_words), and the day's index keeps them. WebP; a thumbnail at half the width.
"""
import datetime as dt
import gzip
import html
import io
import json
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

W, H = 1280, 800                 # the page's size while it draws (Earth's own layout at a laptop's width)
GLOBE_W = 800                    # the globe on its paper, square
GLOBE_SCALE = 1.5                # drawn at 1.5 times, then made 800 px
GLOBE_MARGIN = 12                # the paper round the globe, CSS px (the globe sits 16 px from the paper's edge)
FLAT_W, FLAT_H = 1280, 720       # Flat over Southeast Asia
QUALITY, THUMB_QUALITY = 80, 72
CHIPS = ("smoke", "wind", "fires", "monitors")
SEA_CENTRE, SEA_ZOOM = (6.0, 117.0), 3.5   # the Flat view's box at 1280 px: about 92 to 142 E
# everything that is the site and not the map: hidden, its place kept, so the map is laid out as the page lays it out
CHROME = (".site-header, [data-kept-banner], nav[aria-label='On this page'], .r5-panel, .r5-switches, .r5-zoom, .r5-below, .site-footer, "
          "[data-earth-hint], .r5-prow, .r5-psheet, [data-compare] { visibility: hidden !important }")
STRIP_CSS = ("html,body{margin:0;background:#FFFFFF}"
             ".s{box-sizing:border-box;background:#FFFFFF;box-shadow:inset 0 0 0 1px #D5DBE2;padding:8px 12px;color:#15202B;"
             "font:12px/16px 'Helvetica Neue',Helvetica,Arial,'Liberation Sans','PZ Public Sans',sans-serif}"
             ".s b{font-weight:700}.s .k{white-space:nowrap}.s i{display:inline-block;width:10px;height:10px;vertical-align:-1px}")


class Handler(SimpleHTTPRequestHandler):
    """The site's build at /, the record as it is at /record/ (a replay reads it there), the kept hour's data at /feed/ (each .json.gz
    served unzipped: the site as live, for the check that a kept picture matches it), the record's history/ and real/, and /__strip, a
    blank page the strip is drawn in."""
    site = record = hour = None

    def log_message(self, *a):
        pass

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/__strip":
            return self.send_blob(b"<!doctype html><meta charset=utf-8><title>strip</title><body></body>", "text/html")
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


def box(page, sel):
    return page.evaluate("s => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); "
                         "return { x: r.x + scrollX, y: r.y + scrollY, width: r.width, height: r.height } }", sel)


def shoot(page, base, view, built, hour=None):
    """1 view of the kept hour, the map alone (PNG, the page's own pixels): Globe or Flat, Real Earth or Plain, the standard layers on;
    as a replay of the hour when given (else the site as live, reading /feed/). The globe clipped to a square round it on its paper; Flat
    to the map, the page made as tall as a 1280 by 720 map needs."""
    page.clock.install(time=built)
    if hour:   # the banner hidden before the page lays Earth out, so the map has the live page's size
        page.add_init_script("window.__pzRecordBase = '/record'; document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style'); "
                             "s.textContent = '[data-kept-banner] { display: none !important }'; document.head.appendChild(s) })")
    page.goto(base + ("/earth?at=" + hour if hour else "/earth"), wait_until="domcontentloaded")
    page.wait_for_selector("[data-earth-stage][data-shown='yes']", timeout=90000)
    kind, base_ = view.split("-")
    if kind == "flat":   # Flat over Southeast Asia, about 92 to 142 E and 12 S to 24 N (the page's own map, moved by its hook)
        page.click("[data-view='flat']")
        page.wait_for_function("() => window.__pzMap && window.__pzMap.loaded()", timeout=60000)
    if base_ == "plain":
        page.click("[data-base='plain']")
    for c in CHIPS:
        b = page.locator(f"input[data-chip='{c}']")
        if b.count() and not b.first.is_checked() and b.first.is_enabled():
            b.first.check()
    page.add_style_tag(content=CHROME)
    if kind == "flat":
        m = box(page, "[data-r5-map]")
        if m and round(m["height"]) != FLAT_H:   # the page as tall as a 720 px map needs (the header and tabs above it vary)
            vp = page.viewport_size
            page.set_viewport_size({"width": vp["width"], "height": vp["height"] + FLAT_H - round(m["height"])})
            page.wait_for_function(f"() => Math.round(document.querySelector('[data-r5-map]').getBoundingClientRect().height) === {FLAT_H}", timeout=15000)
        page.evaluate(f"() => window.__pzMap.go({SEA_CENTRE[0]}, {SEA_CENTRE[1]}, {SEA_ZOOM})")
    page.wait_for_timeout(4000 if kind == "flat" else 2500)
    if kind == "flat":
        m = box(page, "[data-r5-map]")
        clip = {"x": m["x"], "y": m["y"], "width": min(m["width"], FLAT_W), "height": min(m["height"], FLAT_H)}
    else:
        g = box(page, "[data-earth-stage]")
        side = g["width"] + 2 * GLOBE_MARGIN
        clip = {"x": g["x"] + g["width"] / 2 - side / 2, "y": g["y"] + g["height"] / 2 - side / 2, "width": side, "height": side}
    return page.screenshot(type="png", clip=clip)


def strip_html(words, width):
    """The strip as HTML (frame 09 D): the hour in bold, the smoke, the key's swatches each with its word and colour's name, the rest."""
    key = " ".join(f'<span class="k"><i style="background:{c}"></i> {html.escape(w)}, {html.escape(n)}</span>' for w, n, c in words["key"])
    return (f'<div class="s" data-strip="" style="width:{width}px"><b>{html.escape(words["head"])}</b> {html.escape(words["smoke"])} {key}. '
            f'{html.escape(words["tail"])}</div>')


def strip_png(page, words, width, font_css=""):
    """The strip drawn by the browser, `width` px wide (PNG); its height is its lines'."""
    page.set_content(f"<!doctype html><meta charset=utf-8><style>{font_css}{STRIP_CSS}</style>{strip_html(words, width)}")
    page.evaluate("() => document.fonts.ready")
    return page.locator("[data-strip]").screenshot(type="png")


def public_sans(site):
    """The site's own Public Sans, the strip's last face before the browser's own (a machine with no Helvetica, Arial or Liberation)."""
    out = []
    for weight in (400, 700):
        hits = sorted(Path(site).glob(f"assets/public-sans-latin-{weight}-normal*.woff2"))
        if hits:
            out.append(f"@font-face{{font-family:'PZ Public Sans';font-weight:{weight};src:url('/assets/{hits[0].name}') format('woff2')}}")
    return "".join(out)


def compose(map_png, strip, size):
    """The map made `size`, the strip under it: 1 picture (PIL image)."""
    from PIL import Image
    m = Image.open(io.BytesIO(map_png)).convert("RGB")
    if m.size != size:
        m = m.resize(size, Image.LANCZOS)
    s = Image.open(io.BytesIO(strip)).convert("RGB")
    if s.size[0] != size[0]:
        s = s.resize((size[0], round(s.size[1] * size[0] / s.size[0])), Image.LANCZOS)
    out = Image.new("RGB", (size[0], size[1] + s.size[1]), (255, 255, 255))
    out.paste(m, (0, 0))
    out.paste(s, (0, size[1]))
    return out


def save(im, path, quality):
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "WEBP", quality=quality, method=6)


def thumb(im):
    from PIL import Image
    return im.resize((im.size[0] // 2, round(im.size[1] / 2)), Image.LANCZOS)


def map_size(view):
    return (GLOBE_W, GLOBE_W) if view.startswith("globe") else (FLAT_W, FLAT_H)


def draw(record, due, site, browser=None):
    """Each (hour, view, full?, where) due: <view>.webp when full and <view>-thumb.webp always, in record/hours/<hour>/ ("main": written
    once, a file already there is never drawn again) or record/.today/hours/<hour>/ ("today": the branch `today`, replaced). Returns
    [(hour, view, seconds)]."""
    import record as rec_
    from playwright.sync_api import sync_playwright
    record, site = Path(record), Path(site)
    srv, h = serve(site, record)
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    took = []
    try:
        with sync_playwright() as pw:
            b = browser or pw.chromium.launch()
            sctx = b.new_context(viewport={"width": FLAT_W, "height": 200}, device_scale_factor=1)
            spage = sctx.new_page()
            spage.goto(base + "/__strip")
            fonts = public_sans(site)
            for item in due:
                hour, view, full, where = item if len(item) == 4 else (*item, "main")
                out = (record / rec_.TODAY if where == "today" else record) / "hours" / hour
                want = ([out / f"{view}.webp"] if full else []) + [out / f"{view}-thumb.webp"]
                if where == "main":
                    want = [p for p in want if not p.exists()]
                if not want or not (record / "hours" / hour / "data").exists():
                    continue
                man = json.loads((record / "hours" / hour / "manifest.json").read_text(encoding="utf-8"))
                built = dt.datetime.fromisoformat(man["feed_generated_at"]) + dt.timedelta(minutes=2)
                h.hour = hour
                scale = GLOBE_SCALE if view.startswith("globe") else 1
                ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=scale)
                ctx.add_init_script("try { localStorage.setItem('pz-earth-tour', 'done'); localStorage.setItem('pz-compare', JSON.stringify({ layout: 'after', site: 'after' })) } catch (e) {}")
                t0 = time.monotonic()
                try:
                    png = shoot(ctx.new_page(), base, view, built, hour)
                finally:
                    ctx.close()
                size = map_size(view)
                im = compose(png, strip_png(spage, rec_.strip_words(man, view), size[0], fonts), size)
                for p in want:
                    if p.name.endswith("-thumb.webp"):
                        save(thumb(im), p, THUMB_QUALITY)
                    else:
                        save(im, p, QUALITY)
                took.append((hour, view, round(time.monotonic() - t0, 1)))
            sctx.close()
            if not browser:
                b.close()
    finally:
        srv.shutdown()
    return took
