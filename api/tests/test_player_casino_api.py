from datetime import datetime, timedelta
from decimal import Decimal

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


def test_registration_creates_isolated_player_session_and_empty_wallets(conn, api_client):
    response = register(api_client)
    assert response.status_code == HTTP_201_CREATED
    player = response.json()["player"]
    assert player["balance"] == 0
    assert player["chip_balance"] == 0
    assert player["wallet_balance"] == 0.0
    assert api_client.cookies.get("player_session")
    assert api_client.get("/api/player/me").json()["player"]["username"] == "demo.player"
    assert api_client.get("/api/auth/me").status_code == HTTP_401_UNAUTHORIZED
    assert conn.execute(text("SELECT balance FROM player_chip_wallets")).scalar_one() == 0
    assert conn.execute(text("SELECT balance FROM wallets")).scalar_one() == 0
    assert conn.execute(text("SELECT count(*) FROM demo_credit_entries")).scalar_one() == 0


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


def test_slot_spin_updates_chip_balance_and_ledger(api_client, conn, monkeypatch):
    assert register(api_client).status_code == HTTP_201_CREATED
    conn.execute(text("UPDATE player_chip_wallets SET balance = 100"))
    monkeypatch.setattr("app.api.player_casino.secrets.choice", lambda choices: "⭐")
    response = api_client.post("/api/player/games/slots/spin", json={"stake": 10})
    assert response.status_code == HTTP_200_OK
    assert response.json()["round"]["outcome"]["result"] == "win"
    assert response.json()["balance"] == 190
    assert conn.execute(text("SELECT balance FROM player_chip_wallets")).scalar_one() == 190
    assert conn.execute(text("SELECT count(*) FROM wallets")).scalar_one() == 1
    deltas = conn.execute(
        text("SELECT delta FROM player_chip_entries ORDER BY id")
    ).scalars().all()
    assert deltas == [-10, 100]


def test_roulette_pays_european_odds_and_records_all_wagers(api_client, conn, monkeypatch):
    assert register(api_client).status_code == HTTP_201_CREATED
    conn.execute(text("UPDATE player_chip_wallets SET balance = 500"))
    monkeypatch.setattr("app.api.player_casino.secrets.randbelow", lambda upper: 32)

    response = api_client.post(
        "/api/player/games/roulette/spin",
        json={
            "bets": [
                {"kind": "number", "value": 32, "amount": 10},
                {"kind": "color", "value": "red", "amount": 10},
                {"kind": "parity", "value": "even", "amount": 10},
                {"kind": "dozen", "value": 3, "amount": 10},
            ]
        },
    )

    assert response.status_code == HTTP_200_OK
    result = response.json()
    assert result["round"]["winning_number"] == 32
    assert result["round"]["color"] == "red"
    assert [bet["payout"] for bet in result["round"]["bets"]] == [360, 20, 20, 30]
    assert [bet["won"] for bet in result["round"]["bets"]] == [True, True, True, True]
    assert result["round"]["outcome"]["requested_payout"] == 430
    assert result["round"]["outcome"]["payout"] == 430
    assert result["balance"] == 890
    assert conn.execute(
        text("SELECT game_code, stake FROM demo_game_rounds")
    ).one() == ("roulette", 40)
    entries = conn.execute(
        text(
            "SELECT delta, reason FROM player_chip_entries "
            "WHERE reason IN ('wager', 'payout') ORDER BY id"
        )
    ).all()
    assert entries == [(-40, "wager"), (430, "payout")]
    assert conn.execute(text("SELECT count(*) FROM wallets")).scalar_one() == 1


