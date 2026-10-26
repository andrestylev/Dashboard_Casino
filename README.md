# Casino Admin Dashboard

Administrative web dashboard for an online casino (single brand, single currency), backed by PostgreSQL
with realistic mock data. Roles: `super_admin` and `support`, with username/password sign-in.

**Stack:** FastAPI + SQLAlchemy + PostgreSQL (backend), React + Vite + TypeScript (frontend).

## Status

- Phase 0 (done): foundations + packaging spike, verified on a clean Windows PC.
- Phase 1 (done): data model, Alembic migration and schema tests. See [docs/erd.md](docs/erd.md).
- Phase 2 (done): reproducible fictional casino data, risk patterns and a SQL dump for local demos.
- Phase 3 (done): administrator sessions, audit logging and protected, filterable read APIs.
- Phase 4 (done): protected React dashboard shell, username/password sign-in and server-paginated
  data tables.
- Phase 5 (done): live KPIs, player insights, daily/monthly trends and activity heatmap.
- Phase 6 (done): filtered detail views, audited risk/player/game management and CSV export.
- Phase 7 (done): query-plan review, responsive/accessibility improvements and browser E2E tests.
- Phase 8 (in progress): final portable Windows bundle and presentation rehearsal.

The Windows packaging spike is preserved; Phase 8 updates it with the current application and a
rehearsed presentation package.

## Layout

```
api/                 FastAPI app, requirements, tests, Dockerfile
api/app/models/      SQLAlchemy models (one module per area)
api/alembic/         Database migrations
api/scripts/         Helper scripts (ERD and mock-data generators)
docs/                Generated database diagram
web/                 Frontend (Vite dev server; web/dist is served by the API)
seed/                PostgreSQL schema-and-data dump loaded on first run
packaging/windows/   Portable bundle for presenting on a PC without admin rights
docker-compose.yml   Dev stack: PostgreSQL + API + Vite with hot reload
```

## Develop

```
docker compose up --build                       # http://localhost:5173 (live frontend)
                                                 # http://localhost:8000 (built app/API docs: /api/docs)
docker compose run --rm api alembic upgrade head   # create/upgrade the schema
docker compose run --rm api python -m pytest -q tests   # tests need the db service
```

### Frontend development

The `web` service starts the Vite development server with hot module replacement. Open
`http://localhost:5173`, then save files under `web/src/` to see the browser update immediately.
The container uses polling so source-file changes are detected reliably through Docker Desktop on
Windows. API requests to `/api` are proxied to the API service, keeping session cookies same-origin.

To run Vite directly on the host instead:

```
cd web
npm install
npm run dev
```

Vite proxies `/api` requests to `http://localhost:8000` by default. To build the static app served by
FastAPI at `http://localhost:8000`, run `npm run build` from `web/`; the output is `web/dist/`.
The frontend uses local system fonts and does not require internet access.

The portable Windows ZIP serves this compiled frontend from FastAPI; it does not start Vite, so it
does not hot-reload changes made after the ZIP was built. `packaging/windows/build_bundle.ps1`
automatically runs the frontend build before creating a fresh ZIP. After editing the UI, run that
script and copy/extract the newly generated `dist/casino-demo.zip` to the presentation PC. Node.js
and npm are needed on the build machine only, not on the presentation PC. For live UI changes during
development, use `docker compose up --build` and open `http://localhost:5173`.

### Phase 4 frontend

Administrators sign in with a username and password. New registration asks for a username, full
name, email and a password of at least 12 characters; each request receives the least-privilege
`support` role and remains inactive until a `super_admin` approves it in **Access requests**.
Registration does not send or verify email. Seeded accounts use the email's local part as their
username (for example, `camila.restrepo`).

The protected navigation includes Dashboard, Players, Games, Transactions, Bets and Risk alerts.
Super admins also see Access requests and the Audit log; the frontend routes and APIs restrict those
pages by role. Collection tables use server-side pagination (10 rows per page); Players and Games
also expose their API search field. The management functions are described in Phase 6 below.
FastAPI serves the built app and falls back to its entry point on frontend routes, so direct links
and page refreshes work as well.

### Phase 5 dashboard metrics

The protected Dashboard is the default page after sign-in. It starts with the latest 30 UTC dates
and provides a shared date range for the Phase 5 cards and daily charts. Metrics refresh
automatically every five seconds while the dashboard is open, and immediately after the selected
dates or registration-channel period changes.

- **GGR:** sum of bet stakes minus payouts, grouped by bet placement date.
- **Completed deposits / withdrawals:** sum of transaction amounts with `completed` status, grouped
  by completion date. Pending and failed transactions are excluded.
- **Active players:** distinct players with one or more bets in the selected range.
- **Bets placed:** count of all bets placed in the selected range.
- Daily charts show GGR and completed deposits/withdrawals. Days without activity display as zero.
- An all-time GGR card sums stakes minus payouts across all bets. The six-month GGR chart has one
  bar per UTC calendar month, including the current (possibly partial) month.
