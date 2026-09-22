# Rallylog

**A tennis match diary.** Browse real ATP and WTA matches, log what you watched, rate matches, write reviews, comment, follow players, and see your tennis taste in a personal profile.

Rallylog is a separate project from Movie Finder. The interface is in English. It uses Flask, Flask-SQLAlchemy and Flask-Login. SQLite works locally; set `DATABASE_URL` to use PostgreSQL when hosting.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app wsgi run --debug
```

Open <http://127.0.0.1:5000>. The first run creates the local database and imports 16 real Grand Slam finals from 2024–2025 so the site is usable immediately. `instance/rallylog.db` is ignored by Git. To load a larger catalog:

```bash
flask --app wsgi import-tennis --from-year 2023 --to-year 2026
```

That command downloads ATP and WTA CSV files from the [Sackmann archive](https://github.com/Aneeshers/tennis-sackmann-archive). It can be run again safely: existing matches are skipped. For complete historical career title counts, import more years. The archive snapshot contains data only through **June 2026**, even though a 2026 CSV exists. It is not a live score feed.

## What is here

- **Discover:** featured match, archive highlights and recent public reviews.
- **Matches:** search by player or tournament; filter by tour, surface, level and year.
- **Match page:** score, recorded serve statistics, community rating, reviews and comments.
- **Diary:** one editable entry per user and match with viewing date, optional half-star rating, review, favorite, spoiler flag and public/private choice.
- **Watchlist:** save matches to watch later; logging a match removes it from the watchlist.
- **Players:** biography, imported wins and losses, surface and season splits, titles, serve metrics, frequent opponents and followed players.
- **Profiles:** personal diary, watched surfaces, tour split, ratings and favorites.
- **Settings:** display name, bio, password change, diary export and account deletion.

## Data honesty

- The dataset's `tourney_date` is the **start of the tournament week**, not an exact match date. The interface labels it accordingly.
- Win rates, titles, head-to-head and rankings are calculated from **loaded matches only**. Rankings shown are from the player's latest imported match, not current rankings.
- Prize money appears only when [Wikidata](https://www.wikidata.org/) lists a USD amount for that player's linked entity. The source and date are visible. Missing data is shown as unavailable. A displayed amount may be out of date.
- Sample CSV-derived JSON in `data/` is CC BY-NC-SA 4.0. See [DATA_LICENSE.md](DATA_LICENSE.md). This project is intended for non-commercial use.

## Repository and deployment

The project is a local Git repository. No accounts, passwords or database files belong in Git. Copy `.env.example` to `.env` if you want local environment variables; keep the real `.env` private.

For a later free public preview, a workable route is a free [Render web service](https://render.com/docs/free) with a free [Supabase Postgres database](https://supabase.com/pricing). Set these environment variables on the web service:

```text
APP_ENV=production
SECRET_KEY=<long random secret>
DATABASE_URL=<Postgres connection URL>
```

Build command: `pip install -r requirements.txt`  
Start command: `gunicorn wsgi:app`

Run `flask --app wsgi import-tennis ...` against the same database from a trusted local shell to add the historical catalog. Render's free web service sleeps when idle and its local filesystem is temporary, so **do not use SQLite there for user accounts or reviews**. Supabase's free project can pause after inactivity. Free-plan policies may change; review them before deployment. This is a hobby-project setup, not a guarantee of permanent free hosting.

Before opening registration to strangers, add email verification, password recovery, abuse reporting/moderation, database backups and a persistent rate limit. The current build is ready for local testing and a small controlled preview.

## Structure

```text
rallylog/
  rallylog/__init__.py     application setup and import command
  rallylog/models.py       database tables
  rallylog/importer.py     historical match import
  rallylog/stats.py        transparent statistics
  rallylog/prize_money.py  optional Wikidata figure
  rallylog/routes.py       pages and forms
  rallylog/templates/     HTML pages
  rallylog/static/        CSS and favicon
  data/                   small credited starter dataset
  tests/                  critical user-flow tests
  wsgi.py                 web server entry point
```
