from conftest import make_user
from fixtures.pages import pricing_html

def setup_page(client, srv, email):
    h = make_user(client, email)
    cid = client.post("/api/v1/competitors", json={"name": "Acme", "website_url": srv.url}, headers=h).json()["id"]
    pid = client.post("/api/v1/monitored-pages", json={"competitor_id": cid, "url": srv.url}, headers=h).json()["id"]
    return h, pid

def test_auth_required(client):
    assert client.get("/api/v1/competitors").status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": "no@x.com", "password": "password123"}).status_code == 401

def test_register_validation(client):
    assert client.post("/api/v1/auth/register", json={"email": "bad", "password": "short"}).status_code == 422
    make_user(client, "dup@x.com")
    assert client.post("/api/v1/auth/register", json={"email": "dup@x.com", "password": "password123"}).status_code == 409

def test_private_url_rejected_by_api(client, monkeypatch):
    h = make_user(client, "ssrf@x.com"); monkeypatch.delenv("ALLOW_PRIVATE")
    assert client.post("/api/v1/competitors", json={"name": "Evil", "website_url": "http://169.254.169.254/"}, headers=h).status_code == 422

def test_full_flow_price_change_visual_report(client, srv):
    h, pid = setup_page(client, srv, "flow@x.com")
    srv.html = pricing_html(); srv.status = 200
    r1 = client.post(f"/api/v1/monitored-pages/{pid}/scan", headers=h).json()
    assert r1["status"] == "DONE" and r1["baseline"] and r1["events"] == 0
    r1b = client.post(f"/api/v1/monitored-pages/{pid}/scan", headers=h).json()
    assert r1b["events"] == 0                                       # unchanged -> no duplicate events
    srv.html = pricing_html(starter="$12", business="$49", extra_feature=True)
    r2 = client.post(f"/api/v1/monitored-pages/{pid}/scan", headers=h).json()
    assert r2["events"] == 3
    ev = client.get("/api/v1/change-events", headers=h).json()
    kinds = {e["event_type"] for e in ev}
    assert kinds == {"PRICE_INCREASE", "NEW_PLAN", "FEATURE_ADDED"}
    inc = next(e for e in ev if e["event_type"] == "PRICE_INCREASE")
    assert (inc["previous"], inc["current"], round(inc["pct"])) == ("$10 / month", "$12 / month", 20)
    assert next(e for e in ev if e["event_type"] == "NEW_PLAN")["plan"] == "Business"
    # visual diff
    d = client.get("/api/v1/visual-diffs", headers=h).json()
    assert d and d[0]["changed_pct"] > 0
    assert client.get(f"/api/v1/visual-diffs/{d[0]['id']}/image", headers=h).headers["content-type"] == "image/png"
    snaps = client.get("/api/v1/snapshots", headers=h).json()
    assert client.get(f"/api/v1/snapshots/{snaps[0]['id']}/screenshot", headers=h).status_code == 200
    # profile + report
    client.put("/api/v1/product-profile", json={"name": "Mine", "features": "1 project\n10 projects"}, headers=h)
    rid = client.post("/api/v1/reports", headers=h).json()["id"]
    md = client.get(f"/api/v1/reports/{rid}/markdown", headers=h).text
    assert "$10 / month -> $12 / month (+20.0%)" in md and "New plan 'Business'" in md
    assert "Automated reporting" not in md.split("Feature Changes")[0]
    assert "Signal for investigation" in md and "SSO" in md                # gap analysis uses profile
    pdf = client.get(f"/api/v1/reports/{rid}/pdf", headers=h)
    assert pdf.content[:5] == b"%PDF-" and len(pdf.content) > 1500

def test_failed_fetch_is_not_content_change(client, srv):
    h, pid = setup_page(client, srv, "fail@x.com")
    srv.html, srv.status = pricing_html(), 200
    client.post(f"/api/v1/monitored-pages/{pid}/scan?shots=false", headers=h)
    srv.status = 503
    r = client.post(f"/api/v1/monitored-pages/{pid}/scan?shots=false", headers=h).json()
    assert r["status"] == "FAILED"
    ev = client.get("/api/v1/change-events", headers=h).json()
    assert [e["event_type"] for e in ev] == ["PAGE_UNAVAILABLE"]      # no REMOVED_PLAN events
    srv.status = 200
    r = client.post(f"/api/v1/monitored-pages/{pid}/scan?shots=false", headers=h).json()
    assert r["status"] == "DONE" and r["events"] == 0                  # compares against last VALID snapshot

def test_workspace_isolation(client, srv):
    h1, pid = setup_page(client, srv, "w1@x.com"); h2 = make_user(client, "w2@x.com")
    srv.html, srv.status = pricing_html(), 200
    client.post(f"/api/v1/monitored-pages/{pid}/scan?shots=false", headers=h1)
    assert client.get("/api/v1/competitors", headers=h2).json() == []
    assert client.get("/api/v1/pricing", headers=h2).json() == []
    assert client.post(f"/api/v1/monitored-pages/{pid}/scan", headers=h2).status_code == 404
    assert client.post("/api/v1/monitored-pages", json={"competitor_id": 1, "url": srv.url}, headers=h2).status_code == 404
    rid = client.post("/api/v1/reports", headers=h1).json()["id"]
    assert client.get(f"/api/v1/reports/{rid}/markdown", headers=h2).status_code == 404
    snap = client.get("/api/v1/snapshots", headers=h1).json()[0]["id"]
    assert client.get(f"/api/v1/snapshots/{snap}/screenshot", headers=h2).status_code == 404

def test_pricing_endpoint_latest_only(client, srv):
    h, pid = setup_page(client, srv, "pr@x.com")
    srv.html, srv.status = pricing_html(), 200
    client.post(f"/api/v1/monitored-pages/{pid}/scan?shots=false", headers=h)
    srv.html = pricing_html(starter="$15")
    client.post(f"/api/v1/monitored-pages/{pid}/scan?shots=false", headers=h)
    rows = client.get("/api/v1/pricing", headers=h).json()
    assert {r["plan_name"]: r["amount"] for r in rows}["Starter"] == "15" and len(rows) == 3
