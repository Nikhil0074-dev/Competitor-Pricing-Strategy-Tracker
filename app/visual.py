"""Screenshot diffing (Pillow) and capture (Playwright)."""
import numpy as np
from PIL import Image, ImageChops
from .safety import validate_url, UnsafeURL

def diff_images(prev_path, cur_path, out_path, masks=(), threshold=24):
    """Return changed-pixel percentage. masks = [(x,y,w,h)] regions ignored as known noise."""
    a, b = Image.open(prev_path).convert("RGB"), Image.open(cur_path).convert("RGB")
    w, h = max(a.width, b.width), max(a.height, b.height)
    A, B = Image.new("RGB", (w, h), "white"), Image.new("RGB", (w, h), "white")
    A.paste(a); B.paste(b)
    d = ImageChops.difference(A, B).convert("L").point(lambda v: 255 if v > threshold else 0)
    mw_, mh_ = min(a.width, b.width), min(a.height, b.height)  # area present in only one image = layout change
    if (w, h) != (mw_, mh_):
        d.paste(255, (mw_, 0, w, h)); d.paste(255, (0, mh_, w, h))
    for x, y, mw, mh in masks:
        d.paste(0, (x, y, x + mw, y + mh))
    changed = int(np.count_nonzero(np.asarray(d)))
    over = B.copy(); over.paste(Image.new("RGB", (w, h), (220, 30, 30)), mask=d)
    over.save(out_path)
    return changed / (w * h) * 100

def capture(url, out_path, timeout_ms=15000):
    """Full-page screenshot, fixed viewport; every sub-request is re-validated (SSRF)."""
    from playwright.sync_api import sync_playwright
    def guard(route):
        try: validate_url(route.request.url); route.continue_()
        except UnsafeURL: route.abort()
    with sync_playwright() as p:
        br = p.chromium.launch()
        try:
            ctx = br.new_context(viewport={"width": 1280, "height": 800}, locale="en-US", timezone_id="UTC", reduced_motion="reduce")
            pg = ctx.new_page(); pg.route("**/*", guard)
            pg.goto(url, timeout=timeout_ms, wait_until="load")
            pg.add_style_tag(content="*{animation:none!important;transition:none!important}")
            pg.screenshot(path=out_path, full_page=True)
        finally:
            br.close()
