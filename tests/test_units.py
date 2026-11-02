import os, pytest
from PIL import Image
from app.extract import parse_price, parse_page, detect_changes, pct_change
from app.safety import validate_url, UnsafeURL
from app.visual import diff_images
from fixtures.pages import pricing_html

# ---- pricing extraction
@pytest.mark.parametrize("text,amt,cur,intv,basis", [
    ("$19 / month", "19", "USD", "month", "unknown"),
    ("$190 / year", "190", "USD", "year", "unknown"),
    ("₹999 per user/month", "999", "INR", "month", "user"),
    ("€1,299.50 per year", "1299.50", "EUR", "year", "unknown"),
])
def test_price_formats(text, amt, cur, intv, basis):
    p = parse_price(text)
    assert (p["amount"], p["currency"], p["billing_interval"], p["billing_basis"]) == (amt, cur, intv, basis)

def test_free_custom_missing():
    assert parse_price("Free forever")["amount"] == "0"
    assert parse_price("Contact sales")["status"] == "CUSTOM"
    m = parse_price("Great value")
    assert m["amount"] is None and m["status"] == "REVIEW_REQUIRED"

def test_per_user_not_assumed():
    assert parse_price("$12 / month")["billing_basis"] == "unknown"

def test_parse_page_plans():
    plans = parse_page(pricing_html())["plans"]
    assert [p["plan_name"] for p in plans] == ["Starter", "Pro", "Enterprise"]
    assert plans[0]["features"] == ["1 project"] and plans[2]["status"] == "CUSTOM"

# ---- change detection
def plans(**k): return parse_page(pricing_html(**k))["plans"]
def types(ev): return sorted(e["event_type"] for e in ev)

def test_no_change(): assert detect_changes(plans(), plans()) == []
def test_price_increase_pct():
    ev = detect_changes(plans(), plans(starter="$12"))
    assert types(ev) == ["PRICE_INCREASE"] and round(ev[0]["pct"]) == 20 and ev[0]["plan"] == "Starter"
def test_price_decrease():
    assert types(detect_changes(plans(), plans(pro="$20"))) == ["PRICE_DECREASE"]
def test_new_and_removed_plan():
    assert types(detect_changes(plans(), plans(business="$49"))) == ["NEW_PLAN"]
    assert types(detect_changes(plans(business="$49"), plans())) == ["REMOVED_PLAN"]
def test_feature_added():
    assert types(detect_changes(plans(), plans(extra_feature=True))) == ["FEATURE_ADDED"]
def test_no_match_by_similar_price():
    old = plans(starter="$10"); new = parse_page(pricing_html(starter="$10").replace("Starter", "Basic"))["plans"]
    assert types(detect_changes(old, new)) == ["NEW_PLAN", "REMOVED_PLAN"]
def test_interval_change_needs_review_no_pct():
    o = [dict(plan_name="X", normalized_plan_name="x", displayed_price="$10/month", amount="10", currency="USD", billing_interval="month", billing_basis="unknown", features=[])]
    n = [dict(o[0], displayed_price="$100/year", amount="100", billing_interval="year")]
    ev = detect_changes(o, n)
    assert types(ev) == ["EXTRACTION_REVIEW_REQUIRED"] and ev[0]["pct"] is None
def test_pct_zero_or_missing():
    assert pct_change("0", "5") is None and pct_change(None, "5") is None and pct_change("10", "12") == pytest.approx(20)
def test_whitespace_only_change_same_hash():
    assert parse_page(pricing_html())["hash"] == parse_page(pricing_html().replace("<body>", "<body>\n\n   "))["hash"]

# ---- SSRF
@pytest.mark.parametrize("u", ["ftp://example.com", "file:///etc/passwd", "http://user:pw@example.com", "javascript:alert(1)", "", "http://example.com:invalid/", "http://[invalid]/"])
def test_bad_schemes(u):
    with pytest.raises(UnsafeURL): validate_url(u)

@pytest.mark.parametrize("u", ["http://127.0.0.1/", "http://localhost/", "http://10.0.0.5/", "http://192.168.1.1/",
                               "http://169.254.169.254/latest/meta-data/", "http://[::1]/"])
def test_private_blocked(u, monkeypatch):
    monkeypatch.delenv("ALLOW_PRIVATE")
    with pytest.raises(UnsafeURL): validate_url(u)

# ---- visual diff
def img(path, color, box=None):
    im = Image.new("RGB", (200, 100), "white")
    if box: im.paste(color, box)
    im.save(path); return str(path)

def test_visual_identical_and_different(tmp_path):
    a, b = img(tmp_path / "a.png", "red"), img(tmp_path / "b.png", "red")
    assert diff_images(a, b, str(tmp_path / "d.png")) == 0
    c = img(tmp_path / "c.png", "black", (0, 0, 100, 50))
    assert diff_images(a, c, str(tmp_path / "d2.png")) == pytest.approx(25, abs=0.1)

def test_visual_mask_ignores_noise(tmp_path):
    a, c = img(tmp_path / "a.png", "red"), img(tmp_path / "c.png", "black", (0, 0, 100, 50))
    assert diff_images(a, c, str(tmp_path / "d.png"), masks=[(0, 0, 100, 50)]) == 0

def test_visual_different_sizes(tmp_path):
    a = img(tmp_path / "a.png", "red"); Image.new("RGB", (200, 150), "white").save(tmp_path / "b.png")
    assert diff_images(a, str(tmp_path / "b.png"), str(tmp_path / "d.png")) > 0
