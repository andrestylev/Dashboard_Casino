from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.security import password_hasher


@pytest.fixture
def metrics_client(conn):
    role_id = conn.execute(
        text("INSERT INTO roles (name) VALUES ('super_admin') RETURNING id")
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO admin_users "
            "(username, email, password_hash, full_name, role_id) "
            "VALUES ('metrics_admin', 'metrics@example.test', :password_hash, 'Metrics Admin', :role_id)"
        ),
        {"password_hash": password_hasher.hash("metrics-test-password"), "role_id": role_id},
    )

    def override_get_db():
        with Session(bind=conn, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        login = client.post(
            "/api/auth/login",
            json={"username": "metrics_admin", "password": "metrics-test-password"},
        )
        assert login.status_code == 200
        yield client
    app.dependency_overrides.clear()


def seed_metrics_rows(conn):
    player_ids = []
    for index in range(2):
        player_id = conn.execute(
            text(
                "INSERT INTO players "
                "(username, email, first_name, last_name, birth_date, country_code, registration_channel) "
                "VALUES (:username, :email, 'Test', 'Player', '1990-01-01', 'CO', 'web') "
                "RETURNING id"
            ),
            {"username": f"metrics_player_{index}", "email": f"metrics_{index}@example.test"},
        ).scalar_one()
        conn.execute(
            text("INSERT INTO wallets (player_id, balance) VALUES (:player_id, 0)"),
            {"player_id": player_id},
        )
        player_ids.append(player_id)

    category_id = conn.execute(
        text("INSERT INTO game_categories (code, name) VALUES ('metrics', 'Metrics') RETURNING id")
    ).scalar_one()
    game_id = conn.execute(
        text(
            "INSERT INTO games "
            "(category_id, name, provider, theoretical_rtp, volatility, min_bet, max_bet) "
            "VALUES (:category_id, 'Metrics Game', 'Test', 95, 'medium', 1, 100) RETURNING id"
        ),
        {"category_id": category_id},
    ).scalar_one()
    session_ids = [
        conn.execute(
            text(
                "INSERT INTO game_sessions (player_id, game_id, device_type) "
                "VALUES (:player_id, :game_id, 'desktop') RETURNING id"
            ),
            {"player_id": player_id, "game_id": game_id},
        ).scalar_one()
        for player_id in player_ids
    ]

    bets = [
        (session_ids[0], "2026-01-01 12:00:00+00", 20, 5),
        (session_ids[1], "2026-01-01 23:59:59+00", 10, 15),
        (session_ids[0], "2026-01-03 00:00:00+00", 30, 0),
        (session_ids[1], "2025-12-31 23:59:59+00", 100, 0),
    ]
    for session_id, placed_at, stake, payout in bets:
        conn.execute(
            text(
                "INSERT INTO bets (session_id, placed_at, stake, payout) "
                "VALUES (:session_id, :placed_at, :stake, :payout)"
            ),
            {
                "session_id": session_id,
                "placed_at": placed_at,
                "stake": stake,
                "payout": payout,
            },
        )

    current_bet = datetime.now(UTC).replace(day=1, hour=12, minute=0, second=0, microsecond=0)
    conn.execute(
        text("INSERT INTO bets (session_id, placed_at, stake, payout) VALUES (:s, :t, 7, 2)"),
        {"s": session_ids[0], "t": current_bet},
    )

    transactions = [
        ("deposit", "completed", 50, "2026-01-01 09:00:00+00", "card"),
        ("withdrawal", "completed", 12, "2026-01-02 09:00:00+00", "card"),
        ("deposit", "pending", 500, None, "card"),
        ("deposit", "completed", 1000, "2025-12-31 12:00:00+00", "card"),
    ]
    for kind, status, amount, completed_at, method in transactions:
        created_at = completed_at or "2026-01-01 08:00:00+00"
        conn.execute(
            text(
                "INSERT INTO transactions "
                "(player_id, type, status, amount, method, created_at, completed_at) "
                "VALUES (:player_id, :type, :status, :amount, :method, :created_at, :completed_at)"
            ),
            {
                "player_id": player_ids[0],
                "type": kind,
                "status": status,
                "amount": amount,
                "method": method,
                "created_at": created_at,
                "completed_at": completed_at,
            },
        )


def test_dashboard_metrics_aggregate_and_fill_daily_dates(conn, metrics_client):
    seed_metrics_rows(conn)

    response = metrics_client.get(
        "/api/dashboard/metrics?start_date=2026-01-01&end_date=2026-01-03"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["bets_count"] == 3
    assert result["active_players"] == 2
    assert Decimal(result["ggr"]) == Decimal("40.00")
    assert Decimal(result["deposits"]) == Decimal("50.00")
    assert Decimal(result["withdrawals"]) == Decimal("12.00")
    assert [day["date"] for day in result["daily"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert [Decimal(day["ggr"]) for day in result["daily"]] == [
        Decimal("10.00"),
        Decimal("0.00"),
        Decimal("30.00"),
    ]
    assert [Decimal(day["deposits"]) for day in result["daily"]] == [
        Decimal("50.00"),
        Decimal("0.00"),
        Decimal("0.00"),
    ]
    assert [Decimal(day["withdrawals"]) for day in result["daily"]] == [
        Decimal("0.00"),
        Decimal("12.00"),
        Decimal("0.00"),
    ]


def test_dashboard_all_time_distributions_monthly_ggr_and_heatmap(conn, metrics_client):
    seed_metrics_rows(conn)
    today = datetime.now(UTC).date()
    conn.execute(
        text(
            "UPDATE players SET registration_channel = 'mobile', vip_tier = 'gold', "
            "birth_date = :birth_date, registered_at = :registered_at "
            "WHERE username = 'metrics_player_1'"
        ),
        {
            "birth_date": date(today.year - 35, today.month, today.day),
            "registered_at": datetime.now(UTC) - timedelta(days=210),
        },
    )
    conn.execute(
        text("UPDATE players SET birth_date = :birth_date WHERE username = 'metrics_player_0'"),
        {"birth_date": date(today.year - 25, today.month, today.day)},
    )

    response = metrics_client.get(
        "/api/dashboard/metrics?start_date=2026-01-01&end_date=2026-01-03"
    )

    assert response.status_code == 200
    result = response.json()
    assert Decimal(result["all_time_ggr"]) == Decimal("145.00")
    assert {item["key"]: item["count"] for item in result["registration_channels"]} == {
        "web": 1,
        "mobile": 1,
    }
    assert {item["key"]: item["percentage"] for item in result["registration_channels"]} == {
        "web": 50.0,
        "mobile": 50.0,
    }
    assert {item["key"]: item["count"] for item in result["vip_tiers"]} == {
        "standard": 1,
        "silver": 0,
        "gold": 1,
        "platinum": 0,
        "diamond": 0,
    }
    assert {item["key"]: item["percentage"] for item in result["vip_tiers"]} == {
        "standard": 50.0,
        "silver": 0.0,
        "gold": 50.0,
        "platinum": 0.0,
        "diamond": 0.0,
    }
    age_counts = {item["key"]: item["count"] for item in result["age_bands"]}
    age_percentages = {item["key"]: item["percentage"] for item in result["age_bands"]}
    assert age_counts["18-25"] == 1
    assert age_counts["26-35"] == 1
    assert age_percentages["18-25"] == age_percentages["26-35"] == 50.0
    assert len(result["monthly_ggr"]) == 6
    this_month = today.replace(day=1).isoformat()
    current_month = next(item for item in result["monthly_ggr"] if item["month"] == this_month)
    assert Decimal(current_month["ggr"]) == Decimal("5.00")
    assert sum(item["bets_count"] for item in result["bet_heatmap"]) == 5
    assert len(result["bet_heatmap"]) == 7 * 24
    heatmap = {
        (cell["weekday"], cell["hour"]): cell["bets_count"]
        for cell in result["bet_heatmap"]
    }
    assert heatmap[(3, 12)] >= 1  # Thursday 12:00 UTC
    assert heatmap[(3, 23)] >= 1  # Thursday 23:00 UTC
    assert heatmap[(5, 0)] >= 1  # Saturday 00:00 UTC
    assert heatmap[(2, 23)] >= 1  # Wednesday 23:00 UTC


def test_dashboard_registration_channel_period_filters_players(conn, metrics_client):
    seed_metrics_rows(conn)
    conn.execute(
        text(
            "UPDATE players SET registration_channel = 'mobile', registered_at = "
            "(now() AT TIME ZONE 'UTC') - interval '7 months' "
            "WHERE username = 'metrics_player_1'"
        )
    )

    response = metrics_client.get(
        "/api/dashboard/metrics?start_date=2026-01-01&end_date=2026-01-03&registration_months=1"
    )

    assert response.status_code == 200
    result = response.json()
    assert result["registration_channel_period"] == "1"
    assert {item["key"]: item["count"] for item in result["registration_channels"]} == {
        "web": 1,
        "mobile": 0,
    }
    assert {item["key"]: item["percentage"] for item in result["registration_channels"]} == {
        "web": 100.0,
        "mobile": 0.0,
    }


def test_dashboard_metrics_empty_period_and_date_validation(metrics_client):
    empty = metrics_client.get(
        "/api/dashboard/metrics?start_date=2026-02-01&end_date=2026-02-02"
    )
    assert empty.status_code == 200
    assert empty.json()["bets_count"] == 0
    assert empty.json()["active_players"] == 0
    assert len(empty.json()["daily"]) == 2
    assert Decimal(empty.json()["all_time_ggr"]) == Decimal("0.00")
    assert all(item["count"] == 0 and item["percentage"] == 0 for item in empty.json()["vip_tiers"])
    assert all(item["count"] == 0 and item["percentage"] == 0 for item in empty.json()["age_bands"])
    assert len(empty.json()["monthly_ggr"]) == 6
    assert len(empty.json()["bet_heatmap"]) == 7 * 24
    assert all(cell["bets_count"] == 0 for cell in empty.json()["bet_heatmap"])

    inverted = metrics_client.get(
        "/api/dashboard/metrics?start_date=2026-02-02&end_date=2026-02-01"
    )
    assert inverted.status_code == 422

    too_wide = metrics_client.get(
        "/api/dashboard/metrics?start_date=2025-01-01&end_date=2026-01-02"
    )
    assert too_wide.status_code == 422


def test_dashboard_metrics_requires_authentication():
    with TestClient(app) as client:
        response = client.get(
            "/api/dashboard/metrics?start_date=2026-01-01&end_date=2026-01-30"
        )
    assert response.status_code == 401
