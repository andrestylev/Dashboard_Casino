from urllib.parse import parse_qs, urlsplit

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.status import HTTP_200_OK, HTTP_202_ACCEPTED, HTTP_401_UNAUTHORIZED

from app.db import get_db
from app.main import app
from app.security import password_hasher, recovery_code_digest

PASSWORD = "test-password-123"


def create_admin(conn, role_name="super_admin", *, totp_enabled=False, secret=None):
    role_id = conn.execute(
        text("INSERT INTO roles (name) VALUES (:name) RETURNING id"),
        {"name": role_name},
    ).scalar_one()
    admin_id = conn.execute(
        text(
            "INSERT INTO admin_users "
            "(email, password_hash, full_name, role_id, totp_enabled, totp_secret) "
            "VALUES (:email, :password_hash, 'Test Admin', :role_id, :enabled, :secret) "
            "RETURNING id"
        ),
        {
            "email": f"{role_name}@example.test",
            "password_hash": password_hasher.hash(PASSWORD),
            "role_id": role_id,
            "enabled": totp_enabled,
            "secret": secret,
        },
    ).scalar_one()
    return admin_id, f"{role_name}@example.test"


def make_client(conn):
    def override_get_db():
        with Session(bind=conn, join_transaction_mode="create_savepoint") as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


@pytest.fixture
def api_client(conn):
    with make_client(conn) as client:
        yield client
    app.dependency_overrides.clear()


