import secrets
from calendar import monthrange
from copy import deepcopy
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.enums import Channel, PlayerStatus
from app.models.player_casino import (
    DemoCreditEntry,
    DemoCreditWallet,
    DemoGameRound,
    PlayerCredential,
    PlayerSession,
)
from app.models.players import Player
from app.player_security import (
    PLAYER_LOCKOUT_DURATION,
    PLAYER_MAX_FAILED_LOGINS,
    PLAYER_SESSION_COOKIE,
    PlayerDatabaseSession,
    PlayerPrincipal,
    clear_player_session_cookie,
    create_player_session,
    current_player,
    player_password_hasher,
    player_token_digest,
    set_player_session_cookie,
    verify_player_password,
)
from app.schemas_player import BlackjackAction, DemoBet, PlayerLogin, PlayerRegistration

router = APIRouter(prefix="/api/player", tags=["player casino"])
MAX_DEMO_BALANCE = 1000
SLOT_SYMBOLS = ("🍒", "🍋", "🔔", "⭐")
SLOT_TRIPLE_MULTIPLIERS = {"🍒": 2, "🍋": 3, "🔔": 5, "⭐": 10}
BLACKJACK_SUITS = ("H", "D", "C", "S")
BLACKJACK_RANKS = ("A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")


def _is_adult(birth_date: date, today: date) -> bool:
    last_eligible_birth_date = date(
        today.year - 18,
        today.month,
        min(today.day, monthrange(today.year - 18, today.month)[1]),
    )
    return birth_date <= last_eligible_birth_date


def _require_active_player(principal: PlayerPrincipal) -> Player:
    if principal.player.status != PlayerStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Player account is not active",
        )
    return principal.player


def _wallet_for_update(db: Session, player_id: int) -> DemoCreditWallet:
    wallet = db.scalar(
        select(DemoCreditWallet)
        .where(DemoCreditWallet.player_id == player_id)
        .with_for_update()
    )
    if wallet is None:
        raise HTTPException(status_code=500, detail="Demo credit wallet is not configured")
    return wallet


def _refill_wallet(db: Session, wallet: DemoCreditWallet) -> None:
    today = datetime.now(UTC).date()
    if wallet.last_refilled_on >= today:
        return
    refill = MAX_DEMO_BALANCE - wallet.balance
    if refill > 0:
        wallet.balance += refill
        db.add(
            DemoCreditEntry(
                player_id=wallet.player_id,
                delta=refill,
                reason="daily_refill",
            )
        )
    wallet.last_refilled_on = today
    wallet.updated_at = datetime.now(UTC)


def _debit(
    db: Session,
    wallet: DemoCreditWallet,
    amount: int,
    *,
    reason: str,
    round_id: UUID | None = None,
) -> None:
    if wallet.balance < amount:
        raise HTTPException(status_code=409, detail="Not enough demo credits")
    wallet.balance -= amount
    wallet.updated_at = datetime.now(UTC)
    db.add(
        DemoCreditEntry(
            player_id=wallet.player_id,
            delta=-amount,
            reason=reason,
            round_id=round_id,
        )
    )


def _credit(
    db: Session,
    wallet: DemoCreditWallet,
    amount: int,
    *,
    reason: str,
    round_id: UUID,
) -> int:
    if amount <= 0:
        return 0
    credited = min(amount, MAX_DEMO_BALANCE - wallet.balance)
    if credited <= 0:
        return 0
    wallet.balance += credited
    wallet.updated_at = datetime.now(UTC)
    db.add(
        DemoCreditEntry(
            player_id=wallet.player_id,
            delta=credited,
            reason=reason,
            round_id=round_id,
        )
    )
    return credited


def _player_read(player: Player, wallet: DemoCreditWallet) -> dict:
    return {
        "id": player.id,
        "username": player.username,
        "first_name": player.first_name,
        "balance": wallet.balance,
    }


def _round_read(game_round: DemoGameRound, *, reveal_dealer: bool | None = None) -> dict:
    if game_round.game_code == "slots":
        return {
            "id": str(game_round.id),
            "game": game_round.game_code,
            "status": game_round.status,
            "stake": game_round.stake,
            "symbols": game_round.state["symbols"],
            "outcome": game_round.outcome,
        }

    state = game_round.state
    reveal = game_round.status != "in_progress" if reveal_dealer is None else reveal_dealer
    dealer_cards = state["dealer_hand"] if reveal else [state["dealer_hand"][0], "🂠"]
    return {
        "id": str(game_round.id),
        "game": game_round.game_code,
        "status": game_round.status,
        "stake": game_round.stake,
        "dealer_hand": dealer_cards,
        "hands": state["player_hands"],
        "current_hand": state["current_hand"],
        "can_split": (
            game_round.status == "in_progress"
            and not state["has_split"]
            and len(state["player_hands"]) == 1
            and len(state["player_hands"][0]["cards"]) == 2
            and _card_value(state["player_hands"][0]["cards"][0])
            == _card_value(state["player_hands"][0]["cards"][1])
        ),
        "outcome": game_round.outcome,
    }


