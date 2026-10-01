"""Per-IPO detail pages: parse the tables on them and turn the numbers into a financial analysis.

Everything here works on already-parsed tables (lists of rows of (text, href)), so it is testable offline.
"""
import re
from datetime import date, datetime
from statistics import median

FD_RATE = 7.0           # % p.a., the yardstick "safe alternative" for money blocked during an IPO
SCENARIO_ODDS = (1, 5, 20, 50)


def num(s):
    """'₹14,950' -> 14950.0, '15.37 %' -> 15.37, '-₹3.2' -> -3.2; None for '-', '–', '-%', 'N/A', ''."""
    if s is None:
        return None
    m = re.search(r"-?\s*\d[\d,]*(?:\.\d+)?", str(s).replace("₹", ""))
    if not m:
        return None
    return float(m.group().replace(",", "").replace(" ", ""))


def parse_date(s):
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d,%Y", "%d %B %Y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except (ValueError, AttributeError):
            pass
    return None


def parse_tables(tables):
    """Pick the useful tables out of an IPO page by their header text."""
    d, kv = {}, {}
    for rows in tables:
        head = [c[0].lower() for c in rows[0]]
        first = head[0] if head else ""
        if first.startswith("purpose"):
            d["purposes"] = [{"text": r[0][0], "crore": num(r[1][0])} for r in rows[1:] if len(r) >= 2]
        elif first.startswith("application") and any("lot" in h for h in head):
            for r in rows[1:]:
                if r[0][0].lower().startswith("retail min") and len(r) >= 4:
                    d["lot"] = {"lots": num(r[1][0]), "shares": num(r[2][0]), "amount": num(r[3][0])}
        elif first.startswith("investor category"):
            cats = {}
            for r in rows[1:]:
                name = r[0][0].lower()
                key = "anchor" if "anchor" in name else "qib" if "qib" in name else "nii" if "nii" in name \
                    else "retail" if "retail" in name else None
                if key and len(r) >= 3:
                    cats[key] = {"shares": num(r[1][0]), "pct": num(r[2][0])}
            d["categories"] = cats
        elif first.startswith("particular") and len(head) >= 5 and "pre" in head[1]:
            for r in rows[1:]:
                if r[0][0].lower().startswith("promoter") and len(r) >= 5:
                    d["promoter"] = {"pre": num(r[2][0]), "post": num(r[4][0])}
        elif first.startswith("period"):
            d["financials"] = [{"period": r[0][0], "revenue": num(r[1][0]), "expense": num(r[2][0]),
                                "pat": num(r[3][0]), "assets": num(r[4][0])} for r in rows[1:] if len(r) >= 5]
        elif any(re.search(r"p/e|pe ratio", h) for h in head) and any("company" in h for h in head):
            pe_i = next(i for i, h in enumerate(head) if re.search(r"p/e|pe ratio", h))
            peers = []
            for r in rows[1:]:
                if len(r) > pe_i and num(r[pe_i][0]) is not None:
                    peers.append({"name": r[0][0], "pe": num(r[pe_i][0])})
            d["peers"] = peers
        elif all(len(r) == 2 for r in rows):                     # key / value tables: details, timeline, KPIs
            for r in rows:
                kv[r[0][0].lower().strip(" :")] = r[1][0]
    d["kpi"] = {k: num(kv.get(src)) for k, src in {
        "roe": "roe", "roce": "roce", "ebitda_margin": "ebitda margin", "pat_margin": "pat margin",
        "de": "debt to equity ratio", "eps": "earning per share (eps)", "ronw": "return on net worth (ronw)",
        "nav": "net asset value (nav)"}.items() if kv.get(src) is not None}
    d["issue"] = {k: kv[k] for k in ("issue size", "fresh issue", "offer for sale", "issue type", "ipo listing") if k in kv}
    d["dates"] = {"allotment": parse_date(kv.get("basis of allotment", "")), "refund": parse_date(kv.get("refunds", "")),
                  "listing": parse_date(kv.get("ipo listing date", ""))}
    d["dates"] = {k: v.isoformat() for k, v in d["dates"].items() if v}
    return d


