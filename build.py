"""Scrape IPO Watch's GMP table, keep GMP history, and render static pages.

Usage:
    python build.py            # fetch live data, update data/, write index.html
    python build.py --debug    # fetch and print what the parser sees (no files written)
    python build.py --html F   # parse a saved HTML file instead of fetching
"""
import argparse
import html
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).parent
SOURCE = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
HISTORY_FILE = ROOT / "data" / "history.json"
IPOS_FILE = ROOT / "data" / "ipos.json"
OUT_FILE = ROOT / "index.html"
HISTORY_PAGE = ROOT / "history.html"
ARCHIVE_FILE = ROOT / "data" / "archive.json"
IST = timezone(timedelta(hours=5, minutes=30))
MAX_HISTORY = 60
MAX_ARCHIVE = 200


# ---------- fetch ----------
def fetch(url=SOURCE):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
                      "Accept": "text/html"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


# ---------- parse ----------
class TableParser(HTMLParser):
    """Collects every <table> as a list of rows; each cell is (text, first_href)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._rows, self._row, self._cell = [], None, None, None
        self._depth = 0
        self.headings = []      # heading text preceding each kept table
        self._last_heading, self._in_heading = "", None

    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._depth == 0:
            self._in_heading = []
        if tag == "table":
            self._depth += 1
            if self._depth == 1:
                self._rows = []
        elif self._rows is not None and self._depth == 1:
            if tag == "tr":
                self._row = []
            elif tag in ("td", "th") and self._row is not None:
                self._cell = {"text": [], "href": None}
            elif tag == "a" and self._cell is not None and not self._cell["href"]:
                self._cell["href"] = dict(attrs).get("href")

    def handle_endtag(self, tag):
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._in_heading is not None:
            text = re.sub(r"\s+", " ", "".join(self._in_heading)).strip()
            if text:
                self._last_heading = text
            self._in_heading = None
        if tag == "table":
            if self._depth == 1 and self._rows is not None:
                if len(self._rows) > 1:
                    self.tables.append(self._rows)
                    self.headings.append(self._last_heading)
                self._rows = None
            self._depth = max(0, self._depth - 1)
        elif self._rows is not None and self._depth == 1:
            if tag in ("td", "th") and self._cell is not None and self._row is not None:
                text = re.sub(r"\s+", " ", "".join(self._cell["text"]).replace("\xa0", " ")).strip()
                self._row.append((text, self._cell["href"]))
                self._cell = None
            elif tag == "tr" and self._row is not None:
                if self._row:
                    self._rows.append(self._row)
                self._row = None

    def handle_data(self, data):
        if self._in_heading is not None:
            self._in_heading.append(data)
        if self._cell is not None:
            self._cell["text"].append(data)


def number(s):
    """'-₹5', '₹1,250.5 (12%)' -> -5.0, 1250.5 ; None if there is no number."""
    if not s:
        return None
    s = re.sub(r"\(.*?\)", "", s.replace(",", ""))
    m = re.search(r"(-|−|–)?\s*₹?\s*(\d+(?:\.\d+)?)", s)
    if not m:
        return None
    return (-1 if m.group(1) else 1) * float(m.group(2))


def clean_name(name):
    name = re.sub(r"\b(IPO|GMP)\b", "", name, flags=re.I)
    return re.sub(r"\s+", " ", name).strip(" -–:") or name


def key_of(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def table_to_ipos(rows, heading=""):
    head = [c[0].lower() for c in rows[0]]

    def find(pattern):
        return next((i for i, h in enumerate(head) if re.search(pattern, h)), -1)

    col = dict(name=find(r"ipo|company|name"), gmp=find(r"gmp|premium"), price=find(r"price|band"),
               est=find(r"est|listing"), date=find(r"date"), status=find(r"status"), size=find(r"size|issue"))
    if col["name"] < 0 or col["gmp"] < 0:
        return []

    def cell(r, i):
        return r[i][0] if 0 <= i < len(r) else ""

    out = []
    for r in rows[1:]:
        raw_name = cell(r, col["name"])
        if not raw_name or len(r) < 3:
            continue
        gmp_text = cell(r, col["gmp"])
        price_text = cell(r, col["price"])
        est_text = cell(r, col["est"])
        prices = [float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", price_text)]
        upper = max(prices) if prices else None
        gmp = number(gmp_text)
        gain = None
        m = re.search(r"(-?\d+(?:\.\d+)?)\s*%", est_text) or re.search(r"(-?\d+(?:\.\d+)?)\s*%", gmp_text)
        if m:
            gain = float(m.group(1))
        elif gmp is not None and upper:
            gain = round(gmp / upper * 100, 2)
        out.append(dict(
            name=clean_name(raw_name),
            sme=bool(re.search(r"\bsme\b", heading + " " + raw_name, re.I)),
            gmp=gmp, gain=gain, price=upper, price_text=price_text,
            est_price=number(re.sub(r"\(.*?\)", "", est_text)),
            dates=cell(r, col["date"]), status=cell(r, col["status"]), size=cell(r, col["size"]),
            url=r[col["name"]][1]))
    return out


def parse(page):
    p = TableParser()
    p.feed(page)
    p.close()
    return p.tables, [i for t, h in zip(p.tables, p.headings) for i in table_to_ipos(t, h)]


# ---------- history ----------
def update_history(ipos, now):
    hist = json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else {}
    stamp = now.strftime("%Y-%m-%d %H:%M")
    for i in ipos:
        if i["gmp"] is None:
            continue
        h = hist.setdefault(key_of(i["name"]), [])
        if not h or h[-1][1] != i["gmp"]:
            h.append([stamp, i["gmp"]])
            del h[:-MAX_HISTORY]
    return hist


# ---------- apply-by date and verdict ----------
MONTHS = {m: n for n, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def parse_end(dates, today):
    """'28-5 Oct' -> date(…, 10, 5); '30 Sep - 5 Oct' also works. None if unreadable."""
    m = re.search(r"(\d{1,2})\s*([A-Za-z]{3})[A-Za-z]*\s*$", dates.strip())
    if not m or m.group(2).lower() not in MONTHS:
        return None
    day, month = int(m.group(1)), MONTHS[m.group(2).lower()]
    for year in (today.year, today.year + 1, today.year - 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if abs((d - today).days) <= 180:
            return d
    return None


def is_closed(i, today):
    end = parse_end(i["dates"], today)
    return bool(re.search(r"clos|list|allot", i["status"], re.I)) or (end is not None and end < today)


def verdict(i, today):
    """Rule of thumb, not advice: Apply / Don't apply / Ignore, plus a short reason."""
    if is_closed(i, today):
        return "Closed", "bidding is over"
    g = i["gain"]
    if g is None or i["gmp"] is None:
        return "Ignore", "no GMP yet"
    need = 15 if i["sme"] else 10
    if g >= need:
        return "Apply", f"GMP gain {g:g}% is at least {need}%"
    if g < 0:
        return "Don't apply", "GMP is negative"
    if g < 3:
        return "Don't apply", f"GMP gain only {g:g}%"
    return "Ignore", f"GMP gain {g:g}% is below the {need}% bar"