def _card_value(card: str) -> int:
    rank = card[:-1]
    if rank == "A":
        return 11
    if rank in {"K", "Q", "J"}:
        return 10
    return int(rank)


def _hand_score(cards: list[str]) -> int:
    score = sum(_card_value(card) for card in cards)
    aces = sum(card[:-1] == "A" for card in cards)
    while score > 21 and aces:
        score -= 10
        aces -= 1
    return score


def _new_deck() -> list[str]:
    deck = [rank + suit for suit in BLACKJACK_SUITS for rank in BLACKJACK_RANKS]
    secrets.SystemRandom().shuffle(deck)
    return deck


def _draw(state: dict) -> str:
    return state["deck"].pop()


def _complete_blackjack(
    db: Session,
    wallet: DemoCreditWallet,
    game_round: DemoGameRound,
    *,
    natural: bool = False,
) -> None:
    state = game_round.state
    hands = state["player_hands"]
    alive_scores = [
        _hand_score(hand["cards"])
        for hand in hands
        if hand["status"] != "bust"
    ]
    dealer_cards = state["dealer_hand"]
    dealer_score = _hand_score(dealer_cards)
    dealer_natural = len(dealer_cards) == 2 and dealer_score == 21

    if not natural and alive_scores:
        target_score = max(alive_scores)
        while dealer_score < target_score and dealer_score < 21:
            dealer_cards.append(_draw(state))
            dealer_score = _hand_score(dealer_cards)

    dealer_bust = dealer_score > 21
    results = []
    for hand in hands:
        score = _hand_score(hand["cards"])
        requested_payout = 0
        is_player_natural = score == 21 and len(hand["cards"]) == 2
        if dealer_natural:
            if is_player_natural:
                requested_payout = hand["stake"]
                result = "push"
            else:
                result = "lose"
        elif natural and is_player_natural:
            requested_payout = hand["stake"] * 5 // 2
            result = "blackjack"
        elif score > 21:
            result = "bust"
        elif dealer_bust or score > dealer_score:
            requested_payout = hand["stake"] * 2
            result = "win"
        elif score == dealer_score:
            requested_payout = hand["stake"]
            result = "push"
        else:
            result = "lose"
        reason = "refund" if result == "push" else "payout"
        payout = _credit(db, wallet, requested_payout, reason=reason, round_id=game_round.id)
        results.append(
            {
                "result": result,
                "score": score,
                "stake": hand["stake"],
                "payout": payout,
            }
        )

    game_round.status = "completed"
    game_round.outcome = {
        "dealer_score": dealer_score,
        "hands": results,
    }
    game_round.completed_at = datetime.now(UTC)
    game_round.updated_at = game_round.completed_at
    game_round.state = deepcopy(state)
    flag_modified(game_round, "state")


def _active_blackjack(db: Session, player_id: int, *, lock: bool = False):
    statement = select(DemoGameRound).where(
        DemoGameRound.player_id == player_id,
        DemoGameRound.game_code == "blackjack",
        DemoGameRound.status == "in_progress",
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _invalid_player_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register_player(
    payload: PlayerRegistration,
    request: Request,
    response: Response,
    db: PlayerDatabaseSession,
):
    today = datetime.now(UTC).date()
    if not _is_adult(payload.birth_date, today):
        raise HTTPException(status_code=422, detail="Players must be at least 18 years old")

    username = payload.username.strip().lower()
    email = payload.email.strip().lower()
    player = Player(
        username=username,
        email=email,
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        birth_date=payload.birth_date,
        country_code=payload.country_code.upper(),
        registration_channel=Channel.WEB,
    )
    db.add(player)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered",
        ) from exc

    db.add(
        PlayerCredential(
            player_id=player.id,
            password_hash=player_password_hasher.hash(payload.password),
        )
    )
    today = datetime.now(UTC).date()
    wallet = DemoCreditWallet(
        player_id=player.id,
        balance=MAX_DEMO_BALANCE,
        last_refilled_on=today,
    )
    db.add(wallet)
    db.add(
        DemoCreditEntry(
            player_id=player.id,
            delta=MAX_DEMO_BALANCE,
            reason="initial_credit",
        )
    )
    token = create_player_session(db, player, request)
    db.commit()
    set_player_session_cookie(response, token)
    return {"player": _player_read(player, wallet)}