def test_totp_enrollment_recovery_rotation_and_logout(conn, api_client):
    create_admin(conn)
    response = api_client.post(
        "/api/auth/login",
        json={"email": "super_admin@example.test", "password": PASSWORD},
    )
    assert response.status_code == HTTP_202_ACCEPTED
    assert response.json()["status"] == "totp_setup_required"
    uri = response.json()["provisioning_uri"]
    secret = parse_qs(urlsplit(uri).query)["secret"][0]

    response = api_client.post(
        "/api/auth/totp/enable",
        json={
            "email": "super_admin@example.test",
            "password": PASSWORD,
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )
    assert response.status_code == HTTP_200_OK
    recovery_codes = response.json()["recovery_codes"]
    assert len(recovery_codes) == 10
    assert api_client.get("/api/auth/me").status_code == HTTP_200_OK

    cookie = api_client.cookies.get("admin_session")
    response = api_client.post("/api/auth/refresh")
    assert response.status_code == HTTP_200_OK
    assert api_client.cookies.get("admin_session") != cookie
    assert api_client.get("/api/auth/me").status_code == HTTP_200_OK

    assert api_client.post("/api/auth/logout").status_code == 204
    assert api_client.get("/api/auth/me").status_code == HTTP_401_UNAUTHORIZED
    response = api_client.post(
        "/api/auth/login",
        json={
            "email": "super_admin@example.test",
            "password": PASSWORD,
            "recovery_code": recovery_codes[0],
        },
    )
    assert response.status_code == HTTP_200_OK
    assert api_client.post("/api/auth/logout").status_code == 204
    response = api_client.post(
        "/api/auth/login",
        json={
            "email": "super_admin@example.test",
            "password": PASSWORD,
            "recovery_code": recovery_codes[0],
        },
    )
    assert response.status_code == HTTP_401_UNAUTHORIZED

    assert (
        conn.execute(
            text(
                "SELECT count(*) FROM admin_recovery_codes "
                "WHERE code_hash = :digest AND used_at IS NOT NULL"
            ),
            {"digest": recovery_code_digest(recovery_codes[0])},
        ).scalar_one()
        == 1
    )


def test_login_failures_are_audited_and_lock_account(conn, api_client):
    create_admin(conn)
    for _ in range(5):
        response = api_client.post(
            "/api/auth/login",
            json={"email": "super_admin@example.test", "password": "wrong-password"},
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED
    attempts, locked_until = conn.execute(
        text("SELECT failed_login_attempts, locked_until FROM admin_users")
    ).one()
    assert attempts == 5
    assert locked_until is not None
    assert (
        conn.execute(
            text("SELECT count(*) FROM audit_log WHERE action = 'auth.login_failed'")
        ).scalar_one()
        == 5
    )


def test_list_endpoints_filter_and_paginate_and_audit_is_super_admin_only(conn, api_client):
    create_admin(conn, role_name="support", totp_enabled=True, secret="JBSWY3DPEHPK3PXP")
    conn.execute(
        text(
            "INSERT INTO players "
            "(username, email, first_name, last_name, birth_date, country_code, registration_channel) "
            "VALUES ('player_one', 'one@example.test', 'Ada', 'One', '1990-01-01', 'CO', 'web'), "
            "('player_two', 'two@example.test', 'Ada', 'Two', '1990-01-01', 'CO', 'web')"
        )
    )
    player_id = conn.execute(
        text("SELECT id FROM players WHERE username = 'player_one'")
    ).scalar_one()
    conn.execute(
        text("INSERT INTO wallets (player_id, balance) VALUES (:player_id, 20.00)"),
        {"player_id": player_id},
    )
    category_id = conn.execute(
        text("INSERT INTO game_categories (code, name) VALUES ('slots', 'Slots') RETURNING id")
    ).scalar_one()
    game_id = conn.execute(
        text(
            "INSERT INTO games "
            "(category_id, name, provider, theoretical_rtp, volatility, min_bet, max_bet) "
            "VALUES (:category_id, 'Test Slots', 'Test Provider', 96.50, 'medium', 1, 100) "
            "RETURNING id"
        ),
        {"category_id": category_id},
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO transactions (player_id, type, status, amount, method, completed_at) "
            "VALUES (:player_id, 'deposit', 'completed', 10, 'card', now())"
        ),
        {"player_id": player_id},
    )
    session_id = conn.execute(
        text(
            "INSERT INTO game_sessions (player_id, game_id, device_type) "
            "VALUES (:player_id, :game_id, 'desktop') RETURNING id"
        ),
        {"player_id": player_id, "game_id": game_id},
    ).scalar_one()
    conn.execute(
        text("INSERT INTO bets (session_id, stake, payout) VALUES (:session_id, 10, 20)"),
        {"session_id": session_id},
    )
    conn.execute(
        text(
            "INSERT INTO risk_alerts (player_id, alert_type, severity, details) "
            "VALUES (:player_id, 'rapid_deposits', 'high', '{}'::jsonb)"
        ),
        {"player_id": player_id},
    )
    response = api_client.post(
        "/api/auth/login",
        json={
            "email": "support@example.test",
            "password": PASSWORD,
            "totp_code": pyotp.TOTP("JBSWY3DPEHPK3PXP").now(),
        },
    )
    assert response.status_code == HTTP_200_OK
    response = api_client.get("/api/players", params={"q": "player", "page_size": 1})
    assert response.status_code == HTTP_200_OK
    assert response.json()["total"] == 2
    assert len(response.json()["items"]) == 1
    response = api_client.get(f"/api/players/{player_id}")
    assert response.status_code == HTTP_200_OK
    assert response.json()["wallet_balance"] == "20.00"
    assert api_client.get("/api/games", params={"category_code": "slots"}).json()["total"] == 1
    assert (
        api_client.get(
            "/api/transactions",
            params={"type": "deposit", "status": "completed"},
        ).json()["total"]
        == 1
    )
    assert (
        api_client.get("/api/bets", params={"player_id": player_id, "is_win": "true"}).json()[
            "total"
        ]
        == 1
    )
    assert api_client.get("/api/risk-alerts", params={"severity": "high"}).json()["total"] == 1
    assert api_client.get("/api/audit-log").status_code == 403

    create_admin(conn, role_name="super_admin", totp_enabled=True, secret="JBSWY3DPEHPK3PXP")
    assert api_client.post("/api/auth/logout").status_code == 204
    response = api_client.post(
        "/api/auth/login",
        json={
            "email": "super_admin@example.test",
            "password": PASSWORD,
            "totp_code": pyotp.TOTP("JBSWY3DPEHPK3PXP").now(),
        },
    )
    assert response.status_code == HTTP_200_OK
    response = api_client.get("/api/audit-log", params={"page_size": 10})
    assert response.status_code == HTTP_200_OK
    assert response.json()["total"] > 0
    assert api_client.get("/api/games", params={"page": 0}).status_code == 422
    assert api_client.get("/api/transactions", params={"page_size": 101}).status_code == 422