def test_roulette_zero_only_wins_straight_up_number(api_client, conn, monkeypatch):
    assert register(api_client).status_code == HTTP_201_CREATED
    conn.execute(text("UPDATE player_chip_wallets SET balance = 500"))
    monkeypatch.setattr("app.api.player_casino.secrets.randbelow", lambda upper: 0)

    response = api_client.post(
        "/api/player/games/roulette/spin",
        json={
            "bets": [
                {"kind": "number", "value": 0, "amount": 10},
                {"kind": "color", "value": "red", "amount": 10},
                {"kind": "parity", "value": "odd", "amount": 10},
                {"kind": "dozen", "value": 1, "amount": 10},
            ]
        },
    )

    assert response.status_code == HTTP_200_OK
    game_round = response.json()["round"]
    assert game_round["color"] == "green"
    assert [bet["won"] for bet in game_round["bets"]] == [True, False, False, False]
    assert response.json()["balance"] == 820


@pytest.mark.parametrize(
    "bets",
    [
        [],
        [{"kind": "number", "value": 37, "amount": 10}],
        [{"kind": "color", "value": "green", "amount": 10}],
        [{"kind": "dozen", "value": 4, "amount": 10}],
        [{"kind": "number", "value": "red", "amount": 10}],
        [{"kind": "number", "value": 1, "amount": 15}],
        [{"kind": "number", "value": 1, "amount": 60}, {"kind": "number", "value": 2, "amount": 50}],
        [{"kind": "number", "value": 1, "amount": 10}] * 11,
    ],
)
def test_roulette_rejects_invalid_wagers_without_ledger_changes(api_client, conn, bets):
    assert register(api_client).status_code == HTTP_201_CREATED
    response = api_client.post("/api/player/games/roulette/spin", json={"bets": bets})
    assert response.status_code == 422
    assert conn.execute(text("SELECT count(*) FROM demo_game_rounds")).scalar_one() == 0
    assert conn.execute(text("SELECT count(*) FROM player_chip_entries")).scalar_one() == 0


