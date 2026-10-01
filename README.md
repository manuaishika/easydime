# easydime — IPO GMP in one table

Pure Python, no JavaScript. `build.py` scrapes GMP from [IPO Watch](https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/)
and writes two static pages:

- `index.html` — open and upcoming IPOs: Apply by, GMP, expected gain %, trend, an Apply / Don't apply / Ignore verdict,
  a worked-arithmetic detail view (tap a row), and Groww / Zerodha links.
- `history.html` — closed IPOs, kept in `data/archive.json`.
- `news.html` — a news-style page: a daily briefing (closing soon, strongest GMP, biggest moves, market mood), an
  "apply early or late?" guide per IPO, a "what to look for" checklist, and a live feed of changes (`data/news.json`).

GMP snapshots are saved in `data/history.json`, so trends build up over time.
A GitHub Action (`.github/workflows/update.yml`) re-runs it four times a day and commits to `main`.

- Serve: GitHub Pages (Settings → Pages → `main` / root) or Vercel/Netlify as a plain static site (no build command).
- Run locally: `python build.py` (see what was parsed: `python build.py --debug`). Tests: `pytest tests`.
