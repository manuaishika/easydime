"""Scrape IPO Watch's GMP table, keep GMP history, and render a static index.html.

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
IST = timezone(timedelta(hours=5, minutes=30))
MAX_HISTORY = 60


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


# ---------- render ----------
CSS = """
:root{color-scheme:light dark;--bg:#fff;--fg:#111;--mut:#777;--line:#eee;--up:#0a8f4d;--down:#d0312d}
@media(prefers-color-scheme:dark){:root{--bg:#111;--fg:#eee;--mut:#999;--line:#2a2a2a;--up:#3ddc84;--down:#ff6b66}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.4 system-ui,sans-serif}
main{max-width:760px;margin:0 auto;padding:16px}h1{font-size:18px;margin:0 0 4px}h2{font-size:13px;color:var(--mut);
font-weight:500;margin:22px 0 4px;text-transform:uppercase;letter-spacing:.05em}
table{width:100%;border-collapse:collapse}th{font-weight:500;color:var(--mut);text-align:right;font-size:12px;padding:6px}
th:first-child,td:first-child{text-align:left}td{padding:10px 6px;border-top:1px solid var(--line);text-align:right;
vertical-align:top;white-space:nowrap}td:first-child{white-space:normal}summary{cursor:pointer}
.up{color:var(--up)}.down{color:var(--down)}.mut{color:var(--mut);font-size:12px}.det{color:var(--mut);font-size:13px;
margin-top:6px}a{color:inherit}
"""


def sign(v, suffix=""):
    return "–" if v is None else f"{v:+g}{suffix}" if suffix else f"{v:g}"


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


def row(i, hist, today):
    e = html.escape
    h = hist.get(key_of(i["name"]), [])
    label, why = verdict(i, today)
    est = f"₹{i['est_price']:g}" if i["est_price"] is not None else "–"
    bits = [f"Price band: {e(i['price_text'] or '–')}", f"Est. listing: {e(est)}",
            f"Dates: {e(i['dates'] or '–')}", f"Verdict: {e(why)}"]
    if i["size"]:
        bits.append(f"Size: {e(i['size'])}")
    history = ", ".join(f"{t[5:10]} ₹{v:g}" for t, v in h[-10:]) or "just started tracking"
    link = f' · <a href="{e(i["url"])}" target="_blank" rel="noopener">IPO Watch ↗</a>' if i["url"] else ""
    cls = {"Apply": "up", "Don't apply": "down"}.get(label, "mut")
    return (f'<tr><td><details><summary>{e(i["name"])}</summary>'
            f'<div class="det">{" · ".join(bits)}<br>GMP history: {history}{link}</div></details></td>'
            f'<td>{e(apply_by(i, today))}</td>'
            f'<td>{sign(i["gmp"])}</td><td class="{color(i["gain"])}"><b>{sign(i["gain"], "%")}</b></td>'
            f'<td>{sparkline(h)}</td><td class="{cls}"><b>{e(label)}</b></td></tr>')


def render(ipos, hist, now):
    today = now.date()

    def section(title, items):
        if not items:
            return ""
        # open IPOs first (best gain on top), closed ones at the bottom
        items = sorted(items, key=lambda i: (is_closed(i, today), -(i["gain"] if i["gain"] is not None else -1e9)))
        return (f"<h2>{title}</h2><table><thead><tr><th>IPO</th><th>Apply by</th><th>GMP ₹</th><th>Gain</th>"
                f"<th>Trend</th><th>Verdict</th></tr></thead>"
                f"<tbody>{''.join(row(i, hist, today) for i in items)}</tbody></table>")

    body = section("Mainboard", [i for i in ipos if not i["sme"]]) + section("SME", [i for i in ipos if i["sme"]])
    if not body:
        body = "<p>No IPOs could be read from the source. Check the latest GitHub Action log.</p>"
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><title>IPO GMP</title><style>{CSS}</style></head><body><main>'
            f'<h1>IPO GMP</h1><div class="mut">Updated {now.strftime("%d %b %Y, %H:%M")} IST · tap an IPO for details</div>'
            f'{body}<p class="mut">Source: <a href="{SOURCE}">IPO Watch</a>. GMP is unofficial and moves fast; '
            f'treat it as a rough signal only. Verdict is a simple rule (Apply: GMP gain ≥10%, ≥15% for SME; '
            f'Don\'t apply: negative or under 3%; Ignore: in between or no GMP), not financial advice.</p></main></body></html>')


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
    OUT_FILE.write_text(render(ipos, hist, now))
    print(f"wrote {OUT_FILE.name} with {len(ipos)} IPOs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
