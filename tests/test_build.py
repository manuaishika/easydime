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
