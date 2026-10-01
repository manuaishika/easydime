import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import build

ROW = "<tr><td>{}</td><td>{}</td><td>🟢</td><td>{}</td><td>{}</td><td>30-5 Oct</td><td>Open</td></tr>"
HEAD = "<tr><th>IPO Name</th><th>IPO GMP*</th><th>Trend</th><th>Price Band</th><th>Est. Listing</th><th>Date</th><th>Status</th></tr>"
PAGE = ("<h2>Mainboard IPO GMP Today</h2><table>" + HEAD
        + ROW.format('<a href="https://ipowatch.in/x">Acme Ltd IPO</a>', "₹25", "₹95 to ₹100", "₹125 (25.00%)")
        + ROW.format("Loss Co", "-₹5", "₹60", "₹55 (-8.33%)")
        + ROW.format("No Gmp", "-", "₹50", "–") + "</table>"
        + "<h2>SME IPO GMP Today</h2><table>" + HEAD + ROW.format("Small Ltd", "₹7", "₹70", "₹77 (10.00%)") + "</table>")


def test_parse():
    _, ipos = build.parse(PAGE)
    a, loss, none, small = ipos
    assert (a["name"], a["gmp"], a["gain"], a["price"], a["sme"]) == ("Acme Ltd", 25, 25.0, 100, False)
    assert (a["est_price"], a["dates"], a["status"]) == (125, "30-5 Oct", "Open")
    assert a["url"] == "https://ipowatch.in/x"
    assert (loss["gmp"], loss["gain"]) == (-5, -8.33)
    assert (none["gmp"], none["gain"]) == (None, None)
    assert (small["gain"], small["sme"]) == (10.0, True)


def test_render_and_history(tmp_path, monkeypatch):
    monkeypatch.setattr(build, "HISTORY_FILE", tmp_path / "h.json")
    _, ipos = build.parse(PAGE)
    now = datetime(2026, 10, 1, 9, 0)
    hist = build.update_history(ipos, now)
    ipos[0]["gmp"] = 30
    build.HISTORY_FILE.write_text(__import__("json").dumps(hist))
    hist = build.update_history(ipos, now)
    assert [v for _, v in hist["acmeltd"]] == [25, 30]
    out = build.render(ipos, hist, now)
    assert "Acme Ltd" in out and "<polyline" in out and "▲" in out and "SME" in out
    assert "Small Ltd" in out.split("<h2>SME</h2>")[-1]
    assert "Small Ltd" not in out.split("<h2>SME</h2>")[0]


def test_parse_end():
    today = date(2026, 9, 30)
    assert build.parse_end("28-5 Oct", today) == date(2026, 10, 5)
    assert build.parse_end("23-25 Sep", today) == date(2026, 9, 25)
    assert build.parse_end("30 Sep - 5 Oct", today) == date(2026, 10, 5)
    assert build.parse_end("29-2 Jan", date(2026, 12, 30)) == date(2027, 1, 2)
    assert build.parse_end("TBA", today) is None


def test_verdict():
    today = date(2026, 9, 30)
    base = dict(gmp=1, gain=None, sme=False, status="Open", dates="30-5 Oct")
    v = lambda **k: build.verdict({**base, **k}, today)[0]
    assert v(gain=12) == "Apply" and v(gain=12, sme=True) == "Ignore" and v(gain=16, sme=True) == "Apply"
    assert v(gain=-2) == "Don't apply" and v(gain=1) == "Don't apply" and v(gain=5) == "Ignore"
    assert v(gain=None, gmp=None) == "Ignore" and v(gain=50, status="Closed") == "Closed"
    assert v(gain=50, dates="23-25 Sep") == "Closed"
    assert build.apply_by({**base}, today).endswith("5 Oct · 5d")


def _rec(**k):
    base = dict(name="Acme Ltd", sme=False, gmp=25.0, gain=25.0, price=100.0, price_text="₹95 to ₹100", est_price=125.0,
                dates="30-5 Oct", status="Open", size="", url=None)
    return {**base, **k}


