"""Pure-SVG GMP charts (no JavaScript). Styling comes from the page CSS classes: .ax .gl .tx .zl .bl .ln .pt"""
import html
from datetime import datetime


def _ts(s):
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M").timestamp()
    except ValueError:
        return 0.0


def _nice_step(span, n=4):
    raw = span / n if span > 0 else 1
    mag = 10 ** (len(str(int(raw))) - 1) if raw >= 1 else 10 ** -1
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _fmt(v):
    return f"{v:,.0f}" if abs(v) >= 100 or float(v).is_integer() else f"{v:,.1f}"


def chart(h, bar=None, big=True):
    """h = [[ 'YYYY-MM-DD HH:MM', gmp ], ...]; bar = GMP rupee level that earns an 'Apply'. Returns an <svg> string."""
    W, H = (640, 340) if big else (320, 140)
    L, R, T, B = (52, 16, 16, 34) if big else (38, 10, 10, 22)
    if not h:
        return (f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="No GMP readings yet">'
                f'<text class="tx" x="{W / 2}" y="{H / 2}" text-anchor="middle">No readings yet</text></svg>')
    pts = [(_ts(t), float(v), t) for t, v in h]
    vals = [v for _, v, _ in pts]
    lo, hi = min(vals + [0.0]), max(vals + ([bar] if bar is not None else []) + [0.0])
    if hi - lo < 1:
        hi = lo + 1
    hi += (hi - lo) * 0.14
    lo -= (hi - lo) * 0.04 if lo < 0 else 0
    pad = 22 if big else 8                        # keep first/last points and their labels inside the frame
    pw, ph = W - L - R, H - T - B
    y = lambda v: T + (hi - v) / (hi - lo) * ph
    t0, t1 = pts[0][0], pts[-1][0]
    if len(pts) == 1:
        xs = [L + pw / 2]
    elif t1 > t0:
        xs = [L + pad + (t - t0) / (t1 - t0) * (pw - 2 * pad) for t, _, _ in pts]
    else:
        xs = [L + pad + i / (len(pts) - 1) * (pw - 2 * pad) for i in range(len(pts))]
    out = [f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="GMP over time, latest ₹{_fmt(vals[-1])}">']
    step = _nice_step(hi - lo)
    g = (lo // step) * step
    while g <= hi:
        if g >= lo:
            out.append(f'<line class="gl" x1="{L}" x2="{W - R}" y1="{y(g):.1f}" y2="{y(g):.1f}"/>'
                       f'<text class="tx" x="{L - 6}" y="{y(g) + 4:.1f}" text-anchor="end">{_fmt(g)}</text>')
        g += step
    if lo < 0 < hi:
        out.append(f'<line class="zl" x1="{L}" x2="{W - R}" y1="{y(0):.1f}" y2="{y(0):.1f}"/>')
    if bar is not None and bar > 0:
        out.append(f'<line class="bl" x1="{L}" x2="{W - R}" y1="{y(bar):.1f}" y2="{y(bar):.1f}"/>')
        if big:
            out.append(f'<text class="tx" x="{W - R - 4}" y="{y(bar) - 5:.1f}" text-anchor="end">'
                       f'Apply bar ₹{_fmt(bar)}</text>')
    cls = "ln" if vals[-1] >= vals[0] else "ln dn"
    if len(pts) > 1:
        out.append(f'<polyline class="{cls}" fill="none" points="' + " ".join(f"{x:.1f},{y(v):.1f}" for x, (_, v, _) in zip(xs, pts)) + '"/>')
    n = len(pts)
    for k, (x, (_, v, t)) in enumerate(zip(xs, pts)):
        last = k == n - 1
        out.append(f'<circle class="pt{" dn" if v < 0 else ""}" cx="{x:.1f}" cy="{y(v):.1f}" r="{4 if last else 2.5}"/>')
        if big and (last or n <= 10):
            out.append(f'<text class="tx v" x="{x:.1f}" y="{y(v) - 8:.1f}" text-anchor="middle">₹{_fmt(v)}</text>')
    if big:                                           # x-axis date labels
        span_days = (t1 - t0) / 86400
        want = min(n, 5)
        for idx in sorted({round(k * (n - 1) / max(want - 1, 1)) for k in range(want)}):
            t = pts[idx][2]
            lab = t[11:16] if span_days < 1 else datetime.strptime(t, "%Y-%m-%d %H:%M").strftime("%d %b")
            out.append(f'<text class="tx" x="{xs[idx]:.1f}" y="{H - 10}" text-anchor="middle">{html.escape(lab)}</text>')
    out.append("</svg>")
    return "".join(out)


def mini(h):
    """Tiny inline trend graph for table rows. A single reading is drawn as a dot so every IPO has a graph."""
    vals = [float(v) for _, v in h[-15:]]
    if not vals:
        return '<svg class="mini" width="56" height="18" viewBox="0 0 56 18"><line class="gl" x1="2" x2="54" y1="9" y2="9"/></svg>'
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    if len(vals) == 1:
        return ('<svg class="mini" width="56" height="18" viewBox="0 0 56 18"><line class="gl" x1="2" x2="54" y1="9" y2="9"/>'
                '<circle class="pt" cx="28" cy="9" r="3"/></svg>')
    pts = " ".join(f"{2 + i / (len(vals) - 1) * 52:.1f},{16 - (v - lo) / span * 14:.1f}" for i, v in enumerate(vals))
    cls = "ln" if vals[-1] >= vals[0] else "ln dn"
    ex, ey = pts.split()[-1].split(",")
    return (f'<svg class="mini" width="56" height="18" viewBox="0 0 56 18"><polyline class="{cls}" fill="none" points="{pts}"/>'
            f'<circle class="pt" cx="{ex}" cy="{ey}" r="2.2"/></svg>')
