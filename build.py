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
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import charts
import details

ROOT = Path(__file__).parent
SOURCE = "https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/"
HISTORY_FILE = ROOT / "data" / "history.json"
IPOS_FILE = ROOT / "data" / "ipos.json"
OUT_FILE = ROOT / "index.html"
HISTORY_PAGE = ROOT / "history.html"
ARCHIVE_FILE = ROOT / "data" / "archive.json"
NEWS_FILE = ROOT / "data" / "news.json"
DETAILS_FILE = ROOT / "data" / "details.json"
NEWS_PAGE = ROOT / "news.html"
MAX_NEWS = 150
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


# ---------- per-IPO detail pages ----------
def update_details(ipos, archive, today, fetch_page=None, pause=0.4):
    """Fetch each open IPO's own page (lot size, financials, peers...). Failures keep the previous copy."""
    fetch_page = fetch_page or fetch
    store = json.loads(DETAILS_FILE.read_text()) if DETAILS_FILE.exists() else {}
    failed = []
    for i in ipos:
        if is_closed(i, today) or not i["url"]:
            continue
        try:
            tables, _ = parse(fetch_page(i["url"]))
            d = details.parse_tables(tables)
            if d.get("lot") or d.get("financials") or d.get("kpi"):
                store[key_of(i["name"])] = d
            else:
                failed.append(i["name"])
        except Exception as ex:                                  # one bad page must not break the build
            failed.append(f"{i['name']} ({ex})")
        time.sleep(pause)
    keep = {key_of(i["name"]) for i in ipos} | set(archive)
    return {k: v for k, v in store.items() if k in keep}, failed


# ---------- render helpers ----------
BROKERS = [("Groww", "https://groww.in/ipo"), ("Zerodha", "https://zerodha.com/ipo/")]


def bar_for(i):
    return 15 if i["sme"] else 10


def money(v):
    return f"₹{v:,.2f}".rstrip("0").rstrip(".")


def signed_money(v):
    return f"{'+' if v >= 0 else '−'}{money(abs(v))}"


def kv(rows):
    e = html.escape
    return "<table class='kv'>" + "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in rows) + "</table>"