def test_arithmetic_numbers():
    rows = dict(build.arithmetic(_rec(price=220.0, gmp=6.0, gain=2.73)))
    assert rows["Estimated listing price"] == "₹220 + ₹6 = ₹226"
    assert rows["Expected gain"] == "₹6 ÷ ₹220 × 100 = 2.73%"
    assert rows["If you invest about ₹15,000"] == "68 shares × ₹220 = ₹14,960"
    assert rows["Estimated profit / loss"].startswith("68 × ₹6 = +₹408")
    assert rows["GMP needed for ‘Apply’ (10%)"].startswith("₹220 × 10% = ₹22")
    neg = dict(build.arithmetic(_rec(gmp=-5.0, gain=-5.0)))
    assert neg["Estimated listing price"] == "₹100 − ₹5 = ₹95"


def test_pages_split_open_and_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(build, "ARCHIVE_FILE", tmp_path / "a.json")
    now = datetime(2026, 10, 1, 9, 0)
    ipos = [_rec(), _rec(name="Old Co", dates="23-25 Sep", status="Closed")]
    main = build.render(ipos, {}, now)
    arch = build.update_archive(ipos, now)
    past = build.render_history(arch, {}, now)
    assert "Acme Ltd" in main and "Old Co" not in main
    assert "Old Co" in past and "Acme Ltd" not in past
    assert arch["oldco"]["end"] == "2026-09-25"
    assert "https://groww.in/ipo" in main and "https://zerodha.com/ipo/" in main
    assert "groww.in" not in past            # no apply links for closed IPOs
    assert "The arithmetic" in main and "history.html" in main


def test_timing_labels():
    today = date(2026, 9, 30)
    h_up, h_down = [["a", 20], ["b", 25]], [["a", 30], ["b", 25]]
    assert build.timing(_rec(gain=20, dates="28-30 Sep"), [], today)[0] == "Apply today"
    assert build.timing(_rec(gain=20), h_up, today)[0] == "Apply early"
    assert build.timing(_rec(gain=20), h_down, today)[0] == "Apply, but watch"
    assert build.timing(_rec(gain=5), h_up, today)[0] == "Apply late, if at all"
    assert build.timing(_rec(gain=5, dates="28-30 Sep"), [], today)[0] == "Skip"
    assert build.timing(_rec(gain=-3, gmp=-3.0), [], today)[0] == "Skip"
    assert build.timing(_rec(dates="23-25 Sep", status="Closed"), [], today) is None



def test_events_and_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(build, "NEWS_FILE", tmp_path / "n.json")
    now = datetime(2026, 9, 30, 9, 0)
    old = [_rec(), _rec(name="Gone Co", gain=20.0), _rec(name="Flat Co", gain=5.0, gmp=5.0)]
    new = [_rec(gain=5.0, gmp=5.0),                                     # fell 25% -> 5%: Apply -> Ignore
           _rec(name="Gone Co", gain=20.0, status="Closed", dates="25-29 Sep"),
           _rec(name="Flat Co", gain=5.0, gmp=5.0),                      # unchanged -> no event
           _rec(name="Fresh Co", gain=30.0, gmp=30.0)]                    # new listing
    texts = " | ".join(e["text"] for e in build.detect_events(old, new, {}, now))
    assert "Acme Ltd: GMP falling" in texts and "verdict changed" in texts
    assert "Gone Co: bidding closed" in texts and "New on the list: Fresh Co" in texts
    assert "Flat Co" not in texts
    feed = build.update_news(old, new, {}, now)
    again = build.update_news(old, new, {}, now)   # same run twice must not duplicate
    build.NEWS_FILE.write_text(__import__("json").dumps(feed))
    assert len(build.update_news(old, new, {}, now)) == len(feed) == len(again)
    assert build.detect_events([], new, {}, now) == [] or all(e["kind"] != "new" for e in build.detect_events([], new, {}, now))


def test_news_page():
    now = datetime(2026, 9, 30, 9, 0)
    ipos = [_rec(gain=20.0, dates="28-30 Sep"), _rec(name="Flat Co", gain=5.0, gmp=5.0)]
    out = build.render_news(ipos, {}, {}, [{"t": "2026-09-30 08:00", "kind": "new", "text": "Hello bulletin"}], now)
    assert "Apply today" in out and "Closing soon" in out and "Hello bulletin" in out and "What to look for" in out
    assert "Apply early or late?" in out
