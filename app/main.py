import hashlib, os, secrets, datetime as dt
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.responses import FileResponse, Response, JSONResponse
from pydantic import BaseModel
from .db import q, ex, data_dir
from .safety import validate_url, UnsafeURL
from .scanner import scan_page
from .report import build_markdown, markdown_to_pdf

app = FastAPI(title="Competitor Pricing & Strategy Tracker")
P = "/api/v1"

def hpw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 120_000).hex()

class Auth(BaseModel): email: str; password: str

def ctx(authorization: str = Header(None), token: str = Query(None)):
    t = (authorization or "").removeprefix("Bearer ").strip() or token
    r = q("SELECT m.user_id, m.workspace_id, m.role FROM sessions s JOIN members m ON m.user_id=s.user_id WHERE s.token=?", (t,)) if t else []
    if not r: raise HTTPException(401, "Authentication required")
    return r[0]

def writer(c=Depends(ctx)):
    if c["role"] == "viewer": raise HTTPException(403, "Viewers cannot modify data")
    return c

@app.post(P + "/auth/register")
def register(a: Auth):
    if len(a.password) < 8 or "@" not in a.email: raise HTTPException(422, "Valid email and 8+ character password required")
    if q("SELECT 1 FROM users WHERE email=?", (a.email.lower(),)): raise HTTPException(409, "Email already registered")
    uid = ex("INSERT INTO users(email,pw) VALUES(?,?)", (a.email.lower(), hpw(a.password)))
    wid = ex("INSERT INTO workspaces(name) VALUES(?)", (a.email.split("@")[0] + "'s workspace",))
    ex("INSERT INTO members VALUES(?,?,?)", (uid, wid, "admin"))
    return login(a)

@app.post(P + "/auth/login")
def login(a: Auth):
    u = q("SELECT * FROM users WHERE email=?", (a.email.lower(),))
    if not u or hpw(a.password, u[0]["pw"].split("$")[0]) != u[0]["pw"]: raise HTTPException(401, "Invalid credentials")
    t = secrets.token_urlsafe(24); ex("INSERT INTO sessions VALUES(?,?)", (t, u[0]["id"])); return {"token": t}

class Comp(BaseModel): name: str; website_url: str; notes: str = ""
@app.post(P + "/competitors")
def add_comp(b: Comp, c=Depends(writer)):
    try: validate_url(b.website_url)
    except UnsafeURL as e: raise HTTPException(422, str(e))
    return {"id": ex("INSERT INTO competitors(workspace_id,name,website_url,notes) VALUES(?,?,?,?)", (c["workspace_id"], b.name, b.website_url, b.notes))}

@app.get(P + "/competitors")
def list_comp(c=Depends(ctx)): return q("SELECT * FROM competitors WHERE workspace_id=?", (c["workspace_id"],))

class Pg(BaseModel): competitor_id: int; url: str; page_type: str = "PRICING"; monitoring_interval_minutes: int = 1440
@app.post(P + "/monitored-pages")
def add_page(b: Pg, c=Depends(writer)):
    if not q("SELECT 1 FROM competitors WHERE id=? AND workspace_id=?", (b.competitor_id, c["workspace_id"])): raise HTTPException(404, "Competitor not found")
    try: validate_url(b.url)
    except UnsafeURL as e: raise HTTPException(422, str(e))
    return {"id": ex("INSERT INTO pages(workspace_id,competitor_id,url,page_type,interval_minutes) VALUES(?,?,?,?,?)", (c["workspace_id"], b.competitor_id, b.url, b.page_type, b.monitoring_interval_minutes))}

@app.get(P + "/monitored-pages")
def list_pages(c=Depends(ctx)): return q("SELECT * FROM pages WHERE workspace_id=?", (c["workspace_id"],))

@app.post(P + "/monitored-pages/{pid}/scan")
def scan(pid: int, shots: bool = True, c=Depends(writer)):
    if not q("SELECT 1 FROM pages WHERE id=? AND workspace_id=?", (pid, c["workspace_id"])): raise HTTPException(404, "Page not found")
    return scan_page(pid, with_screenshot=shots)

@app.get(P + "/snapshots")
def snaps(c=Depends(ctx)): return q("SELECT id,page_id,captured_at,http_status,status,error_code,shot IS NOT NULL AS has_shot FROM snapshots WHERE workspace_id=? ORDER BY id DESC", (c["workspace_id"],))