def analysis_html(a):
    """The financial analysis panel for one IPO."""
    e, parts = html.escape, []
    if a["bottom"]:
        q = f" <span class='mut'>Fundamentals: {e(a['quality'])}</span>" if a["quality"] else ""
        parts.append(f"<p><b>{e(a['bottom'])}</b>{q}</p>")
    for title, rows in a["sections"]:
        parts.append(f"<h4>{e(title)}</h4>{kv(rows)}")
        if title == "What one application means" and a["scenarios"]:
            parts.append("<h4>If it lists at…</h4><table class='kv'><tr><th>Scenario</th><th>Profit / loss</th><th>Return</th></tr>"
                         + "".join(f"<tr><td>{e(lab)}</td><td class='{color(pl)}'>{e(signed_money(pl))}</td>"
                                   f"<td class='{color(pc)}'>{pc:+.1f}%</td></tr>" for lab, pl, pc in a["scenarios"]) + "</table>")
        if title == "Allotment odds" and a["odds"]:
            parts.append("<table class='kv'><tr><th>If retail demand is…</th><th>Chance of a lot</th><th>Expected profit</th></tr>"
                         + "".join(f"<tr><td>{n}× the quota</td><td>{'100%' if n == 1 else f'1 in {n}'}</td>"
                                   f"<td>{e(signed_money(ev))}</td></tr>" for n, _, ev in a["odds"]) + "</table>")
    if a["flags"]:
        parts.append("<h4>Watch out for</h4><ul class='fl'>" + "".join(f"<li>⚠ {e(x)}</li>" for x in a["flags"]) + "</ul>")
    if a["positives"]:
        parts.append("<h4>In its favour</h4><ul class='fl'>" + "".join(f"<li>✓ {e(x)}</li>" for x in a["positives"]) + "</ul>")
    if not a["has_details"]:
        parts.append("<p class='mut'>Company details (lot size, financials, peers) are not available for this IPO yet.</p>")
    parts.append(f"<div class='mut'>Assumes the minimum one-lot application, and a {details.FD_RATE:g}% fixed deposit as the "
                 "safe alternative. Revenue and profit are in ₹ crore as listed. Allotment is a lottery when oversubscribed. "
                 "Brokerage, charges and tax are not included. GMP is unofficial.</div>")
    return "".join(parts)


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
.det{font-size:13px;padding:2px 6px 14px 20px;white-space:normal;text-align:left;max-width:560px}
.det h3{font-size:12px;color:var(--mut);margin:14px 0 2px;text-transform:uppercase;letter-spacing:.05em}
.det h4{font-size:13px;margin:12px 0 2px}.det p{margin:6px 0}
.kv td,.kv th{padding:3px 4px;border:0;text-align:left;white-space:normal;font-size:13px;vertical-align:top}
.kv th{color:var(--mut);font-weight:500;font-size:12px}
.kv td:first-child{width:45%}.kv td:last-child,.kv th:last-child{text-align:right}.nav{display:flex;gap:14px;margin:8px 0 0;flex-wrap:wrap}
.nav a{text-decoration:none;color:var(--mut)}.nav a.on{color:var(--fg);border-bottom:2px solid var(--fg)}
.btn{display:inline-block;border:1px solid var(--line);border-radius:6px;padding:4px 10px;margin:4px 6px 0 0;text-decoration:none}
.apply{margin:14px 0 0}
ul{padding-left:18px;margin:4px 0}li{margin:6px 0}.feed{list-style:none;padding:0}.feed li{border-top:1px solid var(--line);padding:6px 0}
.fl{list-style:none;padding:0}.fl li{margin:3px 0}
.chart{width:100%;height:auto;display:block}.gl{stroke:var(--line);stroke-width:1}.zl{stroke:var(--mut);stroke-width:1}
.bl{stroke:var(--up);stroke-width:1;stroke-dasharray:5 4}.ln{stroke:var(--up);stroke-width:2.2}.ln.dn{stroke:var(--down)}
.pt{fill:var(--up)}.pt.dn{fill:var(--down)}.tx{fill:var(--mut);font-size:11px}.tx.v{fill:var(--fg)}
a.spark{text-decoration:none;display:inline-flex;align-items:center;gap:4px}.mini{vertical-align:middle}
a.zoom{display:block;text-decoration:none}.zoomhint{font-size:11px;color:var(--mut)}
.lb{display:none;position:fixed;inset:0;z-index:50;align-items:center;justify-content:center;padding:14px}
.lb:target{display:flex}.lb .bg{position:absolute;inset:0;background:rgba(0,0,0,.6)}
.lb .box{position:relative;background:var(--bg);border-radius:10px;padding:14px 16px;width:min(760px,100%);max-height:100%;overflow:auto}
.lb .x{float:right;text-decoration:none;color:var(--mut);font-size:13px}.lb h3{margin:0 0 6px;font-size:15px}
"""


def sign(v, suffix=""):
    if v is None:
        return "–"
    return f"{v:+g}{suffix}" if suffix and v else f"{v:g}{suffix}"


def color(v):
    return "up" if v and v > 0 else "down" if v and v < 0 else ""


def sparkline(h, k):
    """Row-sized graph; clicking it opens the full-size chart (pure CSS, :target)."""
    mv = h[-1][1] - h[-2][1] if len(h) >= 2 else 0
    arrow = f' <span class="{color(mv)}">{"▲" if mv > 0 else "▼" if mv < 0 else "–"}</span>' if len(h) >= 2 else ""
    return f'<a class="spark" href="#c-{k}" title="Click to enlarge">{charts.mini(h)}{arrow}</a>'


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


def lightbox(i, h, k):
    bar = i["price"] * bar_for(i) / 100 if i["price"] else None
    vals = [v for _, v in h]
    stats = (f"First reading {h[0][0][:10]}: ₹{vals[0]:g} · now ₹{vals[-1]:g} · high ₹{max(vals):g} · low ₹{min(vals):g} · "
             f"{len(vals)} readings") if vals else "No readings yet."
    note = "" if len(vals) > 1 else " More readings are added with every update (about four a day)."
    return (f'<div class="lb" id="c-{k}"><a class="bg" href="#!" aria-label="Close"></a><div class="box">'
            f'<a class="x" href="#!">✕ Close</a><h3>{html.escape(i["name"])}: GMP over time (₹ per share)</h3>'
            f'{charts.chart(h, bar, big=True)}<div class="mut">Dashed line: the GMP needed for an “Apply” '
            f'({bar_for(i)}% of the issue price). {html.escape(stats)}{note}</div></div></div>')


def row(i, hist, dets, today, live=True):
    e = html.escape
    k = key_of(i["name"])
    h = hist.get(k, [])
    label, why = verdict(i, today)
    a = details.analyse(i, dets.get(k), parse_end(i["dates"], today), today)
    facts = [("Price band", i["price_text"] or "–"), ("Dates", i["dates"] or "–"), ("Status", i["status"] or "–")]
    if i["est_price"] is not None:
        facts.append(("Estimated listing price", f"₹{i['est_price']:g}"))
    if i["size"]:
        facts.append(("Issue size", i["size"]))
    link = f'<a href="{e(i["url"])}" target="_blank" rel="noopener">More details ↗</a>' if i["url"] else ""
    tm = timing(i, h, today)
    tm_html = f"<br><b>{e(tm[0])}.</b> {e(tm[1])}" if tm else ""
    bar = i["price"] * bar_for(i) / 100 if i["price"] else None
    detail = (f'<div class="det"><h3>Advice</h3>{e(label)}: {e(why)}.{tm_html}'
              f'<h3>Financial analysis</h3>{analysis_html(a)}'
              f'<h3>GMP trend</h3><a class="zoom" href="#c-{k}" title="Click to enlarge">{charts.chart(h, bar, big=False)}</a>'
              f'<span class="zoomhint">Click the graph to enlarge it.</span>'
              f'<h3>Facts</h3>{kv(facts)}{broker_links(live)}<div style="margin-top:8px">{link}</div></div>')
    cls = {"Apply": "up", "Don't apply": "down"}.get(label, "mut")
    tail = f'<span class="{cls}"><b>{e(label)}</b></span>' if live else ""
    return (f'<details class="ipo"><summary class="grid{"" if live else " g5"}"><span class="name">{e(i["name"])}</span>'
            f'<span>{e(apply_by(i, today))}</span><span>{sign(i["gmp"])}</span>'
            f'<span class="{color(i["gain"])}"><b>{sign(i["gain"], "%")}</b></span><span>{sparkline(h, k)}</span>{tail}'
            f'</summary>{detail}</details>{lightbox(i, h, k)}')


def page(title, active, body, now, source=False):
    def link(href, name, key):
        return f'<a href="{href}"{" class=on" if key == active else ""}>{name}</a>'
    credit = f'Data: <a href="{SOURCE}">IPO Watch</a>. ' if source else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style></head><body><main>'
            f'<h1>IPO GMP</h1><div class="mut">Updated {now.strftime("%d %b %Y, %H:%M")} IST · tap an IPO for details</div>'
            f'<div class="nav">{link("index.html", "Open &amp; upcoming", "live")}{link("history.html", "Past IPOs", "past")}{link("news.html", "News &amp; advice", "news")}</div>'
            f'{body}<p class="mut">{credit}GMP is unofficial and moves fast; '
            f'treat it as a rough signal only. Verdict is a simple rule (Apply: GMP gain ≥10%, ≥15% for SME; '
            f'Don\'t apply: negative or under 3%; Ignore: in between or no GMP). None of this is financial advice.</p></main></body></html>')


def render(ipos, hist, now, dets=None):
    """Main page: only IPOs you can still apply to."""
    today, dets = now.date(), dets or {}
    live = [i for i in ipos if not is_closed(i, today)]

    def section(title, items):
        if not items:
            return ""
        items = sorted(items, key=lambda i: -(i["gain"] if i["gain"] is not None else -1e9))
        return (f"<h2>{title}</h2><div class='grid head'><span>IPO</span><span>Apply by</span><span>GMP ₹</span>"
                f"<span>Gain</span><span>Trend</span><span>Verdict</span></div>"
                f"{''.join(row(i, hist, dets, today) for i in items)}")

    body = (broker_links(True) + section("Mainboard", [i for i in live if not i["sme"]])
            + section("SME", [i for i in live if i["sme"]]))
    if not live:
        body += "<p>No IPOs are open right now. See Past IPOs.</p>"
    return page("IPO GMP", "live", body, now, source=True)


def render_history(archive, hist, now, dets=None):
    """Past IPOs page: closed ones, newest first (end date comes from the archive)."""
    today, dets = now.date(), dets or {}
    items = list(archive.values())
    if not items:
        return page("Past IPOs", "past", "<p>Nothing here yet.</p>", now)
    rows = "".join(row(i, hist, dets, today, live=False) for i in items)
    body = (f"<h2>Closed IPOs, last GMP we saw</h2><div class='grid g5 head'><span>IPO</span><span>Closed</span>"
            f"<span>GMP ₹</span><span>Gain</span><span>Trend</span></div>{rows}")
    return page("Past IPOs", "past", body, now)


# ---------- timing advice, briefing and news feed ----------
def last_move(h):
    return h[-1][1] - h[-2][1] if len(h) >= 2 else None


def days_left(i, today):
    end = parse_end(i["dates"], today)
    return None if end is None else (end - today).days


def timing(i, h, today):
    """(label, explanation) on apply early / late / wait / skip. Rule of thumb built from GMP, its last move, days left."""
    if is_closed(i, today):
        return None
    label, _ = verdict(i, today)
    left, mv = days_left(i, today), last_move(h)
    if label == "Apply":
        if left == 0:
            return ("Apply today", "Last day. Place the bid before the cut-off (usually around 5 pm; your broker or UPI "
                    "can stop earlier, so do not leave it to the last hour).")
        if mv is not None and mv < 0:
            return ("Apply, but watch", f"GMP slipped by {money(-mv)} at the last update. It is still above the bar; "
                    "re-check before the last day and bid then if it holds.")
        return ("Apply early", "GMP is above the bar and not falling. Applying early does not raise your allotment chance "
                "(retail allotment is a lottery), but it keeps you clear of last-day glitches.")
    if label == "Ignore":
        if left == 0:
            return ("Skip", "Last day and GMP is below the bar.")
        up = " GMP has been rising." if mv is not None and mv > 0 else ""
        return ("Apply late, if at all", f"GMP is below the bar.{up} Re-check closer to the last day"
                f"{'' if left is None else f' ({left}d left)'} and bid only if it improves.")
    return ("Skip", "GMP is negative or very small. Only revisit if it jumps before the last day.")


def briefing(ipos, hist, archive, today):
    """Short bulletins computed from current data. Returns list of (heading, [lines])."""
    live = [i for i in ipos if not is_closed(i, today)]
    out = []
    closing = [i for i in live if days_left(i, today) in (0, 1)]
    if closing:
        out.append(("Closing soon", [f"{i['name']} — {apply_by(i, today)} · {verdict(i, today)[0]}"
                                     f" ({sign(i['gain'], '%')})" for i in sorted(closing, key=lambda i: days_left(i, today))]))
    picks = sorted([i for i in live if verdict(i, today)[0] == "Apply"], key=lambda i: -(i["gain"] or 0))[:3]
    if picks:
        out.append(("Strongest GMP right now", [f"{i['name']} — {sign(i['gain'], '%')} (GMP {money(i['gmp'])})" for i in picks]))
    moves = []
    for i in live:
        mv = last_move(hist.get(key_of(i["name"]), []))
        if mv:
            moves.append((mv, i))
    movers = sorted(moves, key=lambda m: -abs(m[0]))[:3]
    if movers:
        out.append(("Biggest GMP moves at the last update", [f"{i['name']} — {'▲' if mv > 0 else '▼'} {money(abs(mv))} to {money(i['gmp'])}"
                                                            for mv, i in movers]))
    weak = [i for i in live if not i["sme"] and verdict(i, today)[0] == "Don't apply"]
    if weak:
        out.append(("Mainboard IPOs to be careful with", [f"{i['name']} — GMP {money(i['gmp'])} ({sign(i['gain'], '%')})" for i in weak]))
    main_live = [i for i in live if not i["sme"] and i["gain"] is not None]
    mood = []
    if main_live:
        pos = sum(1 for i in main_live if i["gain"] > 0)
        mood.append(f"Open mainboard IPOs: {pos} of {len(main_live)} have a positive GMP, average expected gain "
                    f"{sum(i['gain'] for i in main_live) / len(main_live):.1f}%.")
    recent = [r for r in archive.values() if r["gain"] is not None][:10]
    if recent:
        mood.append(f"Last {len(recent)} closed IPOs: average GMP gain at close {sum(r['gain'] for r in recent) / len(recent):.1f}%, "
                    f"{sum(1 for r in recent if r['gain'] > 0)} with a positive GMP.")
    if mood:
        out.append(("Market mood (from GMP only)", mood))
    return out


def detect_events(prev, ipos, hist, now):
    """Compare this run with the previous snapshot and write bulletins for what changed."""
    today, t = now.date(), now.strftime("%Y-%m-%d %H:%M")
    before = {key_of(p["name"]): p for p in prev}
    ev = []
    for i in ipos:
        k, p = key_of(i["name"]), before.get(key_of(i["name"]))
        name = i["name"]
        if is_closed(i, today):
            if p is not None and not is_closed(p, today):
                ev.append(("closed", f"{name}: bidding closed. Last GMP {money(i['gmp']) if i['gmp'] is not None else '–'} "
                           f"({sign(i['gain'], '%')})."))
            continue
        lab = verdict(i, today)[0]
        if p is None:
            if prev:
                ev.append(("new", f"New on the list: {name} ({'SME' if i['sme'] else 'Mainboard'}), GMP "
                           f"{money(i['gmp']) if i['gmp'] is not None else '–'} ({sign(i['gain'], '%')}), apply by {apply_by(i, today)}. "
                           f"Verdict: {lab}."))
            continue
        if i["gain"] is not None and p["gain"] is not None:
            d = i["gain"] - p["gain"]
            if abs(d) >= 3:
                ev.append(("move", f"{name}: GMP {'rising' if d > 0 else 'falling'}, {sign(p['gain'], '%')} to {sign(i['gain'], '%')} "
                           f"({money(p['gmp'])} to {money(i['gmp'])})."))
        old = verdict(p, today)[0]
        if old != lab and old != "Closed":
            ev.append(("verdict", f"{name}: verdict changed from {old} to {lab} ({sign(i['gain'], '%')})."))
        if days_left(i, today) == 0 and lab != "Don't apply":
            ev.append(("last-day", f"Last day to apply: {name}. Verdict: {lab}."))
    return [{"t": t, "kind": k, "text": x} for k, x in ev]


def update_news(prev, ipos, hist, now):
    feed = json.loads(NEWS_FILE.read_text()) if NEWS_FILE.exists() else []
    seen = {(e["t"][:10], e["text"]) for e in feed}
    fresh = [e for e in detect_events(prev, ipos, hist, now) if (e["t"][:10], e["text"]) not in seen]
    return (fresh + feed)[:MAX_NEWS]


LOOK_FOR = [
    "Subscription numbers: check the day-by-day subscription (retail, HNI, QIB) in your broker app or on NSE/BSE. "
    "Heavy QIB demand on the last day is a stronger sign than GMP alone. This site does not have that data.",
    "GMP is unofficial and can be wrong or manipulated, especially for small SME issues. Treat it as one signal.",
    "Issue size and how much is a fresh issue vs. offer for sale (OFS). A big OFS means promoters are selling.",
    "Your money: the amount is blocked via UPI until allotment. SME issues usually need a much larger minimum amount than mainboard.",
    "Dates: allotment and listing usually follow a few days after the close. Check them before you tie up funds.",
    "Never apply only because GMP looks high. Read the company and what it plans to do with the money.",
]


def render_news(ipos, hist, archive, feed, now):
    today, e = now.date(), html.escape
    live = [i for i in ipos if not is_closed(i, today)]
    parts = []
    for head, lines in briefing(ipos, hist, archive, today):
        parts.append(f"<h2>{e(head)}</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in lines) + "</ul>")
    groups = {}
    for i in live:
        lab, why = timing(i, hist.get(key_of(i["name"]), []), today)
        groups.setdefault(lab, []).append((i, why))
    order = ["Apply today", "Apply early", "Apply, but watch", "Apply late, if at all", "Skip"]
    g = []
    for lab in order:
        items = sorted(groups.get(lab, []), key=lambda x: -(x[0]["gain"] or -1e9))
        if not items:
            continue
        label = lambda i: f"{e(i['name'])} <span class='mut'>({apply_by(i, today)}, {sign(i['gain'], '%')})</span>"
        if len({why for _, why in items}) == 1:       # same advice for all: say it once
            g.append(f"<li><b>{e(lab)}</b><div class='mut'>{e(items[0][1])}</div><div>"
                     + "<br>".join(label(i) for i, _ in items) + "</div></li>")
        else:
            g.append(f"<li><b>{e(lab)}</b>" + "".join(
                f"<div>{label(i)}<div class='mut'>{e(why)}</div></div>" for i, why in items) + "</li>")
    if g:
        parts.append("<h2>Apply early or late?</h2><ul>" + "".join(g) + "</ul>")
    parts.append("<h2>What to look for</h2><ul>" + "".join(f"<li>{e(x)}</li>" for x in LOOK_FOR) + "</ul>")
    items = "".join(f"<li><span class='mut'>{e(x['t'])}</span> {e(x['text'])}</li>" for x in feed) or \
        "<li class='mut'>No changes recorded yet. New bulletins appear here after each update.</li>"
    parts.append(f"<h2>Live feed</h2><ul class='feed'>{items}</ul>")
    return page("News & advice", "news", "".join(parts), now)


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
    prev = json.loads(IPOS_FILE.read_text()) if IPOS_FILE.exists() else []
    IPOS_FILE.write_text(json.dumps(ipos, indent=1, ensure_ascii=False))
    archive = update_archive(ipos, now)
    feed = update_news(prev, ipos, hist, now)
    NEWS_FILE.write_text(json.dumps(feed, indent=1, ensure_ascii=False))
    NEWS_PAGE.write_text(render_news(ipos, hist, archive, feed, now))
    ARCHIVE_FILE.write_text(json.dumps(archive, indent=1, ensure_ascii=False))
    OUT_FILE.write_text(render(ipos, hist, now, dets))
    HISTORY_PAGE.write_text(render_history(archive, hist, now, dets))
    print(f"wrote {OUT_FILE.name}, {HISTORY_PAGE.name}, {NEWS_PAGE.name}: {len(ipos)} IPOs, "
          f"{len(archive)} archived, {len(feed)} news items, "
          f"details for {len(dets)} IPOs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
