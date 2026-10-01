import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import charts


def test_chart_with_history_has_axes_bar_and_labels():
    h = [["2026-09-28 08:00", 10.0], ["2026-09-29 08:00", 15.0], ["2026-09-30 08:00", 12.0]]
    svg = charts.chart(h, bar=13.0, big=True)
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "<polyline" in svg and "Apply bar ₹13" in svg and "₹12" in svg and "28 Sep" in svg


def test_single_reading_and_empty_still_draw():
    one = charts.chart([["2026-09-30 08:00", 5.0]], bar=10.0)
    assert "<circle" in one and "<polyline" not in one
    assert "No readings yet" in charts.chart([], None)
    assert "<circle" in charts.mini([["2026-09-30 08:00", 5.0]]) and "<svg" in charts.mini([])


def test_negative_gmp_is_drawn_below_zero_and_red():
    svg = charts.chart([["2026-09-30 08:00", 2.0], ["2026-09-30 14:00", -3.0]], bar=None)
    assert 'class="ln dn"' in svg and 'class="zl"' in svg