# ---------- archive of closed IPOs ----------
def update_archive(ipos, now):
    """Keep every IPO we have seen close, so the History page outlives the source's own list."""
    arch = json.loads(ARCHIVE_FILE.read_text()) if ARCHIVE_FILE.exists() else {}
    today = now.date()
    for i in ipos:
        if is_closed(i, today):
            end = parse_end(i["dates"], today)
            arch[key_of(i["name"])] = {**i, "end": end.isoformat() if end else None}
    return dict(sorted(arch.items(), key=lambda kv: kv[1]["end"] or "", reverse=True)[:MAX_ARCHIVE])


# ---------- detail arithmetic ----------
ILLUSTRATIVE = 15000   # ₹ invested in the worked example (illustrative, not the real lot size)
BROKERS = [("Groww", "https://groww.in/ipo"), ("Zerodha", "https://zerodha.com/ipo/")]


def bar_for(i):
    return 15 if i["sme"] else 10


def money(v):
    return f"₹{v:,.2f}".rstrip("0").rstrip(".")


def arithmetic(i):
    """Worked numbers behind the row, as a list of (label, value). Only uses figures we actually have."""
    rows, p, g = [], i["price"], i["gmp"]
    if p:
        rows.append(("Issue price (top of band)", money(p)))
    if g is not None:
        rows.append(("GMP per share", f"{'+' if g > 0 else ''}{money(g)}"))
    if p and g is not None:
        rows.append(("Estimated listing price", f"{money(p)} {'+' if g >= 0 else '−'} {money(abs(g))} = {money(p + g)}"))
        gain = g / p * 100
        rows.append(("Expected gain", f"{money(g)} ÷ {money(p)} × 100 = {gain:.2f}%"))
        shares = int(ILLUSTRATIVE // p)
        if shares:
            invested = shares * p
            rows.append((f"If you invest about {money(ILLUSTRATIVE)}",
                         f"{shares} shares × {money(p)} = {money(invested)}"))
            rows.append(("Estimated profit / loss", f"{shares} × {money(g)} = {'+' if g >= 0 else '−'}{money(abs(shares * g))}"
                         f" ({gain:+.2f}% on {money(invested)})"))
        need = bar_for(i)
        rows.append((f"GMP needed for ‘Apply’ ({need}%)",
                     f"{money(p)} × {need}% = {money(p * need / 100)} (now {gain - need:+.2f} pts vs the bar)"))
    return rows


def trend_stats(h):
    """First/last/high/low GMP and the change between updates, from our saved snapshots."""
    if not h:
        return []
    vals = [v for _, v in h]
    rows = [("GMP now", money(vals[-1])), ("Updates tracked", str(len(vals)))]
    if len(vals) > 1:
        rows += [(f"First seen ({h[0][0][:10]})", money(vals[0])),
                 ("Change since first seen", f"{vals[-1] - vals[0]:+g}"),
                 ("High / low", f"{money(max(vals))} / {money(min(vals))}"),
                 ("Last move", f"{vals[-1] - vals[-2]:+g}")]
    return rows


def kv(rows):
    e = html.escape
    return "<table class='kv'>" + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows) + "</table>"


