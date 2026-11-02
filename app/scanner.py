import datetime as dt, json, urllib.robotparser
from urllib.parse import urljoin, urlparse
import httpx
from .db import q, ex, data_dir
from .extract import parse_page, detect_changes
from .safety import validate_url, UnsafeURL
from .visual import capture, diff_images

MAX_BYTES, UA = 2_000_000, "CompetitorTrackerBot/1.0 (+public-pages-only)"
now = lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

class FetchError(Exception):
    def __init__(self, code): self.code = code

def fetch(url, retries=2):
    """Safe GET: validates every redirect hop, checks robots.txt, caps size, bounded retries."""
    cur = validate_url(url)
    try:
        r = httpx.get(urljoin(cur, "/robots.txt"), timeout=5, headers={"User-Agent": UA})
        if r.status_code == 200:
            rp = urllib.robotparser.RobotFileParser(); rp.parse(r.text.splitlines())
            if not rp.can_fetch(UA, cur): raise FetchError("ROBOTS_BLOCKED")
    except httpx.HTTPError: pass
    for attempt in range(retries + 1):
        try:
            for _ in range(4):
                r = httpx.get(cur, timeout=10, headers={"User-Agent": UA}, follow_redirects=False)
                if r.status_code in (301, 302, 303, 307, 308):
                    cur = validate_url(urljoin(cur, r.headers.get("location", ""))); continue
                break
            else: raise FetchError("TOO_MANY_REDIRECTS")
            if r.status_code in (401, 403, 429): raise FetchError(f"ACCESS_{r.status_code}")
            if r.status_code >= 500 and attempt < retries: continue
            if r.status_code >= 400: raise FetchError(f"HTTP_{r.status_code}")
            if len(r.content) > MAX_BYTES: raise FetchError("TOO_LARGE")
            return cur, r.status_code, r.text
        except httpx.HTTPError:
            if attempt == retries: raise FetchError("NETWORK_ERROR")
    raise FetchError("NETWORK_ERROR")

def scan_page(page_id, with_screenshot=True):
    page = q("SELECT * FROM pages WHERE id=?", (page_id,))[0]; ws = page["workspace_id"]
    job = ex("INSERT INTO jobs(workspace_id,page_id,status,started_at) VALUES(?,?,?,?)", (ws, page_id, "RUNNING", now()))
    ex("UPDATE pages SET last_checked_at=? WHERE id=?", (now(), page_id))
    prev = q("SELECT * FROM snapshots WHERE page_id=? AND status='OK' ORDER BY id DESC LIMIT 1", (page_id,))
    prev = prev[0] if prev else None
    try:
        final, status, html = fetch(page["url"])
    except (FetchError, UnsafeURL) as e:
        code = e.code if isinstance(e, FetchError) else "UNSAFE_URL"
        # A failed fetch is NOT a content change: keep last valid snapshot, record failure only.
        ex("INSERT INTO snapshots(workspace_id,page_id,captured_at,status,error_code) VALUES(?,?,?,?,?)", (ws, page_id, now(), "FAILED", code))
        ex("INSERT INTO events(workspace_id,competitor_id,page_id,event_type,summary,severity,detected_at) VALUES(?,?,?,?,?,?,?)",
           (ws, page["competitor_id"], page_id, "PAGE_UNAVAILABLE", f"Page could not be captured ({code}). No content change is implied.", "MEDIUM", now()))
        ex("UPDATE jobs SET status='FAILED', error_code=?, completed_at=? WHERE id=?", (code, now(), job))
        return dict(job_id=job, status="FAILED", error_code=code, events=0)
    parsed = parse_page(html)
    sid = ex("INSERT INTO snapshots(workspace_id,page_id,captured_at,http_status,content_hash,text,status) VALUES(?,?,?,?,?,?,?)",
             (ws, page_id, now(), status, parsed["hash"], parsed["text"], "OK"))
    for p in parsed["plans"]:
        ex("INSERT INTO pricing(workspace_id,snapshot_id,plan_name,norm_name,displayed_price,amount,currency,billing_interval,billing_basis,status,features) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
           (ws, sid, p["plan_name"], p["normalized_plan_name"], p["displayed_price"], p["amount"], p["currency"], p["billing_interval"], p["billing_basis"], p["status"], json.dumps(p["features"])))
    if with_screenshot:
        try:
            path = data_dir() / "shots" / f"{sid}.png"; capture(final, str(path))
            ex("UPDATE snapshots SET shot=? WHERE id=?", (str(path), sid))
        except Exception:
            pass  # screenshot is optional context; text/pricing remain the source of truth
    n = 0
    if prev and prev["content_hash"] != parsed["hash"]:  # identical hash -> no duplicate events
        old = [dict(plan_name=r["plan_name"], normalized_plan_name=r["norm_name"], displayed_price=r["displayed_price"], amount=r["amount"],
                    currency=r["currency"], billing_interval=r["billing_interval"], billing_basis=r["billing_basis"], features=json.loads(r["features"]))
               for r in q("SELECT * FROM pricing WHERE snapshot_id=?", (prev["id"],))]
        evs = detect_changes(old, parsed["plans"])
        cur = q("SELECT * FROM snapshots WHERE id=?", (sid,))[0]
        if prev["shot"] and cur["shot"]:
            out = data_dir() / "shots" / f"diff_{prev['id']}_{sid}.png"
            pct = diff_images(prev["shot"], cur["shot"], str(out))
            ex("INSERT INTO diffs(workspace_id,prev_snapshot,cur_snapshot,path,changed_pct) VALUES(?,?,?,?,?)", (ws, prev["id"], sid, str(out), pct))
            if pct > 0.5 and not evs:
                evs.append(dict(event_type="VISUAL_LAYOUT_CHANGED", severity="INFO", plan=None, previous=None, current=None, pct=None,
                                summary=f"Page text changed and {pct:.1f}% of pixels differ; no pricing change detected."))
        for e in evs:
            ex("INSERT INTO events(workspace_id,competitor_id,page_id,prev_snapshot,cur_snapshot,event_type,plan,previous,current,pct,summary,severity,detected_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (ws, page["competitor_id"], page_id, prev["id"], sid, e["event_type"], e["plan"], e["previous"], e["current"], e["pct"], e["summary"], e["severity"], now()))
        n = len(evs)
    ex("UPDATE pages SET last_success_at=? WHERE id=?", (now(), page_id))
    ex("UPDATE jobs SET status='DONE', completed_at=? WHERE id=?", (now(), job))
    return dict(job_id=job, status="DONE", snapshot_id=sid, events=n, baseline=prev is None)
