"""Schema tests: constraints are enforced by PostgreSQL itself, not only by the app."""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers

from app.models import Base

EXPECTED_TABLES = {
    "admin_recovery_codes", "admin_sessions", "admin_users", "audit_log", "bets", "bonuses",
    "game_categories", "game_sessions", "games", "player_notes", "players", "risk_alerts",
    "roles", "transactions", "wallets",
}  # fmt: skip


# ---------- helpers -------------------------------------------------------------------------

def insert(conn, sql, **params):
    return conn.execute(text(sql), params).scalar_one()


def violates(conn, constraint, sql, **params):
    """Run `sql` and assert PostgreSQL rejects it because of `constraint`."""
    with pytest.raises(IntegrityError) as exc:
        with conn.begin_nested():
            conn.execute(text(sql), params)
    assert constraint in str(exc.value)


def make_admin(conn):
    role_id = insert(conn, "INSERT INTO roles (name) VALUES (:n) RETURNING id", n=uuid.uuid4().hex[:8])
    return insert(
        conn,
        "INSERT INTO admin_users (email, password_hash, full_name, role_id) "
        "VALUES (:e, 'x', 'Admin', :r) RETURNING id",
        e=f"{uuid.uuid4().hex[:8]}@casino.test", r=role_id,
    )  # fmt: skip


def make_player(conn, birth_date="1990-01-01"):
    tag = uuid.uuid4().hex[:8]
    return insert(
        conn,
        "INSERT INTO players (username, email, first_name, last_name, birth_date, country_code, "
        "registration_channel) VALUES (:u, :e, 'Test', 'Player', :b, 'CO', 'web') RETURNING id",
        u=f"user_{tag}", e=f"{tag}@mail.test", b=birth_date,
    )  # fmt: skip


def make_wallet(conn, player_id, balance=0):
    conn.execute(
        text("INSERT INTO wallets (player_id, balance) VALUES (:p, :b)"), {"p": player_id, "b": balance}
    )
    return player_id


def make_game(conn):
    cat = insert(
        conn, "INSERT INTO game_categories (code, name) VALUES (:c, 'Slots') RETURNING id",
        c=uuid.uuid4().hex[:8],
    )  # fmt: skip
    return insert(
        conn,
        "INSERT INTO games (category_id, name, provider, theoretical_rtp, volatility, min_bet, max_bet) "
        "VALUES (:c, :n, 'Acme', 96.5, 'medium', 0.10, 100) RETURNING id",
        c=cat, n=uuid.uuid4().hex[:8],
    )  # fmt: skip


def make_session(conn, player_id, game_id):
    return insert(
        conn,
        "INSERT INTO game_sessions (player_id, game_id, device_type) "
        "VALUES (:p, :g, 'desktop') RETURNING id",
        p=player_id, g=game_id,
    )  # fmt: skip


# ---------- structure -----------------------------------------------------------------------

def test_mappers_configure():
    configure_mappers()  # raises if any model is inconsistent


def test_expected_tables_exist(engine):
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == EXPECTED_TABLES


def test_models_match_migrations(engine):
    """If this fails, a model changed without a new Alembic migration."""
    with engine.connect() as connection:
        ctx = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(ctx, Base.metadata) == []


# ---------- players, wallets, transactions --------------------------------------------------

def test_players_must_be_adults(conn):
    with pytest.raises(IntegrityError) as exc:
        with conn.begin_nested():
            make_player(conn, birth_date="2020-01-01")
    assert "ck_players_adult_at_registration" in str(exc.value)


def test_player_email_must_be_lowercase(conn):
    violates(
        conn, "ck_players_email_lowercase",
        "INSERT INTO players (username, email, first_name, last_name, birth_date, country_code, "
        "registration_channel) VALUES ('u1', 'Mixed@Case.com', 'A', 'B', '1990-01-01', 'CO', 'web')",
    )  # fmt: skip


def test_wallet_balance_cannot_be_negative(conn):
    player = make_player(conn)
    violates(
        conn, "ck_wallets_balance_non_negative",
        "INSERT INTO wallets (player_id, balance) VALUES (:p, -1)", p=player,
    )  # fmt: skip


def test_transaction_amount_must_be_positive(conn):
    player = make_wallet(conn, make_player(conn))
    violates(
        conn, "ck_transactions_amount_positive",
        "INSERT INTO transactions (player_id, type, amount, method) VALUES (:p, 'deposit', 0, 'card')",
        p=player,
    )  # fmt: skip


def test_payments_need_a_method_and_credits_must_not_have_one(conn):
    player = make_wallet(conn, make_player(conn))
    violates(
        conn, "ck_transactions_method_matches_type",
        "INSERT INTO transactions (player_id, type, amount) VALUES (:p, 'deposit', 10)", p=player,
    )  # fmt: skip
    violates(
        conn, "ck_transactions_method_matches_type",
        "INSERT INTO transactions (player_id, type, amount, method) "
        "VALUES (:p, 'bonus_credit', 10, 'card')", p=player,
    )  # fmt: skip


