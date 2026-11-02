"""Synthetic pricing pages and a tiny local server. All data is fictional."""
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def pricing_html(starter="$10", pro="$25", business=None, extra_feature=False, noise=""):
    biz = f'<div class="plan"><h3>Business</h3><p class="price">{business} / month</p><ul><li>SSO</li></ul></div>' if business else ""
    feat = "<li>Automated reporting</li>" if extra_feature else ""
    return f"""<html><head><title>Acme Pricing</title><style>
    body{{font-family:sans-serif;margin:40px;background:#f6f7f9}} .plans{{display:flex;gap:20px}}
    .plan{{background:#fff;border:1px solid #ccd;padding:20px;width:220px}} .price{{font-size:28px;font-weight:bold}}</style></head>
    <body><h1>Acme Analytics Pricing</h1>{noise}<div class="plans">
    <div class="plan"><h3>Starter</h3><p class="price">{starter} / month</p><ul><li>1 project</li></ul></div>
    <div class="plan"><h3>Pro</h3><p class="price">{pro} / month</p><ul><li>10 projects</li>{feat}</ul></div>
    {biz}<div class="plan"><h3>Enterprise</h3><p class="price">Contact sales</p><ul><li>Custom limits</li></ul></div>
    </div></body></html>"""

class Server:
    def __init__(self):
        self.html, self.status = pricing_html(), 200
        outer = self
        class H(BaseHTTPRequestHandler):
            def do_GET(s):
                if s.path == "/robots.txt": s.send_response(404); s.end_headers(); return
                s.send_response(outer.status); s.send_header("Content-Type", "text/html"); s.end_headers()
                s.wfile.write(outer.html.encode())
            def log_message(s, *a): pass
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.httpd.server_port}/pricing"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
    def stop(self): self.httpd.shutdown()
