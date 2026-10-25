import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.main import app
from app.security import password_hasher

PASSWORD = "management-test-password"


def create_management_admin(conn, role):
    role_id = conn.execute(
        text("INSERT INTO roles (name) VALUES (:role) RETURNING id"),
        {"role": role},
    ).scalar_one()
    return conn.execute(
        text(
            "INSERT INTO admin_users "
            "(username, email, password_hash, full_name, role_id) "
            "VALUES (:username, :email, :password_hash, :full_name, :role_id) RETURNING id"
        ),
        {
            "username": f"phase6_{role}",
            "email": f"phase6_{role}@example.test",
            "password_hash": password_hasher.hash(PASSWORD),
            "full_name": f"Phase 6 {role}",
            "role_id": role_id,
        },
    ).scalar_one()


@pytest.fixture
def api_client(conn):
    def override_get_db():
        with Session(bind=conn, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def seed_management_records(conn):
    player_id = conn.execute(
        text(
            "INSERT INTO players "
            "(username, email, first_name, last_name, birth_date, country_code, registration_channel) "
            "VALUES ('phase6_player', 'phase6_player@example.test', 'Demo', 'Player', "
            "'1990-01-01', 'CO', 'web') RETURNING id"
        )
    ).scalar_one()
    conn.execute(
        text("INSERT INTO wallets (player_id, balance) VALUES (:player_id, 25)"),
        {"player_id": player_id},
    )
    category_id = conn.execute(
        text(
            "INSERT INTO game_categories (code, name) VALUES ('phase6', 'Phase 6') RETURNING id"
        )
    ).scalar_one()
    game_id = conn.execute(
        text(
            "INSERT INTO games "
            "(category_id, name, provider, theoretical_rtp, volatility, min_bet, max_bet) "
            "VALUES (:category_id, 'Phase 6 Game', 'Demo Provider', 96, 'low', 1, 50) RETURNING id"
        ),
        {"category_id": category_id},
    ).scalar_one()
    session_id = conn.execute(
        text(
            "INSERT INTO game_sessions (player_id, game_id, device_type) "
            "VALUES (:player_id, :game_id, 'desktop') RETURNING id"
        ),
        {"player_id": player_id, "game_id": game_id},
    ).scalar_one()
    bet_id = conn.execute(
        text(
            "INSERT INTO bets (session_id, stake, payout) VALUES (:session_id, 5, 2) RETURNING id"
        ),
        {"session_id": session_id},
    ).scalar_one()
    transaction_id = conn.execute(
        text(
            "INSERT INTO transactions (player_id, type, status, amount, method) "
            "VALUES (:player_id, 'deposit', 'pending', 10, 'card') RETURNING id"
        ),
        {"player_id": player_id},
    ).scalar_one()
    alert_id = conn.execute(
        text(
            "INSERT INTO risk_alerts (player_id, alert_type, severity, details) "
            "VALUES (:player_id, 'rapid_deposits', 'high', '{\"count\": 3}'::jsonb) RETURNING id"
        ),
        {"player_id": player_id},
    ).scalar_one()
    return player_id, game_id, transaction_id, bet_id, alert_id


@pytest.fixture
def management_context(conn, api_client):
    super_admin_id = create_management_admin(conn, "super_admin")
    support_id = create_management_admin(conn, "support")
    ids = seed_management_records(conn)
    return api_client, ids, super_admin_id, support_id


def login(client, username):
    response = client.post(
        "/api/auth/login",
        json={"username": f"phase6_{username}", "password": PASSWORD},
    )
    assert response.status_code == 200


def test_management_details_and_role_protected_status_updates(management_context, conn):
    (
        client,
        (player_id, game_id, transaction_id, bet_id, alert_id),
        super_admin_id,
        _,
    ) = management_context
    login(client, "support")

    assert (
        client.patch(
            f"/api/players/{player_id}/status", json={"status": "suspended"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/games/{game_id}/status", json={"is_active": False}
        ).status_code
        == 403
    )
    assert client.get(f"/api/games/{game_id}/detail").json()["name"] == "Phase 6 Game"
    assert client.get(f"/api/transactions/{transaction_id}/detail").status_code == 200
    assert client.get(f"/api/bets/{bet_id}/detail").status_code == 200
    assert client.get(f"/api/risk-alerts/{alert_id}/detail").json()["details"] == {
        "count": 3
    }

    client.post("/api/auth/logout")
    login(client, "super_admin")
    changed_player = client.patch(
        f"/api/players/{player_id}/status", json={"status": "suspended"}
    )
    changed_game = client.patch(
        f"/api/games/{game_id}/status", json={"is_active": False}
    )
    assert changed_player.status_code == changed_game.status_code == 200
    assert changed_player.json()["status"] == "suspended"
    assert changed_player.json()["wallet_balance"] == "25.00"
    assert changed_game.json()["is_active"] is False
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE admin_user_id = :admin_id "
                "AND action IN ('player.status_changed', 'game.availability_changed')"
            ),
            {"admin_id": super_admin_id},
        ).scalar_one()
        == 2
    )