- Player insights show the Web/Mobile **registration channel** distribution (all time by default,
  with last-month, last-3-months and last-6-months filters), all-time VIP-tier distribution and
  current-age bands (18–25, 26–35, 36–45, 46–55 and 56+), each with counts and percentages. Age is
  calculated from birth date and the current UTC date.
- The all-time bet-activity heatmap groups counts by UTC weekday and hour.

The database records a player's registration channel, not the device used for each login. Therefore
the Web/Mobile donut describes registration source and must not be interpreted as actual login or
connection activity.

The metrics API is
`GET /api/dashboard/metrics?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD&registration_months=all`,
where `registration_months` accepts `all`, `1`, `3` or `6`.
Date boundaries use UTC, both selected dates are included, and ranges longer than 366 days or with
an end date before the start date return `422`. The endpoint requires an authenticated administrator
session and aggregates in PostgreSQL rather than loading full transaction or bet tables into memory.

### Language and appearance

The dashboard UI is available in English and Spanish. On first use it follows the browser language
(Spanish when the browser locale is Spanish, otherwise English); choose a language from the flag
selector in the login screen or top bar to save that preference in this browser. User- and
database-provided values such as names, usernames and game names are not translated.

The initial color theme follows the operating system's light/dark preference and updates when that
system setting changes. Use the theme button on the login screen or top bar to explicitly switch
between light and dark; an explicit selection is saved in this browser and takes precedence over the
system setting.

### Phase 6 management and risk

Management tables support combined server-side filters, record detail panels, and CSV downloads
for all rows matching the applied filters (not only the visible page). CSV exports are limited to
10,000 rows; a larger export returns `413`, so apply more filters and retry. Exports are audited,
CSV text cells are protected against spreadsheet formula injection, and downloads are marked
`no-store`.

- **Players:** filter by status, KYC, VIP tier, country, or registration dates; inspect the full
  profile. Only `super_admin` can change status or close an account. Closed accounts cannot be
  reactivated; active self-exclusion cannot be overridden.
- **Games:** filter by category, provider, and availability; inspect catalog details. Only
  `super_admin` can activate or deactivate a game. This does not change historical bets.
- **Risk alerts:** filter by player, signal, severity, status, or creation dates. Both roles can
  assign an open alert to themselves for review, then resolve or dismiss it with a required note.
  Resolved/dismissed alerts are final.
- **Transactions and bets:** provide detail views and filters but remain immutable from this
  dashboard; there are no balance adjustments or financial write actions in this phase.
- All management mutations are recorded in `audit_log`, and authorization is enforced by the API
  as well as by role-aware frontend controls.

### Phase 7 performance, accessibility and responsive checks

The dashboard's main aggregate and list queries were reviewed with PostgreSQL `EXPLAIN ANALYZE`
against the seeded demo database. Existing date and registration indexes are used by the selective
date-range queries. On this local sample, the 30-day bets aggregate took about 20 ms, daily GGR
about 10 ms, all-time GGR about 19 ms, and the all-time activity heatmap about 42 ms. These are
development measurements, not production benchmarks; no extra indexes were added because the
observed plans and timings did not justify their write/storage cost.

The frontend includes semantic labels and regions, visible keyboard focus, reduced-motion support,
and a keyboard-operable responsive navigation menu. Playwright E2E tests check preference
persistence, login/dashboard navigation, mobile overflow and navigation, and automated WCAG 2/2.1
A/AA rules on login, dashboard (light and dark themes), and the mobile player table.

Run the frontend checks from the repository root:

```
cd web
npm ci
npm exec playwright install chromium
npm run build
npm run test:e2e
```

The E2E tests mock API responses and run Vite locally, so they do not require the database or API
containers. CI installs Chromium, builds the frontend and runs the same suite.

New management routes:

| Route | Purpose |
| --- | --- |
| `GET /api/games/{id}/detail`, `GET /api/transactions/{id}/detail` | Read a game or transaction detail record. |
| `GET /api/bets/{id}/detail`, `GET /api/risk-alerts/{id}/detail` | Read a bet or risk-alert detail record. |
| `PATCH /api/players/{id}/status` | Change player status; `super_admin` only. |
| `PATCH /api/games/{id}/status` | Change game availability; `super_admin` only. |
| `PATCH /api/risk-alerts/{id}` | Assign for review, resolve, or dismiss with a note; both admin roles. |
| `GET /api/exports/{resource}.csv` | Export filtered players, games, transactions, bets or risk alerts (maximum 10,000 rows). |

## Phase 3 API and authentication

The API is documented at `http://localhost:8000/api/docs`. Unless otherwise noted, routes below
require an authenticated administrator session:

| Route | Purpose |
| --- | --- |
| `POST /api/auth/login` | Verify administrator username and password. |
| `POST /api/auth/register` | Request a support account using username, full name, email and password; approval is required before sign-in. |
| `POST /api/auth/refresh` | Rotate the session token and extend its 12-hour lifetime. |
| `POST /api/auth/logout` | Revoke the current session and clear its cookie. |
| `GET /api/auth/me` | Return the signed-in administrator and role. |
| `GET /api/dashboard/metrics` | Return date-filtered KPIs and daily trends for the authenticated administrator. |
| `GET /api/admin/pending-registrations` | List account requests; restricted to `super_admin`. |
| `POST /api/admin/users/{id}/approve` | Approve a registration as `support`; restricted to `super_admin`. |
| `GET /api/players`, `GET /api/players/{id}` | Search and view players, including wallet balance. |
| `PATCH /api/players/{id}/status` | Change player status; restricted to `super_admin`. |
| `GET /api/games` | Filter games by category, provider, active status or name. |
| `PATCH /api/games/{id}/status` | Change game availability; restricted to `super_admin`. |
| `GET /api/transactions` | Filter transactions by player, type, status or date range. |
| `GET /api/bets` | Filter bets by player, game, win status or date range. |
| `GET /api/risk-alerts`, `PATCH /api/risk-alerts/{id}` | Filter alerts and progress them through review/resolution. |
| `GET /api/exports/{resource}.csv` | Export up to 10,000 rows matching filters; emits an audit event. |
| `GET /api/audit-log` | Search the audit trail; restricted to `super_admin`. |

List routes return `{items, total, page, page_size}` and support `page` and `page_size` (maximum
100). Five failed login attempts lock the account for 15 minutes. Login, session, registration and
authentication-failure events are written to the audit log.

The session token is opaque, stored hashed in PostgreSQL, and delivered in an HttpOnly,
SameSite=Strict cookie scoped to `/api`. For HTTPS deployments, set `SECURE_AUTH_COOKIES=true`.
This demo uses password-only authentication; restrict it to the local presentation environment and
do not expose it directly to the public internet.

The demo database is initialized from `seed/casino_demo.sql` when PostgreSQL creates its data
volume for the first time. To generate or refresh the dump without replacing the database you use
for development, create a separate export database:

```
docker compose up --build -d db
docker compose exec -T db createdb -U postgres casino_seed_export
docker compose run --rm -e DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/casino_seed_export api alembic upgrade head
docker compose run --rm -e DATABASE_URL=postgresql+psycopg://postgres:postgres@db:5432/casino_seed_export api python -m scripts.seed --database-url postgresql+psycopg://postgres:postgres@db:5432/casino_seed_export --seed 42 --as-of 2026-10-23
docker compose exec -T db pg_dump -U postgres -d casino_seed_export --no-owner --no-privileges > seed/casino_demo.sql
```

The database initializer also runs `seed/zzz_admin_usernames.sql`, adding the username column to
older dumps. If an existing development database was initialized from the old dump and has no
Alembic revision, run `docker compose run --rm api alembic stamp 0001` once, then
`docker compose run --rm api alembic upgrade head`. Check `alembic current` first; do not stamp a
database that already has a revision. Generate future seed dumps only from a database migrated to
`head`.

The default dataset contains 1,200 fictional players and 180 days of activity. Choose a fixed
`--as-of` date with the same `--seed` to reproduce the same rows. `--reset` replaces the data in
the configured database; use it only with the disposable export database. For later refreshes,
omit the `createdb` and migration commands and add `--reset` to the generator command. The
generator checks wallet ledgers, balances, dates, and injected risk alerts before committing.

PowerShell users should use a modern PowerShell with UTF-8 native-command redirection, or run the
command through `cmd /c` to preserve the SQL file's encoding. Rebuild the Windows bundle after
refreshing the dump. Demo administrator accounts use the password printed by the generator; these
credentials and all generated records are fictional and are for local presentations only.

Change the schema: edit the models in `api/app/models/`, then

```
docker compose run --rm api alembic revision --autogenerate -m "describe the change"
# review the generated file in api/alembic/versions/, then:
docker compose run --rm api alembic upgrade head
python api/scripts/generate_erd.py              # refresh docs/erd.md
```

`test_models_match_migrations` fails if a model changes without a migration.

Without Docker:

```
python -m venv .venv && .venv\Scripts\activate       # Windows
pip install -r api/requirements-dev.txt
ruff check .
pytest                      # schema and seed tests need PostgreSQL: set TEST_DATABASE_URL (see .env.example)
```

## Present on another PC

See [packaging/windows/README.md](packaging/windows/README.md) for building and running the
self-contained Windows package. The presentation account `andres.molina` uses the default demo
password `Demo-Casino-2026!`; credentials and data are fictional. The bundle uses its own Python and
PostgreSQL binaries and selects free local ports, so preinstalled versions do not need to be changed
or stopped and no administrator permission is required.
