# Planet Zero: the feed

This branch is the feed, served by GitHub Pages at https://yheushen.github.io/planetzero-feed/. It is built every hour by `.github/workflows/feed.yml` on `main` (`engine/build_feed.py`); `audit.json` and `audit/answers/` come from the AI chat audit. Do not edit by hand: the next run overwrites it.

- `now.json`, `outlook.json`, `grid.json`, `checks.json`: the contract is `engine/schema/` on `main`.
- `status.json`: what each source did on the last run.
- `history/`: hourly history per source and month.
- Credit lines: `ATTRIBUTION.md`, and the `credits` block in every JSON file.