def test_roulette_insufficient_balance_does_not_create_round_or_wager(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    response = api_client.post(
        "/api/player/games/roulette/spin",
        json={"bets": [{"kind": "number", "value": 7, "amount": 10}]},
    )
    assert response.status_code == 409
    assert conn.execute(text("SELECT balance FROM player_chip_wallets")).scalar_one() == 0
    assert conn.execute(text("SELECT count(*) FROM demo_game_rounds")).scalar_one() == 0
    assert conn.execute(text("SELECT count(*) FROM player_chip_entries")).scalar_one() == 0


def test_player_chip_balance_does_not_refill_daily(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    conn.execute(text("UPDATE player_chip_wallets SET balance = 100"))
    response = api_client.get("/api/player/me")
    assert response.status_code == HTTP_200_OK
    assert response.json()["player"]["balance"] == 100
    assert conn.execute(text("SELECT count(*) FROM player_chip_entries")).scalar_one() == 0


def test_blackjack_hides_dealer_card_and_settles_against_server_state(
    api_client, conn, monkeypatch
):
    assert register(api_client).status_code == HTTP_201_CREATED
    conn.execute(text("UPDATE player_chip_wallets SET balance = 100"))
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


def test_simulated_top_up_records_method_origin_and_respects_wallet_cap(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    response = api_client.post(
        "/api/player/wallet/top-up",
        json={"amount": "200.00", "method": "card"},
    )
    assert response.status_code == HTTP_200_OK
    assert response.json()["wallet_balance"] == 200.0
    assert conn.execute(
        text("SELECT type, amount, method, origin FROM transactions")
    ).one() == ("deposit", 200, "card", "player_casino_demo")

    conn.execute(text("UPDATE wallets SET balance = 490000"))
    rejected = api_client.post(
        "/api/player/wallet/top-up",
        json={"amount": "20000.00", "method": "bank_transfer"},
    )
    assert rejected.status_code == 409
    assert conn.execute(text("SELECT balance FROM wallets")).scalar_one() == 490000
    assert conn.execute(text("SELECT count(*) FROM transactions")).scalar_one() == 1
    assert api_client.post(
        "/api/player/wallet/top-up",
        json={"amount": "50000.01", "method": "card"},
    ).status_code == 422


def test_vip_purchase_and_chip_package_apply_discount_atomically(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    assert api_client.post(
        "/api/player/wallet/top-up",
        json={"amount": "100.00", "method": "e_wallet"},
    ).status_code == HTTP_200_OK

    membership = api_client.post("/api/player/vip/purchase", json={"tier": "gold"})
    assert membership.status_code == HTTP_200_OK
    assert membership.json()["player"]["vip_tier"] == "gold"
    assert conn.execute(text("SELECT balance FROM wallets")).scalar_one() == Decimal("85.01")

    package = api_client.post("/api/player/chips/purchase", json={"chips": 100})
    assert package.status_code == HTTP_200_OK
    assert package.json()["price"] == 9.5
    assert package.json()["player"]["chip_balance"] == 100
    assert conn.execute(text("SELECT balance FROM wallets")).scalar_one() == Decimal("75.51")
    assert conn.execute(text("SELECT balance FROM player_chip_wallets")).scalar_one() == 100
    assert conn.execute(
        text("SELECT type, origin FROM transactions ORDER BY id")
    ).all() == [
        ("deposit", "player_casino_demo"),
        ("vip_membership", "player_casino_demo"),
        ("chip_purchase", "player_casino_demo"),
    ]
    assert conn.execute(
        text("SELECT delta, reason FROM player_chip_entries")
    ).one() == (100, "chip_purchase")


def test_vip_same_tier_extends_and_tier_change_replaces(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    assert api_client.post(
        "/api/player/wallet/top-up",
        json={"amount": "100.00", "method": "card"},
    ).status_code == HTTP_200_OK
    assert api_client.post("/api/player/vip/purchase", json={"tier": "silver"}).status_code == 200
    initial_expiry = conn.execute(
        text("SELECT expires_at FROM player_vip_subscriptions")
    ).scalar_one()
    conn.execute(
        text("UPDATE player_vip_subscriptions SET expires_at = expires_at + interval '10 days'")
    )
    extended_from = conn.execute(
        text("SELECT expires_at FROM player_vip_subscriptions")
    ).scalar_one()

    assert api_client.post("/api/player/vip/purchase", json={"tier": "silver"}).status_code == 200
    renewed_expiry = conn.execute(
        text("SELECT expires_at FROM player_vip_subscriptions")
    ).scalar_one()
    assert renewed_expiry == extended_from + timedelta(days=30)
    assert renewed_expiry > initial_expiry

    changed = api_client.post("/api/player/vip/purchase", json={"tier": "gold"})
    assert changed.status_code == HTTP_200_OK
    assert changed.json()["player"]["vip_tier"] == "gold"
    started_at, expires_at = conn.execute(
        text("SELECT started_at, expires_at FROM player_vip_subscriptions")
    ).one()
    assert expires_at - started_at == timedelta(days=30)


def test_chip_purchase_cap_rejects_without_partial_debit_or_ledger(api_client, conn):
    assert register(api_client).status_code == HTTP_201_CREATED
    assert api_client.post(
        "/api/player/wallet/top-up",
        json={"amount": "100.00", "method": "card"},
    ).status_code == HTTP_200_OK
    conn.execute(text("UPDATE player_chip_wallets SET balance = 9999950"))

    response = api_client.post("/api/player/chips/purchase", json={"chips": 100})
    assert response.status_code == 409
    assert conn.execute(text("SELECT balance FROM wallets")).scalar_one() == Decimal("100.00")
    assert conn.execute(text("SELECT balance FROM player_chip_wallets")).scalar_one() == 9999950
    assert conn.execute(
        text("SELECT count(*) FROM transactions WHERE type = 'chip_purchase'")
    ).scalar_one() == 0
    assert conn.execute(text("SELECT count(*) FROM player_chip_entries")).scalar_one() == 0