@router.post("/login")
def login_player(
    payload: PlayerLogin,
    request: Request,
    response: Response,
    db: PlayerDatabaseSession,
):
    username = payload.username.strip().lower()
    player = db.scalar(
        select(Player).where(Player.username == username).with_for_update()
    )
    credential = (
        db.scalar(
            select(PlayerCredential)
            .where(PlayerCredential.player_id == player.id)
            .with_for_update()
        )
        if player is not None
        else None
    )
    now = datetime.now(UTC)
    if (
        player is None
        or credential is None
        or player.status != PlayerStatus.ACTIVE
    ):
        raise _invalid_player_login()

    if credential.locked_until is not None and credential.locked_until > now:
        raise _invalid_player_login()
    if not verify_player_password(credential.password_hash, payload.password):
        credential.failed_login_attempts += 1
        if credential.failed_login_attempts >= PLAYER_MAX_FAILED_LOGINS:
            credential.locked_until = now + PLAYER_LOCKOUT_DURATION
        db.commit()
        raise _invalid_player_login()

    credential.failed_login_attempts = 0
    credential.locked_until = None
    credential.last_login_at = now
    player.last_login_at = now
    wallet = _wallet_for_update(db, player.id)
    _refill_wallet(db, wallet)
    token = create_player_session(db, player, request)
    db.commit()
    set_player_session_cookie(response, token)
    return {"player": _player_read(player, wallet)}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout_player(
    request: Request,
    response: Response,
    db: PlayerDatabaseSession,
):
    token = request.cookies.get(PLAYER_SESSION_COOKIE)
    if token:
        player_session = db.scalar(
            select(PlayerSession).where(
                PlayerSession.token_hash == player_token_digest(token),
                PlayerSession.revoked_at.is_(None),
            )
        )
        if player_session is not None:
            player_session.revoked_at = datetime.now(UTC)
            db.commit()
    clear_player_session_cookie(response)


@router.get("/me")
def player_me(
    principal: Annotated[PlayerPrincipal, Depends(current_player)],
    db: PlayerDatabaseSession,
):
    player = _require_active_player(principal)
    wallet = _wallet_for_update(db, player.id)
    _refill_wallet(db, wallet)
    db.commit()
    return {"player": _player_read(player, wallet)}


@router.post("/games/slots/spin")
def spin_slots(
    payload: DemoBet,
    principal: Annotated[PlayerPrincipal, Depends(current_player)],
    db: PlayerDatabaseSession,
):
    player = _require_active_player(principal)
    wallet = _wallet_for_update(db, player.id)
    _refill_wallet(db, wallet)
    _debit(db, wallet, payload.stake, reason="wager")

    symbols = [secrets.choice(SLOT_SYMBOLS) for _ in range(3)]
    payout = (
        payload.stake * SLOT_TRIPLE_MULTIPLIERS[symbols[0]]
        if symbols[0] == symbols[1] == symbols[2]
        else 0
    )
    game_round = DemoGameRound(
        player_id=player.id,
        game_code="slots",
        status="completed",
        stake=payload.stake,
        state={"symbols": symbols},
        outcome={
            "result": "win" if payout else "lose",
            "payout": payout,
            "multiplier": SLOT_TRIPLE_MULTIPLIERS.get(symbols[0], 0) if payout else 0,
        },
        completed_at=datetime.now(UTC),
    )
    db.add(game_round)
    db.flush()
    payout = _credit(db, wallet, payout, reason="payout", round_id=game_round.id)
    game_round.outcome["payout"] = payout
    game_round.outcome["result"] = "win" if payout else "lose"
    db.commit()
    return {"round": _round_read(game_round), "balance": wallet.balance}


@router.get("/games/blackjack/active")
def active_blackjack(
    principal: Annotated[PlayerPrincipal, Depends(current_player)],
    db: PlayerDatabaseSession,
):
    player = _require_active_player(principal)
    game_round = _active_blackjack(db, player.id)
    return {"round": _round_read(game_round) if game_round else None}


