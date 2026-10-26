import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.status import HTTP_200_OK, HTTP_202_ACCEPTED, HTTP_401_UNAUTHORIZED

from app.db import get_db
from app.main import app
from app.security import password_hasher

PASSWORD = "test-password-123"


def create_admin(conn, role_name="super_admin", *, is_active=True):
    role_id = conn.execute(
        text("INSERT INTO roles (name) VALUES (:name) RETURNING id"),
        {"name": role_name},
    ).scalar_one()
    admin_id = conn.execute(
        text(
            "INSERT INTO admin_users "
            "(username, email, password_hash, full_name, role_id, is_active) "
            "VALUES (:username, :email, :password_hash, 'Test Admin', :role_id, :is_active) "
            "RETURNING id"
        ),
        {
            "username": role_name,
            "email": f"{role_name}@example.test",
            "password_hash": password_hasher.hash(PASSWORD),
            "role_id": role_id,
            "is_active": is_active,
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


def test_username_login_session_rotation_and_logout(conn, api_client):
    create_admin(conn)
    response = api_client.post(
        "/api/auth/login",
        json={"username": "SUPER_ADMIN", "password": PASSWORD},
    )
    assert response.status_code == HTTP_200_OK
    assert response.json()["admin"]["username"] == "super_admin"
    assert api_client.get("/api/auth/me").status_code == HTTP_200_OK

    cookie = api_client.cookies.get("admin_session")
    response = api_client.post("/api/auth/refresh")
    assert response.status_code == HTTP_200_OK
    assert api_client.cookies.get("admin_session") != cookie
    assert api_client.get("/api/auth/me").status_code == HTTP_200_OK

    assert api_client.post("/api/auth/logout").status_code == 204
    assert api_client.get("/api/auth/me").status_code == HTTP_401_UNAUTHORIZED


def test_login_failures_are_audited_and_lock_account(conn, api_client):
    create_admin(conn)
    for _ in range(5):
        response = api_client.post(
            "/api/auth/login",
            json={"username": "super_admin", "password": "wrong-password"},
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


def test_registration_requires_super_admin_approval(conn, api_client):
    super_admin_id, _ = create_admin(conn)
    conn.execute(text("INSERT INTO roles (name) VALUES ('support')"))
    response = api_client.post(
        "/api/auth/register",
        json={
            "username": "new.support",
            "email": "New.Support@example.test",
            "full_name": "New Support",
            "password": "new-password-123",
        },
    )
    assert response.status_code == HTTP_202_ACCEPTED
    assert response.json() == {"status": "pending_approval"}
    assert (
        conn.execute(
            text("SELECT is_active FROM admin_users WHERE username = 'new.support'")
        ).scalar_one()
        is False
    )
    pending_user_id = conn.execute(
        text("SELECT id FROM admin_users WHERE username = 'new.support'")
    ).scalar_one()
    assert (
        api_client.post(
            "/api/auth/login",
            json={"username": "new.support", "password": "new-password-123"},
        ).status_code
        == HTTP_401_UNAUTHORIZED
    )
    assert api_client.get("/api/admin/pending-registrations").status_code == HTTP_401_UNAUTHORIZED

    response = api_client.post(
        "/api/auth/login",
        json={"username": "super_admin", "password": PASSWORD},
    )
    assert response.status_code == HTTP_200_OK
    pending = api_client.get("/api/admin/pending-registrations")
    assert pending.status_code == HTTP_200_OK
    assert [item["username"] for item in pending.json()["items"]] == ["new.support"]

    approved = api_client.post(f"/api/admin/users/{pending_user_id}/approve")
    assert approved.status_code == HTTP_200_OK
    assert approved.json()["role"] == "support"
    assert approved.json()["email"] == "new.support@example.test"
    assert api_client.get("/api/admin/pending-registrations").json()["total"] == 0
    assert (
        conn.execute(
            text("SELECT admin_user_id FROM audit_log WHERE action = 'admin.registration_approved'")
        ).scalar_one()
        == super_admin_id
    )

    api_client.post("/api/auth/logout")
    login = api_client.post(
        "/api/auth/login",
        json={"username": "new.support", "password": "new-password-123"},
    )
    assert login.status_code == HTTP_200_OK


def test_list_endpoints_filter_and_paginate_and_audit_is_super_admin_only(conn, api_client):
    create_admin(conn, role_name="support")
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
        json={"username": "support", "password": PASSWORD},
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

    super_admin_id, _ = create_admin(conn, role_name="super_admin")
    conn.execute(
        text(
            "INSERT INTO audit_log (admin_user_id, action, ip_address) "
            "VALUES (:admin_id, 'test.ip_serialization', '192.0.2.10'::inet), "
            "(:admin_id, 'test.ip_serialization', '2001:db8::10'::inet)"
        ),
        {"admin_id": super_admin_id},
    )
    assert api_client.post("/api/auth/logout").status_code == 204
    response = api_client.post(
        "/api/auth/login",
        json={"username": "super_admin", "password": PASSWORD},
    )
    assert response.status_code == HTTP_200_OK
    response = api_client.get(
        "/api/audit-log",
        params={"page_size": 10, "action": "test.ip_serialization"},
    )
    assert response.status_code == HTTP_200_OK
    assert response.json()["total"] == 2
    assert {item["ip_address"] for item in response.json()["items"]} == {
        "192.0.2.10",
        "2001:db8::10",
    }
    assert api_client.get("/api/games", params={"page": 0}).status_code == 422
    assert api_client.get("/api/transactions", params={"page_size": 101}).status_code == 422
