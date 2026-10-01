# easydime — IPO GMP in one table

Pure Python, no JavaScript. `build.py` scrapes GMP from [IPO Watch](https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/)
and writes two static pages:

- `index.html` — open and upcoming IPOs: Apply by, GMP, expected gain %, a trend graph (click it to enlarge), an
  Apply / Don't apply / Ignore verdict, a financial analysis per IPO (tap a row: value per application, scenarios,
  allotment odds, valuation vs peers, growth and profitability, use of proceeds, red flags), and Groww / Zerodha links.
- `history.html` — closed IPOs, kept in `data/archive.json`.
- `news.html` — a news-style page: a daily briefing (closing soon, strongest GMP, biggest moves, market mood), an
  "apply early or late?" guide per IPO, a "what to look for" checklist, and a live feed of changes (`data/news.json`).

GMP snapshots are saved in `data/history.json`, so trends build up over time. Company details for the analysis are read from
each IPO's own page and cached in `data/details.json` (`details.py` parses and analyses; `charts.py` draws the SVG graphs).
A GitHub Action (`.github/workflows/update.yml`) re-runs it four times a day and commits to `main`.

- Serve: GitHub Pages (Settings → Pages → `main` / root) or Vercel/Netlify as a plain static site (no build command).
- Run locally: `python build.py` (see what was parsed: `python build.py --debug`). Tests: `pytest tests`.
