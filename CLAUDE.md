# CLAUDE.md

Brique-à-Brac: web app to rebuild LEGO sets from a mixed pile sorted by color. See README.md for features.

## Layout

- `server.py`: stdlib-only Python HTTP server. Rebrickable client (rate-limited ~1 req/s, responses cached in `data/cache/`), LEGO instruction scraping + PDF proxy, Brickognize proxy, JSON API, state persistence.
- `static/index.html`: whole UI in one file (vanilla JS, mobile-first, French UI). No build step.
- `data/` (gitignored): `state.json` (live user data), `backups/`, `cache/`.
- `.env` (gitignored): `REBRICKABLE_API_KEY`.

## Live users — read first

The app is used daily by the user's family on the running instance (`python3 server.py`, port 8642). The server serves `static/` straight from disk, so a broken HTML/JS edit breaks the app for them right away.

- Never test against the real `data/state.json`. Test API calls on a throwaway instance: `DATA_DIR=<scratch>/x PORT=8643 python3 server.py` (copy `data/cache/*.json` into it to avoid refetching).
- After editing `static/index.html`, syntax-check the script before calling it done: extract the `<script>` content and run `node --check` on it.
- Changing `server.py` needs a restart (2-3 s outage). Static edits don't.
- Never delete or rewrite `data/`.

## Conventions

- Part key = `"{rebrickable_part_num}|{rebrickable_color_id}"`; spare parts excluded; minifig parts included.
- Allocation rule: a found piece goes to the first active set in queue order that still needs it, unless a set is focused (then that set).
- Brickognize returns BrickLink ids (part and color); map them to Rebrickable via `bl_colors()` and `rb_part_from_bricklink()`.
- Visual checks: headless Chrome enforces a 500px minimum width, so render the page inside a 375px iframe to see the phone layout.
