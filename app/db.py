import os, sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE, pw TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER);
CREATE TABLE IF NOT EXISTS workspaces(id INTEGER PRIMARY KEY, name TEXT);
CREATE TABLE IF NOT EXISTS members(user_id INTEGER, workspace_id INTEGER, role TEXT);
CREATE TABLE IF NOT EXISTS competitors(id INTEGER PRIMARY KEY, workspace_id INTEGER, name TEXT, website_url TEXT, notes TEXT, status TEXT DEFAULT 'ACTIVE');
CREATE TABLE IF NOT EXISTS pages(id INTEGER PRIMARY KEY, workspace_id INTEGER, competitor_id INTEGER, url TEXT, page_type TEXT, interval_minutes INTEGER DEFAULT 1440, is_active INTEGER DEFAULT 1, last_checked_at TEXT, last_success_at TEXT);
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, workspace_id INTEGER, page_id INTEGER, captured_at TEXT, http_status INTEGER, content_hash TEXT, text TEXT, shot TEXT, status TEXT, error_code TEXT);
CREATE TABLE IF NOT EXISTS pricing(id INTEGER PRIMARY KEY, workspace_id INTEGER, snapshot_id INTEGER, plan_name TEXT, norm_name TEXT, displayed_price TEXT, amount TEXT, currency TEXT, billing_interval TEXT, billing_basis TEXT, status TEXT, features TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, workspace_id INTEGER, competitor_id INTEGER, page_id INTEGER, prev_snapshot INTEGER, cur_snapshot INTEGER, event_type TEXT, plan TEXT, previous TEXT, current TEXT, pct REAL, summary TEXT, severity TEXT, review_status TEXT DEFAULT 'PENDING', detected_at TEXT);
CREATE TABLE IF NOT EXISTS diffs(id INTEGER PRIMARY KEY, workspace_id INTEGER, prev_snapshot INTEGER, cur_snapshot INTEGER, path TEXT, changed_pct REAL);
CREATE TABLE IF NOT EXISTS profiles(workspace_id INTEGER PRIMARY KEY, name TEXT, description TEXT, features TEXT);
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY, workspace_id INTEGER, title TEXT, markdown TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, workspace_id INTEGER, page_id INTEGER, status TEXT, error_code TEXT, started_at TEXT, completed_at TEXT);
CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(page_id, captured_at);
CREATE INDEX IF NOT EXISTS ix_ev ON events(workspace_id, detected_at);
"""

def data_dir():
    d = Path(os.environ.get("DATA_DIR", "data")); (d / "shots").mkdir(parents=True, exist_ok=True); return d

def conn():
    c = sqlite3.connect(data_dir() / "tracker.db"); c.row_factory = sqlite3.Row; c.executescript(SCHEMA); return c

def q(sql, args=()):
    with conn() as c: return [dict(r) for r in c.execute(sql, args).fetchall()]

def ex(sql, args=()):
    c = conn()
    try:
        with c: return c.execute(sql, args).lastrowid
    finally: c.close()