def history_table(h):
    if not h:
        return '<div class="mut">No history yet. It builds up with every update.</div>'
    lines, prev = [], None
    for t, v in h[-12:]:
        ch = "" if prev is None else f"{v - prev:+g}"
        lines.append(f"<tr><td>{html.escape(t)}</td><td>{money(v)}</td><td class='{color(v - prev if prev is not None else 0)}'>{ch}</td></tr>")
        prev = v
    return "<table class='kv'><tr><th>When (IST)</th><th>GMP</th><th>Change</th></tr>" + "".join(lines) + "</table>"


# ---------- render ----------
CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#111;--mut:#777;--line:#eee;--up:#0a8f4d;--down:#d0312d}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#999;--line:#2a2a2a;--up:#3ddc84;--down:#ff6b66}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}h1{font-size:18px;margin:0 0 4px}h2{font-size:13px;color:var(--mut);
font-weight:500;margin:22px 0 4px;text-transform:uppercase;letter-spacing:.05em}
table{width:100%;border-collapse:collapse}
.grid{display:grid;grid-template-columns:minmax(0,2fr) 1.3fr .6fr .9fr .9fr 1fr;gap:4px;align-items:baseline;padding:10px 6px}
.grid.g5{grid-template-columns:minmax(0,2fr) 1.3fr .6fr .9fr .9fr}
.grid>*:not(:first-child){text-align:right;white-space:nowrap}
.head{color:var(--mut);font-size:12px;padding:6px}
details.ipo{border-top:1px solid var(--line)}summary{cursor:pointer;list-style:none}summary::-webkit-details-marker{display:none}
summary .name::before{content:"▸ ";color:var(--mut)}details[open] summary .name::before{content:"▾ "}
.up{color:var(--up)}.down{color:var(--down)}.mut{color:var(--mut);font-size:12px}a{color:inherit}
.det{font-size:13px;padding:2px 6px 14px 20px;white-space:normal;text-align:left;max-width:520px}.det h3{font-size:12px;color:var(--mut);margin:12px 0 2px;
text-transform:uppercase;letter-spacing:.05em}.kv td,.kv th{padding:3px 4px;border:0;text-align:left;white-space:normal;font-size:13px;vertical-align:top}
.kv td:first-child{width:45%}.kv td:last-child,.kv th:last-child{text-align:right}.nav{display:flex;gap:14px;margin:8px 0 0;flex-wrap:wrap}
.nav a{text-decoration:none;color:var(--mut)}.nav a.on{color:var(--fg);border-bottom:2px solid var(--fg)}
.btn{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:4px 10px;margin:4px 6px 0 0;text-decoration:none}
.apply{margin:14px 0 0}
"""


def sign(v, suffix=""):
    if v is None:
        return "–"
    return f"{v:+g}{suffix}" if suffix and v else f"{v:g}{suffix}"


def color(v):
    return "up" if v and v > 0 else "down" if v and v < 0 else ""


def sparkline(h):
    if len(h) < 2:
        return '<span class="mut">–</span>'
    vals = [v for _, v in h[-15:]]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    pts = " ".join(f"{i / (len(vals) - 1) * 50:.1f},{14 - (v - lo) / span * 12:.1f}" for i, v in enumerate(vals))
    d = vals[-1] - vals[-2]
    c = "var(--up)" if d > 0 else "var(--down)" if d < 0 else "var(--mut)"
    arrow = "▲" if d > 0 else "▼" if d < 0 else "–"
    return (f'<svg width="50" height="16"><polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.5"/></svg> '
            f'<span class="{color(d)}">{arrow}</span>')


def apply_by(i, today):
    end = parse_end(i["dates"], today)
    if end is None:
        return "–"
    left = (end - today).days
    note = "" if is_closed(i, today) else " · today" if left == 0 else f" · {left}d"
    return f"{end.day} {end.strftime('%b')}{note}"


def broker_links(live):
    if not live:
        return ""
    return ("<div class='apply'>Apply: " + "".join(
        f'<a class="btn" href="{u}" target="_blank" rel="noopener">{n} ↗</a>' for n, u in BROKERS) + "</div>")


def row(i, hist, today, live=True):
    e = html.escape
    h = hist.get(key_of(i["name"]), [])
    label, why = verdict(i, today)
    est = f"₹{i['est_price']:g}" if i["est_price"] is not None else "–"
    facts = [("Price band", i["price_text"] or "–"), ("Dates", i["dates"] or "–"), ("Status", i["status"] or "–")]
    if i["est_price"] is not None:
        facts.append(("Est. listing (IPO Watch)", est))
    if i["size"]:
        facts.append(("Issue size", i["size"]))
    link = f'<a href="{e(i["url"])}" target="_blank" rel="noopener">Full write-up on IPO Watch ↗</a>' if i["url"] else ""
    detail = (f'<div class="det"><h3>Advice</h3>{e(label)}: {e(why)}.'
              f'<h3>The arithmetic</h3>{kv(arithmetic(i))}'
              f'<h3>Trend</h3>{kv(trend_stats(h))}{history_table(h)}'
              f'<h3>Facts</h3>{kv(facts)}'
              f'<div class="mut">Illustrative only: real lot sizes differ, and brokerage, charges and tax are not included. '
              f'GMP is unofficial.</div>{broker_links(live)}<div style="margin-top:8px">{link}</div></div>')
    cls = {"Apply": "up", "Don't apply": "down"}.get(label, "mut")
    tail = f'<span class="{cls}"><b>{e(label)}</b></span>' if live else ""
    return (f'<details class="ipo"><summary class="grid{"" if live else " g5"}"><span class="name">{e(i["name"])}</span>'
            f'<span>{e(apply_by(i, today))}</span><span>{sign(i["gmp"])}</span>'
            f'<span class="{color(i["gain"])}"><b>{sign(i["gain"], "%")}</b></span><span>{sparkline(h)}</span>{tail}'
            f'</summary>{detail}</details>')


def page(title, active, body, now):
    def link(href, name, key):
        return f'<a href="{href}"{" class=on" if key == active else ""}>{name}</a>'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body><main>'
            f'<h1>IPO GMP</h1><div class="mut">Updated {now.strftime("%d %b %Y, %H:%M")} IST · tap an IPO for details</div>'
            f'<div class="nav">{link("index.html", "Open &amp; upcoming", "live")}{link("history.html", "Past IPOs", "past")}</div>'
            f'{body}<p class="mut">Source: <a href="{SOURCE}">IPO Watch</a>. GMP is unofficial and moves fast; '
            f'treat it as a rough signal only. Verdict is a simple rule (Apply: GMP gain ≥10%, ≥15% for SME; '
            f'Don\'t apply: negative or under 3%; Ignore: in between or no GMP), not financial advice.</p></main></body></html>')


def render(ipos, hist, now):
    """Main page: only IPOs you can still apply to."""
    today = now.date()
    live = [i for i in ipos if not is_closed(i, today)]

    def section(title, items):
        if not items:
            return ""
        items = sorted(items, key=lambda i: -(i["gain"] if i["gain"] is not None else -1e9))
        return (f"<h2>{title}</h2><div class='grid head'><span>IPO</span><span>Apply by</span><span>GMP ₹</span>"
                f"<span>Gain</span><span>Trend</span><span>Verdict</span></div>"
                f"{''.join(row(i, hist, today) for i in items)}")

    body = (broker_links(True) + section("Mainboard", [i for i in live if not i["sme"]])
            + section("SME", [i for i in live if i["sme"]]))
    if not live:
        body += "<p>No IPOs are open right now. See Past IPOs.</p>"
    return page("IPO GMP", "live", body, now)


def render_history(archive, hist, now):
    """Past IPOs page: closed ones, newest first (end date comes from the archive)."""
    today = now.date()
    items = list(archive.values())
    if not items:
        return page("Past IPOs", "past", "<p>Nothing here yet.</p>", now)
    rows = "".join(row(i, hist, today, live=False) for i in items)
    body = (f"<h2>Closed IPOs, last GMP we saw</h2><div class='grid g5 head'><span>IPO</span><span>Closed</span>"
            f"<span>GMP ₹</span><span>Gain</span><span>Trend</span></div>{rows}")
    return page("Past IPOs", "past", body, now)


# ---------- main ----------
def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--html", help="parse this saved HTML file instead of fetching")
    args = ap.parse_args(argv)

    page = Path(args.html).read_text() if args.html else fetch()
    tables, ipos = parse(page)
    if args.debug:
        pp = TableParser()
        pp.feed(page)
        print("headings before tables:", pp.headings)
        print("sme count:", sum(i["sme"] for i in ipos), "mainboard count:", sum(not i["sme"] for i in ipos))
        print(f"page bytes: {len(page)}  tables: {len(tables)}  ipos parsed: {len(ipos)}")
        for n, t in enumerate(tables):
            print(f"table {n}: {len(t)} rows, header = {[c[0] for c in t[0]]}")
            for r in t[1:3]:
                print("   ", [c[0] for c in r])
        for i in ipos[:5]:
            print(i)
        return 0 if ipos else 1
    if not ipos:
        print("ERROR: parsed 0 IPOs; keeping the previous site untouched", file=sys.stderr)
        return 1
    now = datetime.now(IST)
    hist = update_history(ipos, now)
    HISTORY_FILE.parent.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(hist, indent=1))
    IPOS_FILE.write_text(json.dumps(ipos, indent=1, ensure_ascii=False))
    archive = update_archive(ipos, now)
    ARCHIVE_FILE.write_text(json.dumps(archive, indent=1, ensure_ascii=False))
    OUT_FILE.write_text(render(ipos, hist, now))
    HISTORY_PAGE.write_text(render_history(archive, hist, now))
    print(f"wrote {OUT_FILE.name} and {HISTORY_PAGE.name}: {len(ipos)} IPOs, {len(archive)} archived")
    return 0


if __name__ == "__main__":
    sys.exit(main())