def test_adjustment_needs_admin_and_note(conn):
    player = make_wallet(conn, make_player(conn))
    violates(
        conn, "ck_transactions_adjustment_needs_admin_and_note",
        "INSERT INTO transactions (player_id, type, amount) VALUES (:p, 'adjustment', 5)", p=player,
    )  # fmt: skip
    admin = make_admin(conn)
    conn.execute(
        text(
            "INSERT INTO transactions (player_id, type, amount, created_by_admin_id, note) "
            "VALUES (:p, 'adjustment', 5, :a, 'goodwill credit')"
        ),
        {"p": player, "a": admin},
    )


def test_completed_at_must_match_status(conn):
    player = make_wallet(conn, make_player(conn))
    violates(
        conn, "ck_transactions_completed_at_matches_status",
        "INSERT INTO transactions (player_id, type, status, amount, method) "
        "VALUES (:p, 'deposit', 'completed', 10, 'card')", p=player,
    )  # fmt: skip


def test_invalid_enum_value_is_rejected(conn):
    player = make_wallet(conn, make_player(conn))
    violates(
        conn, "ck_transactions_transaction_type",
        "INSERT INTO transactions (player_id, type, amount) VALUES (:p, 'refund', 5)", p=player,
    )  # fmt: skip


# ---------- games, sessions, bets -----------------------------------------------------------

def test_session_cannot_end_before_it_starts(conn):
    player, game = make_player(conn), make_game(conn)
    violates(
        conn, "ck_game_sessions_ended_after_started",
        "INSERT INTO game_sessions (player_id, game_id, started_at, ended_at, device_type) "
        "VALUES (:p, :g, '2026-03-01 10:00+00', '2026-03-01 09:00+00', 'mobile')", p=player, g=game,
    )  # fmt: skip


def test_bet_stake_must_be_positive(conn):
    session = make_session(conn, make_player(conn), make_game(conn))
    violates(
        conn, "ck_bets_stake_positive",
        "INSERT INTO bets (session_id, stake, payout) VALUES (:s, 0, 0)", s=session,
    )  # fmt: skip


def test_bet_is_win_is_computed_by_the_database(conn):
    session = make_session(conn, make_player(conn), make_game(conn))
    won = insert(conn, "INSERT INTO bets (session_id, stake, payout) VALUES (:s, 10, 25) RETURNING is_win", s=session)
    lost = insert(conn, "INSERT INTO bets (session_id, stake, payout) VALUES (:s, 10, 0) RETURNING is_win", s=session)
    assert won is True
    assert lost is False


def test_cannot_delete_a_game_that_has_sessions(conn):
    player, game = make_player(conn), make_game(conn)
    make_session(conn, player, game)
    with pytest.raises(IntegrityError) as exc:
        with conn.begin_nested():
            conn.execute(text("DELETE FROM games WHERE id = :g"), {"g": game})
    assert "fk_game_sessions_game_id_games" in str(exc.value)


# ---------- risk ----------------------------------------------------------------------------

def test_alert_resolved_at_must_match_status(conn):
    player = make_player(conn)
    violates(
        conn, "ck_risk_alerts_resolved_at_matches_status",
        "INSERT INTO risk_alerts (player_id, alert_type, severity, status) "
        "VALUES (:p, 'shared_device', 'high', 'resolved')", p=player,
    )  # fmt: skip
    conn.execute(
        text(
            "INSERT INTO risk_alerts (player_id, alert_type, severity, status, resolved_at) "
            "VALUES (:p, 'shared_device', 'high', 'dismissed', now())"
        ),
        {"p": player},
    )


# ---------- materialized view ---------------------------------------------------------------

def test_daily_game_stats_aggregates_bets(conn):
    p1, p2, game = make_player(conn), make_player(conn), make_game(conn)
    s1, s2 = make_session(conn, p1, game), make_session(conn, p2, game)
    conn.execute(
        text(
            "INSERT INTO bets (session_id, stake, payout, placed_at) VALUES "
            "(:s1, 10, 0,  '2026-03-01 10:00+00'),"
            "(:s2, 20, 50, '2026-03-01 23:30+00'),"
            "(:s1, 5,  0,  '2026-03-02 00:10+00')"
        ),
        {"s1": s1, "s2": s2},
    )
    conn.execute(text("REFRESH MATERIALIZED VIEW daily_game_stats"))
    rows = conn.execute(
        text(
            "SELECT stat_date::text, total_bets, unique_players, total_staked, total_paid, ggr "
            "FROM daily_game_stats WHERE game_id = :g ORDER BY stat_date"
        ),
        {"g": game},
    ).all()
    assert [(r[0], r[1], r[2], float(r[3]), float(r[4]), float(r[5])) for r in rows] == [
        ("2026-03-01", 2, 2, 30.0, 50.0, -20.0),
        ("2026-03-02", 1, 1, 5.0, 0.0, 5.0),
    ]


def test_daily_game_stats_has_unique_index_for_concurrent_refresh(conn):
    index = conn.execute(
        text(
            "SELECT indexdef FROM pg_indexes "
            "WHERE indexname = 'uq_daily_game_stats_stat_date_game_id'"
        )
    ).scalar_one()
    assert "UNIQUE" in index