@app.get(P + "/pricing")
def pricing(c=Depends(ctx)):
    return q("""SELECT p.*, c.name AS competitor, s.captured_at FROM pricing p JOIN snapshots s ON s.id=p.snapshot_id JOIN pages g ON g.id=s.page_id
                JOIN competitors c ON c.id=g.competitor_id WHERE p.workspace_id=? AND s.id IN (SELECT MAX(id) FROM snapshots WHERE status='OK' GROUP BY page_id)""", (c["workspace_id"],))

@app.get(P + "/change-events")
def events(event_type: str = None, c=Depends(ctx)):
    sql, a = "SELECT e.*, c.name AS competitor FROM events e JOIN competitors c ON c.id=e.competitor_id WHERE e.workspace_id=?", [c["workspace_id"]]
    if event_type: sql += " AND e.event_type=?"; a.append(event_type)
    return q(sql + " ORDER BY e.id DESC", a)

@app.get(P + "/jobs")
def jobs(c=Depends(ctx)): return q("SELECT * FROM jobs WHERE workspace_id=? ORDER BY id DESC", (c["workspace_id"],))

@app.get(P + "/visual-diffs")
def vdiffs(c=Depends(ctx)): return q("SELECT id,prev_snapshot,cur_snapshot,changed_pct FROM diffs WHERE workspace_id=? ORDER BY id DESC", (c["workspace_id"],))

def _img(path, ws, table, col, key):
    r = q(f"SELECT {col} AS p FROM {table} WHERE {key}=? AND workspace_id=?", (path, ws))
    if not r or not r[0]["p"] or not Path(r[0]["p"]).exists(): raise HTTPException(404, "Not found")
    return FileResponse(r[0]["p"], media_type="image/png")

@app.get(P + "/snapshots/{sid}/screenshot")
def shot(sid: int, c=Depends(ctx)): return _img(sid, c["workspace_id"], "snapshots", "shot", "id")
@app.get(P + "/visual-diffs/{did}/image")
def dimg(did: int, c=Depends(ctx)): return _img(did, c["workspace_id"], "diffs", "path", "id")

class Prof(BaseModel): name: str = ""; description: str = ""; features: str = ""
@app.put(P + "/product-profile")
def put_prof(b: Prof, c=Depends(writer)):
    ex("INSERT INTO profiles VALUES(?,?,?,?) ON CONFLICT(workspace_id) DO UPDATE SET name=excluded.name, description=excluded.description, features=excluded.features", (c["workspace_id"], b.name, b.description, b.features))
    return {"ok": True}
@app.get(P + "/product-profile")
def get_prof(c=Depends(ctx)): return (q("SELECT * FROM profiles WHERE workspace_id=?", (c["workspace_id"],)) or [{}])[0]

@app.post(P + "/reports")
def mk_report(c=Depends(writer)):
    md = build_markdown(c["workspace_id"])
    return {"id": ex("INSERT INTO reports(workspace_id,title,markdown,created_at) VALUES(?,?,?,?)", (c["workspace_id"], "Competitive Intelligence Report", md, dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")))}
@app.get(P + "/reports")
def list_reports(c=Depends(ctx)): return q("SELECT id,title,created_at FROM reports WHERE workspace_id=? ORDER BY id DESC", (c["workspace_id"],))
def _rep(rid, ws):
    r = q("SELECT * FROM reports WHERE id=? AND workspace_id=?", (rid, ws))
    if not r: raise HTTPException(404, "Report not found")
    return r[0]
@app.get(P + "/reports/{rid}/markdown")
def rep_md(rid: int, c=Depends(ctx)): return Response(_rep(rid, c["workspace_id"])["markdown"], media_type="text/markdown")
@app.get(P + "/reports/{rid}/pdf")
def rep_pdf(rid: int, c=Depends(ctx)):
    r = _rep(rid, c["workspace_id"]); out = data_dir() / f"report_{rid}.pdf"
    imgs = [d["path"] for d in q("SELECT path FROM diffs WHERE workspace_id=? ORDER BY id DESC LIMIT 1", (c["workspace_id"],))]
    markdown_to_pdf(r["markdown"], str(out), imgs)
    return FileResponse(out, media_type="application/pdf", filename=f"report_{rid}.pdf")

from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="static")
