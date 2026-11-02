import datetime as dt
from xml.sax.saxutils import escape
from .db import q

def build_markdown(ws, title="Competitive Intelligence Report"):
    ev = q("SELECT e.*, c.name AS cname, p.url FROM events e JOIN competitors c ON c.id=e.competitor_id JOIN pages p ON p.id=e.page_id WHERE e.workspace_id=? ORDER BY e.id", (ws,))
    prof = (q("SELECT * FROM profiles WHERE workspace_id=?", (ws,)) or [None])[0]
    by = lambda *t: [e for e in ev if e["event_type"] in t]
    price, feat = by("PRICE_INCREASE", "PRICE_DECREASE", "NEW_PLAN", "REMOVED_PLAN"), by("FEATURE_ADDED", "FEATURE_REMOVED_FROM_PAGE")
    fails, review = by("PAGE_UNAVAILABLE"), by("EXTRACTION_REVIEW_REQUIRED")
    L = [f"# {title}", "", f"Generated: {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC", "", "## Executive Summary", ""]
    L.append(f"- {len(ev)} change events recorded: {len(price)} pricing, {len(feat)} feature, {len(review)} needing review, {len(fails)} capture failures." if ev else "- No change events recorded yet. Only baselines exist.")
    L += ["", "## Pricing Changes", ""]
    L += [f"- **{e['cname']}** — {e['summary']} (observed {e['detected_at']}, source: {e['url']}, snapshots {e['prev_snapshot']}→{e['cur_snapshot']})" for e in price] or ["- None observed."]
    L += ["", "## Feature Changes", ""]
    L += [f"- **{e['cname']}** — {e['summary']} (source: {e['url']})" for e in feat] or ["- None observed."]
    L += ["", "## Visual Comparison", ""]
    d = q("SELECT * FROM diffs WHERE workspace_id=? ORDER BY id", (ws,))
    L += [f"- Snapshots {x['prev_snapshot']}→{x['cur_snapshot']}: {x['changed_pct']:.2f}% of pixels differ (a filtering signal, not a measure of importance)." for x in d] or ["- No screenshot comparisons available."]
    L += ["", "## Competitive Gap Analysis", ""]
    if not prof or not (prof["features"] or "").strip():
        L.append("- Add your product profile to enable gap analysis.")
    else:
        mine = [f.strip().lower() for f in prof["features"].splitlines() if f.strip()]
        seen = {}
        for r in q("SELECT s.page_id, p.features, p.plan_name FROM pricing p JOIN snapshots s ON s.id=p.snapshot_id WHERE p.workspace_id=? AND s.id IN (SELECT MAX(id) FROM snapshots WHERE status='OK' GROUP BY page_id)", (ws,)):
            import json
            for f in json.loads(r["features"]): seen.setdefault(f, r["plan_name"])
        gaps = [(f, pl) for f, pl in seen.items() if not any(m in f.lower() or f.lower() in m for m in mine)]
        L += [f"- Competitor lists \"{f}\" (plan: {pl}); your profile has no equivalent. Signal for investigation, not proof you need it." for f, pl in gaps] or ["- No unmatched competitor statements found."]
    L += ["", "## Recommended Follow-up", "", "- Verify each price change is not a promotion or regional variation.", "- Confirm which plan a new feature statement applies to.", "- Review events marked REVIEW_REQUIRED before acting."]
    L += ["", "## Sources and Limitations", "", "- Rule-based report. No AI model was used; every statement comes from stored snapshots.",
          "- Absence of a feature on a page does not prove it is unavailable.", "- Visual diffs can include rendering noise."]
    L += [f"- Capture failure: {e['url']} — {e['summary']}" for e in fails]
    return "\n".join(L)

def markdown_to_pdf(md, path, image_paths=()):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
    st = getSampleStyleSheet(); doc = SimpleDocTemplate(path, pagesize=A4, title="Competitive Intelligence Report")
    out = []
    for line in md.splitlines():
        t = escape(line)
        while "**" in t and t.count("**") >= 2:
            t = t.replace("**", "<b>", 1).replace("**", "</b>", 1)
        if line.startswith("# "): out.append(Paragraph(escape(line[2:]), st["Title"]))
        elif line.startswith("## "): out += [Spacer(1, 8), Paragraph(escape(line[3:]), st["Heading2"])]
        elif line.startswith("- "): out.append(Paragraph("• " + t[2:], st["BodyText"]))
        elif line.strip(): out.append(Paragraph(t, st["BodyText"]))
    for p in image_paths:
        try: out += [Spacer(1, 8), Image(p, width=400, height=250, kind="proportional")]
        except Exception: pass
    def pg(c, d): c.setFont("Helvetica", 8); c.drawString(300, 20, f"Page {d.page}")
    doc.build(out, onFirstPage=pg, onLaterPages=pg)
