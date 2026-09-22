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
- **Account safety:** email verification, expiring single-use password reset links and session invalidation after password changes.
- **Community safety:** report controls and a private moderation queue for the verified administrator.

## Data honesty

- The dataset's `tourney_date` is the **start of the tournament week**, not an exact match date. The interface labels it accordingly.
- Win rates, titles, head-to-head and rankings are calculated from **loaded matches only**. Rankings shown are from the player's latest imported match, not current rankings.
- Prize money appears only when [Wikidata](https://www.wikidata.org/) lists a USD amount for that player's linked entity. The source and date are visible. Missing data is shown as unavailable. A displayed amount may be out of date.
- Sample CSV-derived JSON in `data/` is CC BY-NC-SA 4.0. See [DATA_LICENSE.md](DATA_LICENSE.md). This project is intended for non-commercial use.

## Security model

- New passwords use Argon2id with OWASP's 19 MiB / 2 iteration baseline. Existing Werkzeug hashes are accepted and upgraded after a successful login.
- Every state-changing form requires a session CSRF token. Login, registration, password reset, account deletion and reports use database-backed limits that survive web restarts.
- Email verification and reset tokens are random, stored only as SHA-256 digests and deleted after use. Reset and password change invalidate older sessions.
- Production requires HTTPS cookies, a stable secret, an allowed host, PostgreSQL over TLS, configured email delivery and contact addresses before registration can open.
- Responses include HSTS in production, CSP, clickjacking, MIME-sniffing, referrer and browser-permission protections. Authenticated pages are not cacheable.
- User content is escaped by Jinja. Private diary entries and watchlists are never returned on another member's profile.
- The web database role receives data access but no schema creation rights. The owner connection is reserved for initialization and recovery.
- Users can export or delete their data. The privacy page explains stored fields and third-party processing.

## Public deployment

The checked-in [Render Blueprint](render.yaml) deploys one free web service with HTTPS and registration initially disabled. Use a separate [Neon PostgreSQL](https://neon.com/) database; do not use SQLite on Render because the free web service filesystem is ephemeral.

1. Create a Neon project in a nearby region. Copy its TLS connection string into the GitHub repository secret `DATABASE_OWNER_URL`.
2. Run the GitHub action **Initialize production database** once. It creates the schema and loads the bundled catalog of 19,903 ATP/WTA matches without importing user data.
3. In Neon, create a login role named `rallylog_app` with a long generated password. Run `scripts/secure_database.sql` as the owner. Build a pooled TLS URL for that role and use it as Render's `DATABASE_URL`.
4. Create a Resend account and verify a sending domain. Account email cannot reliably use SMTP from a free Render service, so Rallylog uses the HTTPS API. Set `RESEND_API_KEY`, `MAIL_FROM`, `ADMIN_EMAIL` and `CONTACT_EMAIL` in Render.
5. In Render, deploy the repository as a Blueprint. `SECRET_KEY` is generated by Render. The service reads Render's own hostname automatically and starts with `REGISTRATION_ENABLED=false`.
6. Verify `/healthz`, the catalog, account email, login, password reset, reports, export and account deletion. Then change `REGISTRATION_ENABLED` to `true` and redeploy.

Render free services sleep after 15 minutes without traffic and may take about a minute to wake. Neon free compute also sleeps while idle. These limits suit an early public preview; neither free plan is an uptime guarantee.

## Backups and recovery

The **Encrypted database backup** GitHub action creates a PostgreSQL custom-format dump, encrypts it with an age public key before upload and retains the artifact for 30 days. Configure:

- GitHub secret `BACKUP_DATABASE_URL`: a TLS database URL that can read all Rallylog tables.
- GitHub variable `BACKUP_RECIPIENT`: the public `age1...` key. Keep the private age key offline and outside GitHub.
- GitHub variable `BACKUPS_ENABLED=true` only after performing a restore drill.

To validate recovery, download an encrypted artifact, decrypt it locally with the offline age key, restore it into a fresh temporary PostgreSQL database, and compare table counts plus a test account export. A backup is only trusted after that restore succeeds. Neon Free includes a short instant-restore window, while the encrypted export protects against longer incidents.

## Secrets and release process

No account data, database files, API keys or connection URLs belong in Git. Copy `.env.example` to `.env` for local variables; `.env`, dumps and encrypted dumps are ignored. GitHub Actions runs the test suite and dependency vulnerability audit on every push and pull request. Dependabot proposes weekly Python and GitHub Actions updates. Report security issues privately as described in [SECURITY.md](SECURITY.md). The Render Blueprint disables automatic production deploys, so a tested commit must be deployed deliberately and can be rolled back to a previous Render release.

## Structure

```text
rallylog/
  rallylog/__init__.py     application setup and import command
  rallylog/models.py       database tables
  rallylog/importer.py     historical match import
  rallylog/stats.py        transparent statistics
  rallylog/prize_money.py  optional Wikidata figure
  rallylog/routes.py       pages and forms
  rallylog/security.py     tokens, email and persistent abuse limits
  rallylog/templates/     HTML pages
  rallylog/static/        CSS and favicon
  data/                   credited starter and deployment catalog
  scripts/                catalog and database administration helpers
  tests/                  critical user-flow tests
  .github/workflows/      tests, initialization and encrypted backups
  render.yaml             public web service configuration
  wsgi.py                 web server entry point
```
