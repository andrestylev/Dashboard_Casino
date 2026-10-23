# Casino Admin Dashboard

Administrative web dashboard for an online casino (single brand, single currency), backed by PostgreSQL
with realistic mock data. Roles: `super_admin` and `support`, with TOTP 2FA.

**Stack:** FastAPI + SQLAlchemy + PostgreSQL (backend), React + Vite (frontend, from Phase 4).

## Status

- Phase 0 (done): foundations + packaging spike, verified on a clean Windows PC.
- Phase 1 (done): data model, Alembic migration and schema tests. See [docs/erd.md](docs/erd.md).
- Phase 2 (done): reproducible fictional casino data, risk patterns and a SQL dump for local demos.
- Phase 3 (done): administrator authentication with TOTP, recovery codes, session cookies, audit
  logging and protected, filterable read APIs.

`web/dist/index.html` is still only the spike check page, not the real UI.

## Layout

```
api/                 FastAPI app, requirements, tests, Dockerfile
api/app/models/      SQLAlchemy models (one module per area)
api/alembic/         Database migrations
api/scripts/         Helper scripts (ERD and mock-data generators)
docs/                Generated database diagram
web/                 Frontend (web/dist = built files served by the API)
seed/                PostgreSQL schema-and-data dump loaded on first run
packaging/windows/   Portable bundle for presenting on a PC without admin rights
docker-compose.yml   Dev stack: PostgreSQL + API with hot reload
```

## Develop

```
docker compose up --build                       # http://localhost:8000  (API docs: /api/docs)
docker compose run --rm api alembic upgrade head   # create/upgrade the schema
docker compose run --rm api python -m pytest -q tests   # tests need the db service
```

## Phase 3 API and authentication

The API is documented at `http://localhost:8000/api/docs`. Unless otherwise noted, routes below
require an authenticated administrator session:

| Route | Purpose |
| --- | --- |
| `POST /api/auth/login` | Verify email/password and TOTP or recovery code; starts TOTP enrollment for an account that has not enrolled yet. |
| `POST /api/auth/totp/enable` | Confirm initial TOTP enrollment and return ten one-time recovery codes. |
| `POST /api/auth/refresh` | Rotate the session token and extend its 12-hour lifetime. |
| `POST /api/auth/logout` | Revoke the current session and clear its cookie. |
| `GET /api/auth/me` | Return the signed-in administrator and role. |
| `GET /api/players`, `GET /api/players/{id}` | Search and view players, including wallet balance. |
| `GET /api/games` | Filter games by category, provider, active status or name. |
| `GET /api/transactions` | Filter transactions by player, type, status or date range. |
| `GET /api/bets` | Filter bets by player, game, win status or date range. |
| `GET /api/risk-alerts` | Filter risk alerts by player, type, severity, status or date range. |
| `GET /api/audit-log` | Search the audit trail; restricted to `super_admin`. |

List routes return `{items, total, page, page_size}` and support `page` and `page_size` (maximum
100). A seeded administrator's first login returns a TOTP provisioning URI; add it to an
authenticator app, then submit the current code to `/api/auth/totp/enable`. The recovery codes in
that response are shown only once; only their hashes are stored, and each code can be used once.
Five failed login or enrollment attempts lock the account for 15 minutes. Login, session and
authentication-failure events are written to the audit log.

The session token is opaque, stored hashed in PostgreSQL, and delivered in an HttpOnly,
SameSite=Strict cookie scoped to `/api`. For HTTPS deployments, set `SECURE_AUTH_COOKIES=true`.
This project is currently a local demo: TOTP shared secrets are stored in the database without
application-level encryption, so do not reuse its setup as a production security configuration.

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

See [packaging/windows/README.md](packaging/windows/README.md).
