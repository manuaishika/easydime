"""End-to-end: run main() against fake pages, so wiring mistakes (not just helper functions) are caught."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import build
from test_details import SRIT


def as_html(tables):
    return "".join("<table>" + "".join("<tr>" + "".join(f"<td>{c[0]}</td>" for c in r) + "</tr>" for r in t) + "</table>"
                   for t in tables)


LIST = ("<h2>Mainboard</h2><table><tr><th>IPO Name</th><th>IPO GMP*</th><th>Trend</th><th>Price Band</th>"
        "<th>Est. Listing</th><th>Date</th><th>Status</th></tr>"
        "<tr><td><a href='https://x.test/live'>Live Co</a></td><td>₹31</td><td>🟢</td><td>₹130</td><td>₹161 (23.85%)</td>"
        "<td>28-31 Dec</td><td>Open</td></tr>"
        "<tr><td><a href='https://x.test/broken'>Broken Page Co</a></td><td>₹5</td><td>🟢</td><td>₹50</td><td>₹55 (10%)</td>"
        "<td>28-31 Dec</td><td>Open</td></tr>"
        "<tr><td>Done Co</td><td>₹2</td><td>🟢</td><td>₹50</td><td>₹52 (4%)</td><td>20-22 Dec</td><td>Closed</td></tr></table>")


def fake_fetch(url=build.SOURCE):
    if url == build.SOURCE:
        return LIST
    if url.endswith("/live"):
        return as_html(SRIT)
    raise OSError("boom")                                     # one detail page failing must not break the build


def test_main_end_to_end(tmp_path, monkeypatch):
    for name, f in dict(HISTORY_FILE="h.json", IPOS_FILE="i.json", ARCHIVE_FILE="a.json", NEWS_FILE="n.json",
                        DETAILS_FILE="d.json", OUT_FILE="index.html", HISTORY_PAGE="history.html", NEWS_PAGE="news.html").items():
        monkeypatch.setattr(build, name, tmp_path / f)
    monkeypatch.setattr(build, "fetch", fake_fetch)
    monkeypatch.setattr(build.time, "sleep", lambda s: None)
    assert build.main([]) == 0
    index, hist, news = [(tmp_path / n).read_text() for n in ("index.html", "history.html", "news.html")]
    assert "Live Co" in index and "Done Co" not in index and "Done Co" in hist
    assert "Financial analysis" in index and "115 shares" in index            # details were fetched and analysed
    dets = json.loads((tmp_path / "d.json").read_text())
    assert "liveco" in dets and "brokenpageco" not in dets                      # failed page skipped, build survived
    assert "News" in news and "<script" not in index + hist + news
    assert (index + hist + news).count("IPO Watch") == 1
    assert build.main([]) == 0                                                  # a second run (with history) also works