def matches(i, d):
    """True unless this page clearly belongs to another IPO: lot value ÷ shares must equal the issue price.
    (IPO Watch occasionally links one IPO to another's page; showing that data would be wrong.)"""
    lot = (d or {}).get("lot") or {}
    price = i.get("price")
    if not (lot.get("amount") and lot.get("shares") and price):
        return True                                   # nothing to compare, accept
    return abs(lot["amount"] / lot["shares"] - price) / price < 0.01


# ---------- analysis ----------
def _pct(v):
    return f"{v:+.1f}%"


def _inr(v):
    return f"₹{v:,.0f}" if abs(v) >= 100 else f"₹{v:,.2f}"


def _cagr(first, last, years):
    if first and first > 0 and last and last > 0 and years > 0:
        return ((last / first) ** (1 / years) - 1) * 100
    return None


def analyse(i, d, close, today):
    """Financial read of one IPO. Returns {sections, flags, positives, quality, bottom, has_details}.
    i: parsed row (price, gmp, gain, sme, name). d: parse_tables() output or None. close: last bidding date."""
    price, gmp = i.get("price"), i.get("gmp")
    if d and not matches(i, d):
        d = None
    out = {"sections": [], "scenarios": [], "odds": [], "flags": [], "positives": [], "quality": None,
           "bottom": "", "has_details": bool(d)}
    d = d or {}
    flags, pos = out["flags"], out["positives"]

    # --- 1. what one application means ---------------------------------------------------------
    lot = d.get("lot") or {}
    amount, shares = lot.get("amount"), lot.get("shares")
    if amount and shares and gmp is not None and price:
        pnl = shares * gmp
        rows = [("Minimum application", f"{int(lot['lots'])} lot{'s' if lot['lots'] != 1 else ''} = {int(shares):,} shares = {_inr(amount)}"),
                ("Profit/loss if it lists at today's GMP", f"{'+' if pnl >= 0 else '−'}{_inr(abs(pnl))} ({gmp / price * 100:+.2f}%)")]
        dates = d.get("dates", {})
        free = parse_date_iso(dates.get("refund")) or parse_date_iso(dates.get("listing"))
        if free and close and free > close:
            days = (free - close).days
            ann = gmp / price * 100 * 365 / days
            fd = amount * FD_RATE / 100 * days / 365
            rows += [("Money blocked", f"{days} days (bid closes {close:%d %b}, refund/listing {free:%d %b})"),
                     ("Return if GMP holds, annualised", f"{ann:,.0f}% a year (short-term rate, not repeatable)" if abs(ann) < 1e5 else "very high"),
                     (f"Same money in a {FD_RATE:g}% fixed deposit", f"{_inr(fd)} over {days} days"),
                     ("GMP profit beats the deposit by", f"{'+' if pnl - fd >= 0 else '−'}{_inr(abs(pnl - fd))}")]
        out["sections"].append(("What one application means", rows))
        for label, delta in (("Lists at today's GMP", gmp), ("Lists at half the GMP", gmp / 2),
                             ("Lists flat at the issue price", 0.0), ("Lists 10% below the issue price", -0.10 * price)):
            out["scenarios"].append((label, shares * delta, delta / price * 100))
        cats = d.get("categories", {})
        retail = cats.get("retail", {}).get("shares")
        if retail:
            lots_avail = retail / shares
            rows2 = [("Retail quota", f"{int(retail):,} shares = about {int(lots_avail):,} one-lot applications at 1× subscription")]
            out["sections"].append(("Allotment odds", rows2))
            for n in SCENARIO_ODDS:
                out["odds"].append((n, 1 / n, pnl / n))
    elif gmp is not None and price:
        out["sections"].append(("What one application means", [(
            "Lot size", "not available yet, so rupee figures per application can't be shown")]))

    # --- 2. valuation ---------------------------------------------------------------------------
    kpi = d.get("kpi", {})
    rows, eps, nav, val_score = [], kpi.get("eps"), kpi.get("nav"), 0
    if price and eps and eps > 0:
        pe = price / eps
        rows.append(("Price ÷ earnings at the issue price", f"{pe:.1f}×  (EPS ₹{eps:g})"))
        if gmp is not None:
            rows.append(("Price ÷ earnings at the estimated listing price", f"{(price + gmp) / eps:.1f}×"))
        peers = [p["pe"] for p in d.get("peers", []) if 0 < p["pe"] < 500]
        if peers:
            med = median(peers)
            prem = (pe / med - 1) * 100
            rows.append(("Listed peers' median P/E" if len(peers) > 1 else "Listed peer's P/E",
                         f"{med:.1f}×  ({len(peers)} peer{'s' if len(peers) != 1 else ''})"))
            rows.append(("Valuation vs peers", f"{abs(prem):.0f}% {'premium' if prem > 0 else 'discount'}"))
            # SME peers are usually far bigger listed companies, so a "discount" says little: only score mainboard
            val_score = 0 if i.get("sme") else -1 if prem > 30 else 1 if prem < -10 else 0
            if prem > 30:
                flags.append(f"Priced at {pe:.0f}× earnings, {prem:.0f}% above its listed peers' median ({med:.0f}×).")
            elif prem < -10:
                pos.append(f"Priced at {pe:.0f}× earnings, {abs(prem):.0f}% below its listed peers' median ({med:.0f}×).")
    elif eps is not None and eps <= 0:
        flags.append("Earnings per share is zero or negative, so a P/E can't be used.")
    if price and nav and nav > 0:
        rows.append(("Price ÷ book value (NAV ₹%g)" % nav, f"{price / nav:.1f}×"))
    if rows:
        out["sections"].append(("Valuation", rows))

    # --- 3. growth and profitability --------------------------------------------------------------
    fy = sorted([f for f in d.get("financials", []) if re.fullmatch(r"\D*\d{4}\D*", f["period"])
                 and f["revenue"] is not None], key=lambda f: int(re.search(r"\d{4}", f["period"]).group()))
    rows, score = [], val_score
    if len(fy) >= 2:
        yrs = len(fy) - 1
        rc = _cagr(fy[0]["revenue"], fy[-1]["revenue"], yrs)
        pc = _cagr(fy[0]["pat"], fy[-1]["pat"], yrs)
        rows.append(("Revenue", " → ".join(f"{f['revenue']:g}" for f in fy) + f"   (₹ cr as listed, {fy[0]['period']}–{fy[-1]['period']})"))
        rows.append(("Profit after tax", " → ".join("–" if f["pat"] is None else f"{f['pat']:g}" for f in fy)))
        if rc is not None:
            rows.append(("Revenue growth a year (CAGR)", f"{rc:.0f}%"))
            score += 1 if rc >= 15 else -1 if rc < 0 else 0
            if rc >= 25:
                pos.append(f"Revenue growing about {rc:.0f}% a year.")
        if pc is not None:
            rows.append(("Profit growth a year (CAGR)", f"{pc:.0f}%"))
            score += 1 if pc >= 20 else -1 if pc < 0 else 0
        last = fy[-1]
        if last["pat"] is not None and last["revenue"]:
            m = last["pat"] / last["revenue"] * 100
            rows.append(("Profit margin, latest year", f"{m:.1f}%"))
            if last["pat"] < 0:
                flags.append("The company made a loss in its latest year."); score -= 2
            elif m < 5:
                flags.append(f"Thin profit margin ({m:.1f}%); small cost shocks can wipe out profit.")
            elif m >= 12:
                pos.append(f"Healthy profit margin ({m:.1f}%)."); score += 1
    for key, label, good, bad in (("roe", "Return on equity", 15, 8), ("roce", "Return on capital employed", 15, 8)):
        v = kpi.get(key)
        if v is not None:
            rows.append((label, f"{v:.1f}%"))
            if key == "roe":
                score += 1 if v >= good else -1 if v < bad else 0
                if v >= 20:
                    pos.append(f"Strong return on equity ({v:.0f}%).")
    if kpi.get("de") is not None:
        rows.append(("Debt ÷ equity", f"{kpi['de']:.2f}"))
        if kpi["de"] > 2:
            flags.append(f"High debt (debt ÷ equity {kpi['de']:.1f})."); score -= 1
        elif kpi["de"] < 0.5:
            pos.append("Low debt."); score += 1
    if rows:
        out["sections"].append(("Growth and profitability", rows))

    # --- 4. where the money goes, who is selling --------------------------------------------------
    rows = []
    iss = d.get("issue", {})
    if iss.get("issue size"):
        rows.append(("Issue size", iss["issue size"].replace("Approx", "about").strip()))
    cats = d.get("categories", {})
    if cats:
        rows.append(("Split", " · ".join(f"{k.upper() if k in ('qib', 'nii') else k.title()} {v['pct']:g}%"
                                          for k, v in cats.items() if v.get("pct") is not None)))
    pur = [p for p in d.get("purposes", []) if p["crore"]]
    tot = sum(p["crore"] for p in pur)
    if pur and tot:
        for p in pur:
            rows.append((p["text"][:60], f"₹{p['crore']:g} cr ({p['crore'] / tot * 100:.0f}%)"))
        wc = sum(p["crore"] for p in pur if re.search(r"working capital|general corporate|repay|prepay", p["text"], re.I))
        if wc / tot > 0.6:
            flags.append(f"{wc / tot * 100:.0f}% of the money raised goes to working capital, debt repayment or general "
                         "purposes, not new capacity.")
    ofs = num(iss.get("offer for sale"))
    if ofs:
        rows.append(("Offer for sale (existing holders selling)", iss["offer for sale"].replace("Approx", "about")))
        fresh = num(iss.get("fresh issue")) or 0
        if ofs > fresh:
            flags.append("Most of the issue is an offer for sale: existing shareholders are selling, not the company raising money.")
    pm = d.get("promoter")
    if pm and pm.get("pre") and pm.get("post"):
        rows.append(("Promoter holding before → after", f"{pm['pre']:.1f}% → {pm['post']:.1f}%"))
        if pm["pre"] - pm["post"] > 20:
            flags.append(f"Promoter holding drops from {pm['pre']:.0f}% to {pm['post']:.0f}%.")
    if rows:
        out["sections"].append(("Issue structure", rows))

    # --- 5. GMP reliability and size risk ----------------------------------------------------------
    if i.get("sme"):
        flags.append("SME issue: thinner trading and bigger price swings after listing; GMP is less reliable.")
    if gmp is not None and price and gmp / price * 100 > 40:
        flags.append("A very high GMP can reverse quickly; do not assume it will hold until listing.")

    # --- 6. quality + bottom line ----------------------------------------------------------------
    if d.get("financials") or kpi:
        out["quality"] = "Strong" if score >= (4 if i.get("sme") else 3) else "Weak" if score <= -1 else "Mixed"
    q, g = out["quality"], i.get("gain")
    need = 15 if i.get("sme") else 10
    if g is None:
        out["bottom"] = "No GMP yet, so there is no listing-gain signal to weigh."
    elif g >= need and q == "Strong":
        out["bottom"] = "GMP and fundamentals agree: a good-looking listing gain on a business with solid numbers."
    elif g >= need and q in ("Weak",):
        out["bottom"] = "A listing-gain play only. The GMP is attractive but the fundamentals are weak, so plan to sell on listing rather than hold."
    elif g >= need:
        out["bottom"] = ("The GMP clears the bar" + ("; fundamentals are mixed, so treat it as a listing-gain trade."
                                                    if q == "Mixed" else "; fundamentals could not be checked."))
    elif g < 3:
        out["bottom"] = "There is little or no listing gain to expect" + (
            "; only apply for the long term if you like the business and price." if q == "Strong" else ".")
    else:
        out["bottom"] = "A modest GMP. It only makes sense if you like the business" + (
            " (the numbers look solid)." if q == "Strong" else " and price; the numbers alone don't make it compelling.")
    return out


def parse_date_iso(s):
    try:
        return date.fromisoformat(s) if s else None
    except ValueError:
        return None
