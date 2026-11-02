"""Runs the full demo on synthetic pages and saves UI screenshots to screenshots/."""
import os, sys, time, threading, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["ALLOW_PRIVATE"] = "1"; os.environ["DATA_DIR"] = tempfile.mkdtemp()
import httpx, uvicorn
from playwright.sync_api import sync_playwright
from fixtures.pages import Server, pricing_html
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "screenshots"; OUT.mkdir(exist_ok=True)
srv = Server()
from app.main import app
threading.Thread(target=lambda: uvicorn.run(app, port=8765, log_level="warning"), daemon=True).start()
for _ in range(50):
    try: httpx.get("http://127.0.0.1:8765/"); break
    except Exception: time.sleep(0.2)
B = "http://127.0.0.1:8765"
tok = httpx.post(B + "/api/v1/auth/register", json={"email": "demo@example.com", "password": "password123"}).json()["token"]
H = {"Authorization": "Bearer " + tok}
cid = httpx.post(B + "/api/v1/competitors", json={"name": "Acme Analytics (demo)", "website_url": srv.url}, headers=H).json()["id"]
pid = httpx.post(B + "/api/v1/monitored-pages", json={"competitor_id": cid, "url": srv.url}, headers=H).json()["id"]
httpx.put(B + "/api/v1/product-profile", json={"name": "My product", "features": "1 project\n10 projects"}, headers=H)
scan = lambda: httpx.post(f"{B}/api/v1/monitored-pages/{pid}/scan", headers=H, timeout=60).json()
print("baseline:", scan())
srv.html = pricing_html(starter="$12", business="$49", extra_feature=True)
print("after change:", scan())
httpx.post(B + "/api/v1/reports", headers=H)
with sync_playwright() as p:
    br = p.chromium.launch(); pg = br.new_page(viewport={"width": 1280, "height": 800}); pg.goto(B)
    pg.screenshot(path=OUT / "01-login.png")
    pg.evaluate(f"localStorage.setItem('t','{tok}')"); pg.reload()
    for i, (v, name) in enumerate([("dash", "dashboard"), ("comps", "competitors"), ("pricing", "pricing"), ("timeline", "timeline"), ("reports", "reports"), ("profile", "profile")], 2):
        pg.click(f'nav [data-v="{v}"]'); pg.wait_for_timeout(700)
        if v == "reports": pg.click("[data-v]:has-text('Preview')"); pg.wait_for_timeout(300)
        pg.screenshot(path=OUT / f"{i:02d}-{name}.png", full_page=(v == "timeline"))
    br.close()
print("saved", sorted(x.name for x in OUT.iterdir()))