def test_risk_alert_requires_review_and_resolution_note(management_context, conn):
    client, (_, _, _, _, alert_id), _, support_id = management_context
    login(client, "support")

    direct_resolution = client.patch(
        f"/api/risk-alerts/{alert_id}",
        json={"status": "resolved", "resolution_note": "Reviewed"},
    )
    assert direct_resolution.status_code == 409
    assert (
        client.patch(
            f"/api/risk-alerts/{alert_id}", json={"status": "in_review"}
        ).status_code
        == 200
    )
    missing_note = client.patch(
        f"/api/risk-alerts/{alert_id}", json={"status": "resolved"}
    )
    assert missing_note.status_code == 422
    resolved = client.patch(
        f"/api/risk-alerts/{alert_id}",
        json={"status": "resolved", "resolution_note": "Reviewed and cleared"},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolution_note"] == "Reviewed and cleared"
    assert resolved.json()["assigned_to_admin_id"] == support_id
    assert (
        conn.execute(
            text("SELECT count(*) FROM audit_log WHERE resource_type = 'risk_alert'")
        ).scalar_one()
        == 2
    )
    assert (
        client.patch(
            f"/api/risk-alerts/{alert_id}", json={"status": "in_review"}
        ).status_code
        == 409
    )


def test_filtered_csv_exports_all_matching_rows_and_audits(management_context, conn):
    client, (_, _, _, _, _), _, support_id = management_context
    conn.execute(
        text(
            "INSERT INTO players "
            "(username, email, first_name, last_name, birth_date, country_code, registration_channel) "
            "VALUES ('phase6_other', 'phase6_other@example.test', 'Other', 'Player', "
            "'1990-01-01', 'CO', 'mobile')"
        )
    )
    login(client, "support")
    response = client.get("/api/exports/players.csv", params={"country_code": "CO"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["x-exported-count"] == "2"
    assert (
        response.headers["content-disposition"] == 'attachment; filename="players.csv"'
    )
    assert "wallet_balance" in response.text
    assert "phase6_player" in response.text
    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM audit_log WHERE action = 'data.export_csv' "
                "AND admin_user_id = :admin_id AND resource_type = 'players'"
            ),
            {"admin_id": support_id},
        ).scalar_one()
        == 1
    )


@pytest.mark.parametrize(
    ("resource", "filters", "expected_value"),
    [
        ("games", {"is_active": "true"}, "Phase 6 Game"),
        ("transactions", {"status": "pending"}, "deposit"),
        ("bets", {"is_win": "false"}, "5.00"),
        ("risk-alerts", {"severity": "high"}, "rapid_deposits"),
    ],
)
def test_csv_export_filters_each_supported_resource(
    management_context, resource, filters, expected_value
):
    client, _, _, _ = management_context
    login(client, "support")

    response = client.get(f"/api/exports/{resource}.csv", params=filters)

    assert response.status_code == 200
    assert response.headers["x-exported-count"] == "1"
    assert expected_value in response.text


def test_csv_formula_prefix_is_neutralized(management_context, conn):
    client, _, _, _ = management_context
    conn.execute(
        text("UPDATE players SET username = '=1+1' WHERE username = 'phase6_player'")
    )
    login(client, "support")
    response = client.get("/api/exports/players.csv")
    assert response.status_code == 200
    assert "'=1+1" in response.text


def test_player_self_exclusion_and_closed_account_guards(management_context):
    client, (player_id, _, _, _, _), _, _ = management_context
    login(client, "super_admin")

    cannot_set_exclusion = client.patch(
        f"/api/players/{player_id}/status", json={"status": "self_excluded"}
    )
    assert cannot_set_exclusion.status_code == 422
    closed = client.patch(f"/api/players/{player_id}/status", json={"status": "closed"})
    assert closed.status_code == 200
    cannot_reopen = client.patch(
        f"/api/players/{player_id}/status", json={"status": "active"}
    )
    assert cannot_reopen.status_code == 409


def test_active_self_exclusion_cannot_be_overridden(management_context, conn):
    client, (player_id, _, _, _, _), _, _ = management_context
    conn.execute(
        text(
            "UPDATE players SET status = 'self_excluded', "
            "self_exclusion_until = now() + interval '1 day' WHERE id = :player_id"
        ),
        {"player_id": player_id},
    )
    login(client, "super_admin")

    detail = client.get(f"/api/players/{player_id}")
    assert detail.status_code == 200
    assert detail.json()["self_exclusion_until"] is not None
    cannot_reactivate = client.patch(
        f"/api/players/{player_id}/status", json={"status": "active"}
    )
    assert cannot_reactivate.status_code == 409
    can_close = client.patch(
        f"/api/players/{player_id}/status", json={"status": "closed"}
    )
    assert can_close.status_code == 200


def test_csv_export_requires_auth_and_enforces_row_limit(
    management_context, monkeypatch
):
    client, _, _, _ = management_context
    client.post("/api/auth/logout")
    assert client.get("/api/exports/players.csv").status_code == 401

    login(client, "support")
    import app.api.management as management

    monkeypatch.setattr(management, "CSV_EXPORT_LIMIT", 0)
    response = client.get("/api/exports/players.csv")
    assert response.status_code == 413
