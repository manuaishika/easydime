import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import build

PAGE = """<p>intro</p><table><tr><th>IPO Name</th><th>Price Band</th><th>GMP</th><th>Open</th><th>Close</th><th>Listing Date</th></tr>
<tr><td><a href="https://ipowatch.in/x">Acme Ltd IPO</a></td><td>₹95 to ₹100</td><td>₹25 (25%)</td><td>1 Oct</td><td>3 Oct</td><td>8 Oct</td></tr>
<tr><td>Foo SME IPO</td><td>₹60</td><td>-₹5</td><td>1 Oct</td><td>3 Oct</td><td>8 Oct</td></tr>
<tr><td>Bar IPO</td><td>₹50</td><td>-</td><td>-</td><td>-</td><td>-</td></tr></table>"""


def test_parse():
    _, ipos = build.parse(PAGE)
    a, f, b = ipos
    assert (a["name"], a["gmp"], a["gain"], a["price"], a["sme"]) == ("Acme Ltd", 25, 25, 100, False)
    assert a["url"] == "https://ipowatch.in/x"
    assert (f["gmp"], f["gain"], f["sme"]) == (-5, -8.33, True)
    assert (b["gmp"], b["gain"]) == (None, None)


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
