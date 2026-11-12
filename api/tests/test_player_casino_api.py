from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.status import HTTP_200_OK, HTTP_201_CREATED, HTTP_401_UNAUTHORIZED

from app.api.player_casino import _hand_score, _is_adult
from app.db import get_db
from app.main import app
from app.security import password_hasher

PLAYER_PASSWORD = "player-password-123"


def test_player_age_and_blackjack_ace_rules():
    assert _is_adult(datetime(2008, 6, 15).date(), datetime(2026, 6, 15).date())
    assert not _is_adult(datetime(2008, 6, 16).date(), datetime(2026, 6, 15).date())
    assert _hand_score(["AS", "7H"]) == 18
    assert _hand_score(["AS", "9H", "5D"]) == 15
    assert _hand_score(["10S", "7D"]) == 17


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


def register(client: TestClient, **overrides):
    payload = {
        "username": "demo.player",
        "email": "demo.player@example.test",
        "password": PLAYER_PASSWORD,
        "first_name": "Demo",
        "last_name": "Player",
        "birth_date": "1990-01-01",
        "country_code": "ES",
    }
    payload.update(overrides)
    return client.post("/api/player/register", json=payload)


def test_registration_creates_isolated_player_session_and_demo_credits(conn, api_client):
    response = register(api_client)
    assert response.status_code == HTTP_201_CREATED
    assert response.json()["player"]["balance"] == 1000
    assert api_client.cookies.get("player_session")
    assert api_client.get("/api/player/me").json()["player"]["username"] == "demo.player"
    assert api_client.get("/api/auth/me").status_code == HTTP_401_UNAUTHORIZED
    assert conn.execute(
        text("SELECT delta, reason FROM demo_credit_entries")
    ).one() == (1000, "initial_credit")
    assert conn.execute(text("SELECT count(*) FROM wallets")).scalar_one() == 0


def test_registration_rejects_underage_player(api_client, conn):
    response = register(api_client, birth_date="2010-01-01")
    assert response.status_code == 422
    assert conn.execute(text("SELECT count(*) FROM players")).scalar_one() == 0


def test_duplicate_registration_and_login_lockout(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    api_client.post("/api/player/logout")
    assert register(api_client).status_code == 409
    for _ in range(5):
        response = api_client.post(
            "/api/player/login",
            json={"username": "demo.player", "password": "wrong-password"},
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED
    attempts, locked_until = conn.execute(
        text("SELECT failed_login_attempts, locked_until FROM player_credentials")
    ).one()
    assert attempts == 5
    assert locked_until is not None
    assert api_client.post(
        "/api/player/login",
        json={"username": "demo.player", "password": PLAYER_PASSWORD},
    ).status_code == HTTP_401_UNAUTHORIZED


def test_player_and_admin_sessions_are_not_interchangeable(conn, api_client):
    assert register(api_client).status_code == HTTP_201_CREATED
    player_token = api_client.cookies.get("player_session")
    role_id = conn.execute(
        text("INSERT INTO roles (name) VALUES ('super_admin') RETURNING id")
    ).scalar_one()
    conn.execute(
        text(
            "INSERT INTO admin_users (username, email, password_hash, full_name, role_id) "
            "VALUES ('admin.test', 'admin.test@example.test', :password_hash, 'Admin Test', :role)"
        ),
        {"password_hash": password_hasher.hash("admin-password-123"), "role": role_id},
    )
    api_client.post("/api/player/logout")
    admin_login = api_client.post(
        "/api/auth/login",
        json={"username": "admin.test", "password": "admin-password-123"},
    )
    assert admin_login.status_code == HTTP_200_OK
    assert api_client.get("/api/player/me").status_code == HTTP_401_UNAUTHORIZED

    player_only_client = TestClient(app)
    player_only_client.cookies.set("player_session", player_token, path="/api/player")
    assert player_only_client.get("/api/auth/me").status_code == HTTP_401_UNAUTHORIZED


def test_slot_spin_updates_only_demo_credit_balance(api_client, conn, monkeypatch):
    assert register(api_client).status_code == HTTP_201_CREATED
    monkeypatch.setattr("app.api.player_casino.secrets.choice", lambda choices: "⭐")
    response = api_client.post("/api/player/games/slots/spin", json={"stake": 10})
    assert response.status_code == HTTP_200_OK
    assert response.json()["round"]["outcome"]["result"] == "win"
    assert response.json()["balance"] == 1000
    assert conn.execute(text("SELECT balance FROM demo_credit_wallets")).scalar_one() == 1000
    assert conn.execute(text("SELECT count(*) FROM wallets")).scalar_one() == 0
    deltas = conn.execute(
        text("SELECT delta FROM demo_credit_entries ORDER BY id")
    ).scalars().all()
    assert deltas == [1000, -10, 10]


def test_daily_refill_is_utc_based_and_capped(api_client, conn, monkeypatch):
    assert register(api_client).status_code == HTTP_201_CREATED
    symbols = iter(("🍒", "🍋", "🔔"))
    monkeypatch.setattr("app.api.player_casino.secrets.choice", lambda choices: next(symbols))
    api_client.post("/api/player/games/slots/spin", json={"stake": 100})
    conn.execute(
        text("UPDATE demo_credit_wallets SET last_refilled_on = :yesterday"),
        {"yesterday": datetime.now(UTC).date() - timedelta(days=1)},
    )
    response = api_client.get("/api/player/me")
    assert response.status_code == HTTP_200_OK
    assert response.json()["player"]["balance"] == 1000
    assert conn.execute(
        text("SELECT delta FROM demo_credit_entries WHERE reason = 'daily_refill'")
    ).scalar_one() == 100


def test_blackjack_hides_dealer_card_and_settles_against_server_state(
    api_client, conn, monkeypatch
):
    assert register(api_client).status_code == HTTP_201_CREATED
    monkeypatch.setattr(
        "app.api.player_casino._new_deck",
        lambda: ["5D", "9H", "6S", "7D", "10S"],
    )
    started = api_client.post("/api/player/games/blackjack/start", json={"stake": 10})
    assert started.status_code == HTTP_200_OK
    game_round = started.json()["round"]
    assert game_round["dealer_hand"] == ["6S", "🂠"]
    assert game_round["hands"][0]["cards"] == ["10S", "7D"]
    stored_state = conn.execute(
        text("SELECT state FROM demo_game_rounds WHERE id = :id"),
        {"id": game_round["id"]},
    ).scalar_one()
    assert stored_state["deck"] == ["5D"]
    response = api_client.post(
        f"/api/player/games/blackjack/{game_round['id']}/action",
        json={"action": "stand"},
    )
    assert response.status_code == HTTP_200_OK
    assert response.json()["round"]["status"] == "completed"
    assert response.json()["round"]["outcome"]["dealer_score"] == 20
    assert response.json()["round"]["dealer_hand"] == ["6S", "9H", "5D"], response.json()
    assert response.json()["round"]["outcome"]["hands"][0]["result"] == "lose"
