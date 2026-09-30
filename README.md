# easydime — IPO GMP in one table

Pure Python, no JavaScript. `build.py` scrapes GMP from [IPO Watch](https://ipowatch.in/ipo-grey-market-premium-latest-ipo-gmp/) and writes two static pages: `index.html` (open and upcoming IPOs, with Apply by, GMP, gain, trend, verdict, worked arithmetic, and Groww/Zerodha links) and `history.html` (closed IPOs, kept in `data/archive.json`). GMP history is kept in `data/history.json`.
keeps a GMP history in `data/history.json`, and writes a static `index.html` (name, GMP ₹, expected gain %, trend;
tap an IPO for price band, dates and history).

A GitHub Action (`.github/workflows/update.yml`) re-runs it four times a day and commits to `main`.

- Serve: GitHub Pages (Settings → Pages → `main` / root) or Vercel/Netlify as a plain static site (no build command).
- Run locally: `python build.py` (debug what was parsed: `python build.py --debug`). Tests: `pytest tests`.
