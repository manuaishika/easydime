import sys
from datetime import datetime
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
