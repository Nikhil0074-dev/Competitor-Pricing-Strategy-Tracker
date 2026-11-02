"""Extraction (pricing, features, text) and change detection. Pure functions, no I/O."""
import hashlib, re
from decimal import Decimal, InvalidOperation
from bs4 import BeautifulSoup

PRICE_RE = re.compile(
    r"(?P<cur>[$€£₹])\s?(?P<amt>\d[\d,]*(?:\.\d+)?)\s*(?:/|per)?\s*"
    r"(?:(?P<basis>user|seat)\s*/?\s*)?(?P<int>month|mo|year|yr|annum)?", re.I)
CUR = {"$": "USD", "€": "EUR", "£": "GBP", "₹": "INR"}
INTERVAL = {"month": "month", "mo": "month", "year": "year", "yr": "year", "annum": "year"}

def norm_name(s): return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def parse_price(text):
    """Return normalized price fields. Unknown stays None; never guessed."""
    t = " ".join(text.split())
    m = PRICE_RE.search(t)
    if m:
        try: amt = Decimal(m["amt"].replace(",", ""))
        except InvalidOperation: amt = None
        return dict(amount=str(amt) if amt is not None else None, currency=CUR[m["cur"]],
                    billing_interval=INTERVAL.get((m["int"] or "").lower()),
                    billing_basis=(m["basis"] or "unknown").lower(), displayed_price=m.group(0).strip(),
                    status="OK" if amt is not None else "REVIEW_REQUIRED")
    if re.search(r"\bfree\b", t, re.I):
        return dict(amount="0", currency=None, billing_interval=None, billing_basis="unknown",
                    displayed_price="Free", status="OK")
    if re.search(r"contact (sales|us)|custom", t, re.I):
        return dict(amount=None, currency=None, billing_interval=None, billing_basis="unknown",
                    displayed_price="Custom pricing", status="CUSTOM")
    return dict(amount=None, currency=None, billing_interval=None, billing_basis="unknown",
                displayed_price=None, status="REVIEW_REQUIRED")

def parse_page(html):
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript"]): t.decompose()
    text = " ".join(soup.get_text(" ").split())
    cands = [e for e in soup.select('[class*="plan"], [class*="tier"]') if e.find(["h2", "h3", "h4"])]
    cands = [e for e in cands if not any(o is not e and e in o.parents for o in cands)]
    plans = []
    for e in cands:
        name = e.find(["h2", "h3", "h4"]).get_text(" ", strip=True)
        p = parse_price(e.get_text(" ", strip=True))
        p.update(plan_name=name, normalized_plan_name=norm_name(name),
                 features=[li.get_text(" ", strip=True) for li in e.find_all("li")])
        plans.append(p)
    return dict(text=text, plans=plans, hash=hashlib.sha256(text.encode()).hexdigest())

def pct_change(old, new):
    try:
        o, n = Decimal(old), Decimal(new)
    except (InvalidOperation, TypeError):
        return None
    return None if o == 0 else float((n - o) / o * 100)

def _ev(t, sev, plan, prev, cur, pct, summary):
    return dict(event_type=t, severity=sev, plan=plan, previous=prev, current=cur, pct=pct, summary=summary)

def detect_changes(old_plans, new_plans):
    """Compare plans by normalized name (never by price similarity)."""
    ev = []
    old = {p["normalized_plan_name"]: p for p in old_plans}
    new = {p["normalized_plan_name"]: p for p in new_plans}
    for k, n in new.items():
        o, nm = old.get(k), n["plan_name"]
        if o is None:
            ev.append(_ev("NEW_PLAN", "HIGH", nm, None, n["displayed_price"], None,
                          f"New plan '{nm}' appeared ({n['displayed_price'] or 'price not shown'})."))
            continue
        diff_basis = next((f for f in ("currency", "billing_interval", "billing_basis") if o[f] != n[f]
                           and o["amount"] is not None and n["amount"] is not None), None)
        if diff_basis:
            ev.append(_ev("EXTRACTION_REVIEW_REQUIRED", "MEDIUM", nm, o["displayed_price"], n["displayed_price"], None,
                          f"'{nm}': {diff_basis} changed ({o[diff_basis]} -> {n[diff_basis]}). Percentage not computed; review needed."))
        elif o["amount"] != n["amount"]:
            if o["amount"] is None or n["amount"] is None:
                ev.append(_ev("EXTRACTION_REVIEW_REQUIRED", "MEDIUM", nm, o["displayed_price"], n["displayed_price"], None,
                              f"'{nm}' price became non-numeric or missing. Review needed."))
            else:
                up = Decimal(n["amount"]) > Decimal(o["amount"])
                pc = pct_change(o["amount"], n["amount"])
                tail = f" ({pc:+.1f}%)." if pc is not None else " (percentage not defined for a zero old price)."
                ev.append(_ev("PRICE_INCREASE" if up else "PRICE_DECREASE", "HIGH", nm, o["displayed_price"], n["displayed_price"], pc,
                              f"'{nm}' displayed price {'rose' if up else 'fell'}: {o['displayed_price']} -> {n['displayed_price']}{tail}"))
        of, nf = set(o["features"]), set(n["features"])
        for f in sorted(nf - of):
            ev.append(_ev("FEATURE_ADDED", "MEDIUM", nm, None, f, None, f"Feature statement added to '{nm}': {f}"))
        for f in sorted(of - nf):
            ev.append(_ev("FEATURE_REMOVED_FROM_PAGE", "MEDIUM", nm, f, None, None,
                          f"Statement no longer shown for '{nm}': {f} (not proof the feature was discontinued)."))
    for k, o in old.items():
        if k not in new:
            ev.append(_ev("REMOVED_PLAN", "HIGH", o["plan_name"], o["displayed_price"], None, None,
                          f"Plan '{o['plan_name']}' is no longer shown on the page."))
    return ev