@router.post("/games/blackjack/start")
def start_blackjack(
    payload: DemoBet,
    principal: Annotated[PlayerPrincipal, Depends(current_player)],
    db: PlayerDatabaseSession,
):
    player = _require_active_player(principal)
    wallet = _wallet_for_update(db, player.id)
    _refill_wallet(db, wallet)
    if _active_blackjack(db, player.id) is not None:
        raise HTTPException(status_code=409, detail="Finish your active blackjack round first")
    _debit(db, wallet, payload.stake, reason="wager")

    state = {
        "deck": _new_deck(),
        "dealer_hand": [],
        "player_hands": [{"cards": [], "status": "playing", "stake": payload.stake}],
        "current_hand": 0,
        "has_split": False,
    }
    state["player_hands"][0]["cards"] = [_draw(state), _draw(state)]
    state["dealer_hand"] = [_draw(state), _draw(state)]
    game_round = DemoGameRound(
        player_id=player.id,
        game_code="blackjack",
        status="in_progress",
        stake=payload.stake,
        state=state,
    )
    db.add(game_round)
    db.flush()
    player_natural = _hand_score(state["player_hands"][0]["cards"]) == 21
    dealer_natural = _hand_score(state["dealer_hand"]) == 21
    if player_natural or dealer_natural:
        _complete_blackjack(db, wallet, game_round, natural=True)
    db.commit()
    return {"round": _round_read(game_round), "balance": wallet.balance}


@router.post("/games/blackjack/{round_id}/action")
def blackjack_action(
    round_id: UUID,
    payload: BlackjackAction,
    principal: Annotated[PlayerPrincipal, Depends(current_player)],
    db: PlayerDatabaseSession,
):
    player = _require_active_player(principal)
    wallet = _wallet_for_update(db, player.id)
    _refill_wallet(db, wallet)
    game_round = db.scalar(
        select(DemoGameRound)
        .where(
            DemoGameRound.id == round_id,
            DemoGameRound.player_id == player.id,
            DemoGameRound.game_code == "blackjack",
        )
        .with_for_update()
    )
    if game_round is None:
        raise HTTPException(status_code=404, detail="Blackjack round not found")
    if game_round.status != "in_progress":
        raise HTTPException(status_code=409, detail="Blackjack round is already complete")

    state = game_round.state
    hands = state["player_hands"]
    hand_index = state["current_hand"]
    hand = hands[hand_index]
    if hand["status"] != "playing":
        raise HTTPException(status_code=409, detail="This hand is already complete")

    if payload.action == "hit":
        hand["cards"].append(_draw(state))
        if _hand_score(hand["cards"]) > 21:
            hand["status"] = "bust"
        elif _hand_score(hand["cards"]) == 21:
            hand["status"] = "stood"
    elif payload.action == "stand":
        hand["status"] = "stood"
    else:
        if state["has_split"] or len(hands) != 1 or len(hand["cards"]) != 2:
            raise HTTPException(status_code=409, detail="This hand cannot be split")
        if _card_value(hand["cards"][0]) != _card_value(hand["cards"][1]):
            raise HTTPException(status_code=409, detail="Split requires equal-value first cards")
        _debit(db, wallet, hand["stake"], reason="wager", round_id=game_round.id)
        left, right = hand["cards"]
        first_hand = {"cards": [left, _draw(state)], "status": "playing", "stake": hand["stake"]}
        second_hand = {"cards": [right, _draw(state)], "status": "playing", "stake": hand["stake"]}
        state["player_hands"] = [first_hand, second_hand]
        hands = state["player_hands"]
        state["has_split"] = True
        for split_hand in state["player_hands"]:
            if _card_value(split_hand["cards"][0]) == 11 and split_hand["cards"][0][:-1] == "A":
                split_hand["status"] = "stood"
            elif _hand_score(split_hand["cards"]) == 21:
                split_hand["status"] = "stood"

    next_playing = next(
        (index for index, item in enumerate(hands) if item["status"] == "playing"),
        None,
    )
    if next_playing is None:
        _complete_blackjack(db, wallet, game_round)
    else:
        state["current_hand"] = next_playing
        game_round.updated_at = datetime.now(UTC)
        game_round.state = deepcopy(state)
        flag_modified(game_round, "state")
    db.commit()
    return {"round": _round_read(game_round), "balance": wallet.balance}


@router.get("/history")
def player_history(
    principal: Annotated[PlayerPrincipal, Depends(current_player)],
    db: PlayerDatabaseSession,
    limit: int = 20,
):
    player = _require_active_player(principal)
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=422, detail="Limit must be between 1 and 50")
    rounds = db.scalars(
        select(DemoGameRound)
        .where(DemoGameRound.player_id == player.id)
        .order_by(DemoGameRound.created_at.desc())
        .limit(limit)
    ).all()
    return {"items": [_round_read(game_round) for game_round in rounds]}
