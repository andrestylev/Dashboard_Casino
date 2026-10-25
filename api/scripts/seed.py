"""Phase 2: realistic, reproducible mock data for the casino database.

Run from the repo root, after the schema exists (`alembic upgrade head`):

    docker compose run --rm api python -m scripts.seed --reset --as-of 2026-10-23
    python api/scripts/seed.py --reset                 # without Docker (uses DATABASE_URL)

Same --seed + same --as-of  =>  exactly the same data (the digest printed at the end proves it).
Run it close to the presentation day (or pass --as-of) so "last 7 / 30 days" are not empty.

What it builds
--------------
* roles, admin users (demo password), game categories and a catalogue of fictional games;
* players with wallets, a full money ledger (deposits, withdrawals, bonuses, adjustments),
  game sessions and bets, notes, an audit log;
* injected risk patterns (one risk_alert per pattern, with the evidence in `details`):
  rapid_deposits, structured_withdrawals, shared_device, loss_chasing, unusual_bet_size.

Ledger rules (the API and the KPIs must use the same definitions)
-----------------------------------------------------------------
    wallets.balance = completed deposits + completed bonus credits + completed adjustments
                      - withdrawals that are completed or pending (funds are reserved)
                      + sum(bets.payout - bets.stake)
Failed / cancelled transactions never move money. `adjustment` is a manual CREDIT (the schema
has no direction column for it). Amounts live in the casino's single currency (USD-like scale).
Money is handled in integer cents while simulating, so there are no rounding errors.

IDs are renumbered in chronological order at the end, so "ORDER BY id" is also "ORDER BY time".
"""

import argparse
import bisect
import hashlib
import json
import math
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np  # noqa: E402
import psycopg  # noqa: E402
from argon2 import Type  # noqa: E402
from argon2.low_level import hash_secret  # noqa: E402
from faker import Faker  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402
from app.models import enums as E  # noqa: E402

# ---------------------------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------------------------

MIN_DEPOSIT_C = 1_000  # 10.00
MIN_WITHDRAWAL_C = 2_000  # 20.00
REPORTING_THRESHOLD_C = 100_000  # 1,000.00: structured withdrawals stay just under it
STRUCTURING_BAND_C = (85_000, REPORTING_THRESHOLD_C)  # [850.00, 1000.00)
ODD_BET_MIN_C = 10_000  # unusual_bet_size rule: stake >= 100.00 and >= 20x the player's median
LADDER_C = [10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000, 100000]

T_DEPOSIT, T_WITHDRAWAL = E.TransactionType.DEPOSIT.value, E.TransactionType.WITHDRAWAL.value
T_BONUS, T_ADJUST = E.TransactionType.BONUS_CREDIT.value, E.TransactionType.ADJUSTMENT.value
S_PENDING, S_DONE = E.TransactionStatus.PENDING.value, E.TransactionStatus.COMPLETED.value
S_FAILED, S_CANCELLED = E.TransactionStatus.FAILED.value, E.TransactionStatus.CANCELLED.value

METHODS = [m.value for m in E.PaymentMethod]  # card, e_wallet, bank_transfer, crypto
METHOD_PREFIX = {"card": "CARD", "e_wallet": "EWAL", "bank_transfer": "BANK", "crypto": "CRYP"}
METHOD_DELAY_S = {  # how long the payment provider takes to confirm
    "card": (3, 60), "e_wallet": (3, 45), "bank_transfer": (900, 36 * 3600), "crypto": (120, 1800),
}  # fmt: skip

# (name, bets per session: median, sigma, seconds between bets: low, high)
CATEGORIES = {
    "slots": ("Slots", 12, 0.7, 4, 14),
    "roulette": ("Roulette", 8, 0.6, 20, 50),
    "blackjack": ("Blackjack", 8, 0.6, 18, 45),
    "poker": ("Poker", 12, 0.6, 8, 25),
    "baccarat": ("Baccarat", 8, 0.6, 20, 45),
    "live_casino": ("Live casino", 6, 0.6, 25, 60),
}

# category, name, provider, RTP %, volatility, min bet (cents), max bet (cents), outcome model,
# popularity, released N days before --as-of, retired N days before --as-of (None = active)
GAME_DEFS = [
    ("slots", "Golden Scarab", "Aurelia Gaming", 96.20, "medium", 10, 10000, "slot", 3.0, 900, None),
    ("slots", "Neon Fortune", "Pixel Reef", 95.80, "high", 10, 20000, "slot", 3.0, 700, None),
    ("slots", "Pirate's Bounty", "Solstice Studio", 96.50, "medium", 20, 10000, "slot", 2.5, 1400, None),
    ("slots", "Wild Orchard", "Aurelia Gaming", 96.00, "low", 10, 5000, "slot", 2.0, 1100, None),
    ("slots", "Lucky Lanterns", "Quartz Labs", 95.50, "high", 20, 20000, "slot", 2.0, 500, None),
    ("slots", "Dragon Pearl", "Pixel Reef", 96.80, "medium", 10, 10000, "slot", 2.0, 650, None),
    ("slots", "Crystal Cascade", "Quartz Labs", 94.90, "high", 20, 10000, "slot", 1.5, 420, None),
    ("slots", "Aztec Sunrise", "Solstice Studio", 96.10, "medium", 10, 10000, "slot", 2.0, 1200, None),
    ("slots", "Retro Reels 777", "Aurelia Gaming", 95.00, "low", 10, 5000, "slot", 1.5, 1700, 60),
    ("slots", "Midnight Panther", "Pixel Reef", 96.30, "high", 20, 20000, "slot", 1.5, 300, None),
    ("slots", "Viking Voyage", "Quartz Labs", 96.70, "medium", 10, 10000, "slot", 1.5, 800, None),
    ("slots", "Candy Quest", "Solstice Studio", 95.70, "high", 10, 10000, "slot", 1.0, 250, None),
    ("slots", "Mystic Forest", "Aurelia Gaming", 96.40, "low", 10, 5000, "slot", 1.5, 1000, None),
    ("slots", "Safari Sunset", "Pixel Reef", 94.50, "medium", 10, 10000, "slot", 0.8, 1900, 120),
    ("slots", "Jade Emperor", "Quartz Labs", 96.20, "medium", 20, 10000, "slot", 1.5, 600, None),
    ("slots", "Fiesta Fortune", "Solstice Studio", 95.90, "high", 10, 10000, "slot", 1.2, 350, None),
    ("roulette", "European Roulette", "Aurelia Gaming", 97.30, "low", 100, 100000, "even", 2.0, 1500, None),
    ("roulette", "American Roulette", "Aurelia Gaming", 94.74, "low", 100, 100000, "even", 1.0, 1500, None),
    ("roulette", "French Roulette", "Quartz Labs", 97.30, "low", 100, 100000, "even", 0.8, 1300, None),
    ("roulette", "Mini Roulette", "Pixel Reef", 94.59, "low", 50, 20000, "even", 0.5, 800, None),
    ("blackjack", "Classic Blackjack", "Aurelia Gaming", 99.40, "low", 100, 50000, "even", 2.0, 1600, None),
    ("blackjack", "Blackjack Pro", "Quartz Labs", 99.60, "low", 200, 100000, "even", 1.2, 900, None),
    ("blackjack", "Double Exposure Blackjack", "Solstice Studio", 98.70, "low", 100, 50000, "even", 0.7, 1100, None),
    ("blackjack", "Spanish 21", "Pixel Reef", 98.80, "low", 100, 50000, "even", 0.6, 1000, None),
    ("poker", "Jacks or Better", "Quartz Labs", 99.50, "medium", 20, 10000, "video", 1.2, 1700, None),
    ("poker", "Deuces Wild", "Quartz Labs", 98.90, "medium", 20, 10000, "video", 1.0, 1700, None),
    ("poker", "Caribbean Stud", "Solstice Studio", 94.80, "medium", 100, 50000, "video", 0.5, 2000, 90),
    ("poker", "Three Card Poker", "Aurelia Gaming", 96.60, "medium", 100, 50000, "video", 0.8, 1300, None),
    ("baccarat", "Punto Banco", "Aurelia Gaming", 98.90, "low", 100, 100000, "even", 1.2, 1500, None),
    ("baccarat", "Mini Baccarat", "Pixel Reef", 98.76, "low", 100, 50000, "even", 0.8, 900, None),
    ("baccarat", "Baccarat Squeeze", "Quartz Labs", 98.80, "low", 200, 100000, "even", 0.6, 600, None),
    ("live_casino", "Live Roulette", "Studio Meridian", 97.30, "low", 100, 100000, "even", 1.5, 700, None),
    ("live_casino", "Live Blackjack", "Studio Meridian", 99.00, "low", 500, 100000, "even", 1.2, 700, None),
    ("live_casino", "Live Baccarat", "Studio Meridian", 98.90, "low", 500, 100000, "even", 1.0, 700, None),
    ("live_casino", "Fortune Wheel Live", "Studio Meridian", 96.50, "medium", 100, 20000, "wheel", 1.2, 400, None),
]  # fmt: skip

# Win probability and spread (sigma of the lognormal payout multiplier) per outcome model.
# Mean payout multiplier = RTP / p_win, so the realised RTP converges to the theoretical one.
SLOT_MODEL = {"low": (0.40, 0.45), "medium": (0.28, 0.85), "high": (0.17, 1.35)}
MAX_MULTIPLIER = 5000

ARCHETYPES = {  # share, sessions/week, mean active life (days), median deposit (cents), sigma
    "casual": dict(share=0.62, rate=0.9, life=25, dep=3_000, sigma=0.6),
    "regular": dict(share=0.27, rate=2.5, life=90, dep=8_000, sigma=0.6),
    "high_roller": dict(share=0.04, rate=4.0, life=150, dep=60_000, sigma=0.6),
    "dormant": dict(share=0.07, rate=0.0, life=0, dep=2_000, sigma=0.5),
}

# country: (weight, Faker locale, /16 prefixes used to build mock IPs)
COUNTRIES = {
    "CO": (42, "es_CO", [(181, 49), (186, 80), (190, 24), (200, 29)]),
    "MX": (14, "es_MX", [(187, 189), (189, 203), (201, 141)]),
    "CL": (8, "es_CL", [(190, 45), (200, 83)]),
    "PE": (8, "es_CO", [(190, 223), (200, 48)]),
    "AR": (7, "es_AR", [(181, 12), (190, 138)]),
    "ES": (6, "es_ES", [(80, 24), (88, 12), (95, 60)]),
    "BR": (6, "pt_BR", [(177, 12), (189, 40), (201, 17)]),
    "US": (4, "en_US", [(73, 12), (98, 45), (174, 50)]),
    "EC": (3, "es_CO", [(186, 66), (190, 152)]),
    "UY": (2, "es_AR", [(179, 24), (190, 64)]),
}

ADMINS = [  # email, full name, role, is_active
    ("camila.restrepo@casino-demo.test", "Camila Restrepo", "super_admin", True),
    ("andres.molina@casino-demo.test", "Andres Molina", "super_admin", True),
    ("laura.gomez@casino-demo.test", "Laura Gomez", "support", True),
    ("juan.pardo@casino-demo.test", "Juan Pardo", "support", True),
    ("sofia.herrera@casino-demo.test", "Sofia Herrera", "support", True),
    ("diego.vargas@casino-demo.test", "Diego Vargas", "support", False),  # left the team
]
ROLES = [
    ("super_admin", "Full access, user management and audit log"),
    ("support", "Read access and player notes; cannot change money or other staff"),
]
ADMIN_IPS = ["190.250.10.21", "190.250.10.34", "181.50.77.12", "200.29.103.8"]

NOTE_TEMPLATES = [
    "Customer asked why a withdrawal is still pending; explained the KYC review time.",
    "Asked to raise the monthly deposit limit. Declined until the 7-day cooling-off ends.",
    "Reported a card used without permission; deposits sent to chargeback review.",
    "Requested a callback about bonus wagering terms. Terms explained by phone.",
    "VIP manager assigned after the account passed the high-roller threshold.",
    "Documents uploaded again after the first KYC attempt was rejected (blurry photo).",
    "Customer says the game froze during a bet; session checked, bet settled correctly.",
    "Asked for a cooling-off break. Account limits reviewed with the customer.",
]
RESOLUTION_NOTES = {
    "resolved": [
        "Contacted the customer; activity confirmed as legitimate and documented.",
        "Limits applied and the customer was notified; monitoring for 30 days.",
        "Accounts linked and escalated to compliance; manual review completed.",
        "Source of funds verified with supporting documents.",
    ],
    "dismissed": [
        "False positive: consistent with the customer's usual behaviour.",
        "False positive: family members on the same connection, already verified.",
        "No further action: payments confirmed by the provider as genuine.",
    ],
}
ADJUSTMENT_NOTES = [
    "Goodwill credit after support ticket (game outage).",
    "Manual correction: deposit confirmed by provider but not credited.",
    "Compensation for a delayed withdrawal.",
]

PERSONA_BASE = {"rapid": 10, "structuring": 8, "chaser": 12, "oddbet": 8}  # at 1,200 players
RING_SIZES = [3, 4, 5]
MIN_PLAYERS = 40

WEEKDAY_FACTOR = [0.9, 0.85, 0.9, 0.95, 1.1, 1.35, 1.3]  # Monday .. Sunday


def _hour_probabilities() -> np.ndarray:
    """Players are mostly in the Americas: evening there is the UTC night."""
    w = []
    for h in range(24):
        d1 = min(abs(h - 1.5), 24 - abs(h - 1.5))
        d2 = min(abs(h - 19), 24 - abs(h - 19))
        w.append(0.25 + math.exp(-(d1**2) / 18) + 0.5 * math.exp(-(d2**2) / 12.5))
    p = np.array(w)
    return p / p.sum()


HOUR_P = _hour_probabilities()


# ---------------------------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------------------------


def money(cents: int) -> str:
    """Integer cents -> '123.45' (amounts are never negative here)."""
    return f"{cents // 100}.{cents % 100:02d}"


def nice(cents: int) -> int:
    """Round to a human deposit size: 10, 15, 20, ... 50, 100, 150 ..."""
    units = cents / 100
    step = 5 if units < 100 else 10 if units < 500 else 50 if units < 2000 else 100
    return max(MIN_DEPOSIT_C, int(round(units / step)) * step * 100)


def ladder_floor(cents: int) -> int:
    i = bisect.bisect_right(LADDER_C, cents) - 1
    return LADDER_C[max(i, 0)]


def ascii_slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in plain.lower() if ch.isalnum())


def month_key(ts: datetime) -> int:
    return ts.year * 12 + ts.month


def ip_text(parts: tuple[int, int, int, int]) -> str:
    return ".".join(str(p) for p in parts)


def utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


# ---------------------------------------------------------------------------------------------
# Data model used while simulating
# ---------------------------------------------------------------------------------------------


@dataclass
class Config:
    seed: int = 42
    as_of: datetime = field(default_factory=lambda: utc_midnight(datetime.now(UTC).date()))
    days: int = 180
    players: int = 1200
    admin_password: str = "Demo-Casino-2026!"


@dataclass
class Game:
    id: int
    category: str
    name: str
    provider: str
    rtp: float
    volatility: str
    min_c: int
    max_c: int
    kind: str
    weight: float
    released: date
    retired_at: datetime | None
    ladder: list[int]
    p_win: float
    sigma: float
    mean_mult: float
    bets_median: float
    bets_sigma: float
    gap_lo: int
    gap_hi: int


@dataclass
class PlayerMeta:
    id: int
    registered_at: datetime
    persona: str | None = None
    ring: int | None = None
    ring_device: tuple[str, str, tuple[int, int, int]] | None = None  # type, fingerprint, ip /24
    archetype: str = "casual"
    min_life_days: int = 0
    country: str = "CO"
    locale: str = "es_CO"
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    email: str = ""
    birth_date: date = date(1990, 1, 1)
    channel: str = "web"
    status: str = "active"
    status_changed_at: datetime | None = None
    self_exclusion_until: datetime | None = None
    kyc: str = "verified"
    deposit_limit_c: int | None = None
    loss_limit_c: int | None = None
    home_ip: tuple[int, int, int, int] = (0, 0, 0, 0)
    # filled by the simulation
    turnover_c: int = 0
    last_session_at: datetime | None = None
    balance_c: int = 0
    wallet_updated_at: datetime | None = None
    vip_tier: str = "standard"


class Ctx:
    """Everything produced by one run (all ids are temporary until `renumber`)."""

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.as_of = cfg.as_of
        self.start = cfg.as_of - timedelta(days=cfg.days)
        self.master = np.random.default_rng([cfg.seed, 0])
        self.fake = None
        self.games: list[Game] = []
        self.players: list[PlayerMeta] = []
        self.admin_rows: list[list] = []
        self.support_ids: list[int] = []
        self.staff_ids: list[int] = []
        self.tx: list[list] = []
        self.bonuses: list[list] = []
        self.sessions: list[list] = []
        self.bets: list[list] = []
        self.evidence: list[dict] = []
        self.notes: list[list] = []
        self.alerts: list[list] = []
        self.audit: list[list] = []
        self.counters: dict[str, int] = defaultdict(int)

    def next_id(self, kind: str) -> int:
        self.counters[kind] += 1
        return self.counters[kind]


# ---------------------------------------------------------------------------------------------
# Static catalogue
# ---------------------------------------------------------------------------------------------


def build_games(ctx: Ctx) -> None:
    for i, d in enumerate(GAME_DEFS, start=1):
        cat, name, provider, rtp, vol, min_c, max_c, kind, weight, rel_days, ret_days = d
        if kind == "slot":
            p_win, sigma = SLOT_MODEL[vol]
        elif kind == "even":
            p_win, sigma = rtp / 200, 0.0  # even-money bets: pays 2x on a win
        elif kind == "video":
            p_win, sigma = 0.45, 1.0
        else:
            p_win, sigma = 0.45, 0.8
        _, bets_median, bets_sigma, gap_lo, gap_hi = CATEGORIES[cat]
        ctx.games.append(
            Game(
                id=i, category=cat, name=name, provider=provider, rtp=rtp, volatility=vol,
                min_c=min_c, max_c=max_c, kind=kind, weight=weight,
                released=(ctx.as_of - timedelta(days=rel_days)).date(),
                retired_at=None if ret_days is None else ctx.as_of - timedelta(days=ret_days),
                ladder=[c for c in LADDER_C if min_c <= c <= max_c],
                p_win=p_win, sigma=sigma, mean_mult=rtp / 100 / p_win,
                bets_median=bets_median, bets_sigma=bets_sigma, gap_lo=gap_lo, gap_hi=gap_hi,
            )
        )  # fmt: skip


def build_admins(ctx: Ctx) -> None:
    role_id = {name: i for i, (name, _) in enumerate(ROLES, start=1)}
    created = ctx.start - timedelta(days=45)
    for i, (email, name, role, active) in enumerate(ADMINS, start=1):
        salt = hashlib.blake2b(f"{ctx.cfg.seed}:{email}".encode(), digest_size=16).digest()
        pw_hash = hash_secret(
            ctx.cfg.admin_password.encode(), salt, time_cost=3, memory_cost=65536,
            parallelism=4, hash_len=32, type=Type.ID,
        ).decode()  # fmt: skip
        # [id, email, hash, name, role_id, is_active, created_at, last_login_at]
        ctx.admin_rows.append([i, email, pw_hash, name, role_id[role], active, created, None])
        if active:
            ctx.staff_ids.append(i)
            if role == "support":
                ctx.support_ids.append(i)


# ---------------------------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------------------------


def persona_counts(n: int) -> dict[str, int]:
    if n < MIN_PLAYERS:
        raise SystemExit(f"--players must be at least {MIN_PLAYERS} (risk patterns need players)")
    scale = n / 1200
    counts = {k: max(1, round(v * scale)) for k, v in PERSONA_BASE.items()}
    counts["rings"] = max(1, round(3 * scale))
    return counts


def random_time(ctx: Ctx, rng: np.random.Generator, day: datetime) -> datetime:
    seconds = int(rng.choice(24, p=HOUR_P)) * 3600 + int(rng.integers(0, 3600))
    return day + timedelta(seconds=seconds)


def build_players(ctx: Ctx) -> None:
    cfg, rng = ctx.cfg, ctx.master
    n = cfg.players
    day0 = utc_midnight(ctx.start.date())
    offsets = np.minimum(cfg.days * rng.random(n) ** 0.6, cfg.days - 0.6)  # more recent signups
    regs = []
    for off in offsets:
        reg = random_time(ctx, rng, day0 + timedelta(days=int(off)))
        regs.append(min(reg, ctx.as_of - timedelta(minutes=30)))

    # --- who gets a risk pattern (chosen before ids exist, so ring signups can be clustered)
    counts = persona_counts(n)
    persona: dict[int, tuple[str, int | None]] = {}
    cutoff = ctx.as_of - timedelta(days=25)
    eligible = [j for j in range(n) if regs[j] <= cutoff]
    needed = sum(counts[k] for k in PERSONA_BASE) + sum(
        RING_SIZES[r % 3] for r in range(counts["rings"])
    )
    if len(eligible) < needed:
        raise SystemExit("Not enough players old enough for the risk patterns: raise --days")
    picked = [int(x) for x in rng.choice(eligible, size=needed, replace=False)]
    it = iter(picked)
    for kind in PERSONA_BASE:
        for _ in range(counts[kind]):
            persona[next(it)] = (kind, None)
    for r in range(counts["rings"]):
        anchor_day = int(rng.integers(int(cfg.days * 0.15), int(cfg.days * 0.75)))
        anchor = day0 + timedelta(days=anchor_day)
        for _ in range(RING_SIZES[r % 3]):
            j = next(it)
            persona[j] = ("ring", r)
            regs[j] = random_time(ctx, rng, anchor + timedelta(days=int(rng.integers(0, 4))))

    order = sorted(range(n), key=lambda j: regs[j])
    ring_devices: dict[int, tuple[str, str, tuple[int, int, int]]] = {}
    for r in range(counts["rings"]):
        fp = rng.bytes(16).hex()
        ring_devices[r] = (
            "desktop",
            fp,
            (190, int(rng.integers(20, 250)), int(rng.integers(1, 250))),
        )

    # --- identity and profile, in id order (Faker is seeded once, so order = reproducible)
    Faker.seed(cfg.seed)
    ctx.fake = Faker(sorted({v[1] for v in COUNTRIES.values()}))
    codes = list(COUNTRIES)
    c_p = np.array([COUNTRIES[c][0] for c in codes], dtype=float)
    c_p /= c_p.sum()
    arch_names = list(ARCHETYPES)
    arch_p = np.array([ARCHETYPES[a]["share"] for a in arch_names])
    arch_p /= arch_p.sum()
    used_usernames: set[str] = set()

    for new_id, j in enumerate(order, start=1):
        prng = np.random.default_rng([cfg.seed, 5, new_id])
        kind, ring = persona.get(j, (None, None))
        m = PlayerMeta(id=new_id, registered_at=regs[j], persona=kind, ring=ring)
        m.country = codes[int(prng.choice(len(codes), p=c_p))]
        m.locale = COUNTRIES[m.country][1]
        prefix = COUNTRIES[m.country][2][int(prng.integers(0, len(COUNTRIES[m.country][2])))]
        m.home_ip = (prefix[0], prefix[1], int(prng.integers(1, 255)), int(prng.integers(1, 255)))
        loc = ctx.fake[m.locale]
        m.first_name, m.last_name = loc.first_name(), loc.last_name()
        base = (ascii_slug(m.first_name)[:1] + ascii_slug(m.last_name.split()[0]))[:30] or "player"
        name = f"{base}{int(prng.integers(1, 99))}"
        while name in used_usernames:
            name = f"{base}{int(prng.integers(100, 9999))}"
        used_usernames.add(name)
        m.username = name
        domain = ["gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "icloud.com"][
            int(prng.choice(5, p=[0.5, 0.2, 0.15, 0.1, 0.05]))
        ]
        m.email = f"{name}@{domain}".lower()
        age_years = min(18.2 + float(prng.gamma(3.0, 7.0)), 75.0)
        m.birth_date = (m.registered_at - timedelta(days=int(age_years * 365.25))).date()
        m.channel = "web" if prng.random() < 0.55 else "mobile"

        m.archetype = arch_names[int(prng.choice(len(arch_names), p=arch_p))]
        if kind == "oddbet":
            m.archetype, m.min_life_days = "casual", 60
        elif kind in ("rapid", "structuring", "chaser"):
            m.archetype, m.min_life_days = "regular", 45
        elif kind == "ring":
            m.archetype = "casual" if new_id % 2 else "regular"
            m.ring_device = ring_devices[ring]
            m.country = "CO"

        # account status: persona players stay active; the rest drifts a little
        if kind is None:
            m.status = ["active", "suspended", "self_excluded", "closed"][
                int(prng.choice(4, p=[0.90, 0.04, 0.03, 0.03]))
            ]
            lo, hi = m.registered_at + timedelta(days=2), ctx.as_of - timedelta(days=1)
            if m.status != "active":
                if lo >= hi:
                    m.status = "active"
                else:
                    span = int((hi - lo).total_seconds())
                    m.status_changed_at = lo + timedelta(seconds=int(prng.integers(0, span)))
            if m.status == "self_excluded":
                period = [30, 90, 180, 365][int(prng.integers(0, 4))]
                until = m.status_changed_at + timedelta(days=period)
                m.self_exclusion_until = max(until, ctx.as_of + timedelta(days=14))

        # KYC: only verified players can withdraw
        recent = m.registered_at > ctx.as_of - timedelta(days=14)
        if kind in ("rapid", "structuring", "chaser", "oddbet"):
            m.kyc = "verified"
        elif kind == "ring" or m.archetype == "dormant":
            m.kyc = "pending"
        elif m.status == "suspended":
            m.kyc = ["verified", "rejected", "pending"][int(prng.choice(3, p=[0.4, 0.4, 0.2]))]
        elif m.status == "closed":
            m.kyc = "rejected" if prng.random() < 0.15 else "verified"
        else:
            m.kyc = "verified" if prng.random() < (0.35 if recent else 0.9) else "pending"

        # responsible-gambling limits (never on players that must show risk behaviour)
        if kind is None and m.archetype != "dormant":
            if prng.random() < 0.22:
                m.deposit_limit_c = int(prng.choice([20000, 50000, 100000, 200000, 500000]))
            if prng.random() < 0.12:
                m.loss_limit_c = int(prng.choice([10000, 30000, 100000]))
        ctx.players.append(m)


# ---------------------------------------------------------------------------------------------
# Simulation of one player (ledger-safe primitives + persona hooks)
# ---------------------------------------------------------------------------------------------


@dataclass
class DepositResult:
    tx_id: int
    status: str
    amount_c: int
    created_at: datetime


@dataclass
class SessionResult:
    session_id: int
    game: Game
    stakes: list[int]
    payouts: list[int]


class PlayerSim:
    def __init__(self, m: PlayerMeta, ctx: Ctx):
        self.m, self.ctx = m, ctx
        self.rng = rng = np.random.default_rng([ctx.cfg.seed, 7, m.id])
        a = ARCHETYPES[m.archetype]
        self.balance = 0
        self.clock = m.registered_at
        life = max(float(rng.exponential(a["life"])) if a["life"] else 0.0, m.min_life_days)
        self.hard_end = min(ctx.as_of - timedelta(minutes=2), m.status_changed_at or ctx.as_of)
        self.play_until = min(self.hard_end, m.registered_at + timedelta(days=life))
        self.rate = a["rate"] * float(rng.lognormal(0, 0.35))
        self.dep_med_c = int(a["dep"] * float(rng.lognormal(0, 0.3)))
        self.dep_sigma = a["sigma"]
        self.base_stake_c = ladder_floor(int(self.dep_med_c / float(rng.uniform(10, 25))))
        if m.persona == "oddbet":
            self.base_stake_c = int(rng.choice([100, 200]))
        self.method_p = rng.dirichlet(np.array([0.45, 0.30, 0.15, 0.10]) * 8)
        weights = np.array([g.weight for g in ctx.games])
        k = int(rng.integers(3, 7))
        self.favs = rng.choice(len(ctx.games), size=k, replace=False, p=weights / weights.sum())
        self.fav_p = rng.dirichlet(np.ones(k) * 2)
        self.all_p = weights / weights.sum()
        main = "desktop" if m.channel == "web" else "mobile"
        self.devices = [(main, rng.bytes(16).hex())]
        if rng.random() < 0.2:
            other = "mobile" if main == "desktop" else "tablet"
            self.devices.append((other, rng.bytes(16).hex()))
        if m.ring_device:
            self.devices = [(m.ring_device[0], m.ring_device[1])]
        self.last_method: str | None = None
        self.deposits_ok = 0
        self.bonus: list | None = None
        self.month_deposits: dict[int, int] = defaultdict(int)
        self.month_loss: dict[int, int] = defaultdict(int)
        self.stake_list: list[int] = []
        self.last_change = m.registered_at

    # ----- time -----------------------------------------------------------------------------

    def time_on(self, day: date) -> datetime:
        return random_time(self.ctx, self.rng, utc_midnight(day))

    def advance_to(self, ts: datetime) -> None:
        if ts > self.clock:
            self.clock = ts
        else:
            self.clock += timedelta(seconds=int(self.rng.integers(60, 1800)))

    def tick(self, lo: int, hi: int) -> None:
        self.clock += timedelta(seconds=int(self.rng.integers(lo, hi + 1)))

    # ----- money primitives -----------------------------------------------------------------

    def pick_method(self) -> str:
        return METHODS[int(self.rng.choice(len(METHODS), p=self.method_p))]

    def deposit_size(self) -> int:
        return nice(int(math.exp(self.rng.normal(math.log(self.dep_med_c), self.dep_sigma))))

    def _new_tx(self, ttype, status, amount_c, method, created, completed, admin=None, note=None):
        tid = self.ctx.next_id("tx")
        ref = None
        if method:
            digest = hashlib.blake2b(f"{self.ctx.cfg.seed}:{tid}".encode(), digest_size=8)
            ref = f"{METHOD_PREFIX[method]}-{digest.hexdigest().upper()}"
        ip = None if ttype in (T_BONUS, T_ADJUST) else ip_text(self.m.home_ip)
        self.ctx.tx.append(
            [tid, self.m.id, ttype, status, amount_c, method, created, completed, ref,
             admin, note, ip]
        )  # fmt: skip
        return tid

    def deposit(
        self, amount_c: int, method: str | None = None, *, force_ok: bool = False
    ) -> DepositResult | None:
        ctx, rng, m = self.ctx, self.rng, self.m
        if self.clock >= self.hard_end:
            return None
        limit = m.deposit_limit_c
        if limit is not None:
            room = limit - self.month_deposits[month_key(self.clock)]
            amount_c = min(amount_c, room // 500 * 500)
        if amount_c < MIN_DEPOSIT_C:
            return None
        method = method or self.pick_method()
        created = self.clock
        r = float(rng.random())
        status = S_DONE if force_ok or r >= 0.06 else (S_FAILED if r < 0.045 else S_CANCELLED)
        completed = None
        if status == S_DONE:
            lo, hi = METHOD_DELAY_S[method]
            completed = created + timedelta(seconds=int(rng.integers(lo, hi + 1)))
            if completed > ctx.as_of - timedelta(minutes=1):
                status, completed = S_PENDING, None
        tid = self._new_tx(T_DEPOSIT, status, amount_c, method, created, completed)
        if status in (S_DONE, S_PENDING):
            self.month_deposits[month_key(created)] += amount_c
        if status == S_DONE:
            self.balance += amount_c
            self.deposits_ok += 1
            self.last_method = method
            self.clock = completed + timedelta(seconds=int(rng.integers(5, 40)))
            self.last_change = completed
            self._deposit_bonuses(amount_c)
        else:
            self.clock = created + timedelta(seconds=int(rng.integers(20, 90)))
        return DepositResult(tid, status, amount_c, created)

    def _deposit_bonuses(self, amount_c: int) -> None:
        m, rng = self.m, self.rng
        welcome_p = 1.0 if m.persona == "ring" else 0.55
        if self.deposits_ok == 1 and rng.random() < welcome_p:
            self.grant_bonus("welcome", min(amount_c, 20_000), 30.0, 30)
        elif self.deposits_ok > 1 and rng.random() < 0.06:
            self.grant_bonus("deposit_match", min(amount_c // 2, 10_000), 25.0, 21)

    def _refresh_bonus(self) -> None:
        if self.bonus and self.clock >= self.bonus[8] and self.bonus[3] == "active":
            self.bonus[3] = "expired"
            self.bonus = None

    def grant_bonus(self, btype: str, amount_c: int, mult: float, valid_days: int) -> None:
        self._refresh_bonus()
        amount_c = amount_c // 100 * 100
        if self.bonus is not None or amount_c < 500 or self.clock >= self.hard_end:
            return
        tid = self._new_tx(T_BONUS, S_DONE, amount_c, None, self.clock, self.clock)
        row = [self.ctx.next_id("bonus"), self.m.id, btype, "active", amount_c, mult, 0,
               self.clock, self.clock + timedelta(days=valid_days), None, tid]  # fmt: skip
        self.ctx.bonuses.append(row)
        self.bonus = row
        self.balance += amount_c
        self.last_change = self.clock

    def adjustment(self, amount_c: int) -> None:
        ctx = self.ctx
        if self.clock >= self.hard_end:
            return
        admin = int(self.rng.choice(ctx.support_ids))
        note = ADJUSTMENT_NOTES[int(self.rng.integers(0, len(ADJUSTMENT_NOTES)))]
        self._new_tx(T_ADJUST, S_DONE, amount_c, None, self.clock, self.clock, admin, note)
        self.balance += amount_c
        self.last_change = self.clock

    def withdraw(self, amount_c: int, *, force_ok: bool = False) -> int | None:
        ctx, rng = self.ctx, self.rng
        self._refresh_bonus()
        if amount_c < MIN_WITHDRAWAL_C or amount_c > self.balance or self.clock >= self.hard_end:
            return None
        method = self.last_method or self.pick_method()
        created = self.clock
        r = float(rng.random())
        status = S_DONE if force_ok or r >= 0.06 else (S_FAILED if r < 0.04 else S_CANCELLED)
        completed = None
        if status == S_DONE:
            lo, hi = (12 * 3600, 72 * 3600) if method == "bank_transfer" else (3600, 36 * 3600)
            if force_ok:
                lo, hi = 3600, 4 * 3600
            completed = created + timedelta(seconds=int(rng.integers(lo, hi + 1)))
            if completed > ctx.as_of - timedelta(minutes=1):
                status, completed = S_PENDING, None
        tid = self._new_tx(T_WITHDRAWAL, status, amount_c, method, created, completed)
        if status in (S_DONE, S_PENDING):  # funds are reserved from the request
            self.balance -= amount_c
            self.last_change = created
            if self.bonus is not None:  # withdrawing while a bonus is open forfeits it
                self.bonus[3] = "forfeited"
                self.bonus = None
        self.tick(30, 300)
        return tid

    # ----- playing --------------------------------------------------------------------------

    def pick_game(self, *, max_c: int | None = None, min_max_c: int | None = None) -> Game:
        ctx, rng = self.ctx, self.rng
        for _ in range(50):
            if max_c is None and min_max_c is None and rng.random() < 0.85:
                g = ctx.games[int(rng.choice(self.favs, p=self.fav_p))]
            else:
                g = ctx.games[int(rng.choice(len(ctx.games), p=self.all_p))]
            if g.retired_at is not None and self.clock >= g.retired_at:
                continue
            if max_c is not None and g.max_c != max_c:
                continue
            if min_max_c is not None and g.max_c < min_max_c:
                continue
            return g
        live = [g for g in ctx.games if g.retired_at is None]
        return live[int(rng.integers(0, len(live)))]

    def n_bets(self, g: Game) -> int:
        n = round(float(self.rng.lognormal(math.log(g.bets_median), g.bets_sigma)))
        return int(min(max(n, 2), 70))

    def _session_ip(self) -> tuple[str, str]:
        m, rng = self.m, self.rng
        if rng.random() < 0.03:  # VPN / travelling
            other = [c for c in COUNTRIES if c != m.country]
            code = other[int(rng.integers(0, len(other)))]
            pre = COUNTRIES[code][2][0]
            return ip_text(
                (pre[0], pre[1], int(rng.integers(1, 255)), int(rng.integers(1, 255)))
            ), code
        a, b, c, d = m.home_ip
        if m.ring_device:
            a, b, c = m.ring_device[2]
        r = rng.random()
        if r < 0.80:
            d = int(rng.integers(1, 255))
        elif r < 0.95:
            c, d = int(rng.integers(1, 255)), int(rng.integers(1, 255))
        return ip_text((a, b, c, d)), m.country

    def play(
        self, g: Game, n_bets: int, *, mode: str = "normal", base_stake_c: int | None = None,
        force_losses: int = 0, fixed_stake_c: int | None = None,
    ) -> SessionResult | None:  # fmt: skip
        ctx, rng, m = self.ctx, self.rng, self.m
        self._refresh_bonus()
        lad = g.ladder
        if not lad or self.balance < lad[0] or self.clock >= self.hard_end:
            return None
        n = n_bets
        u, z, v = rng.random(n), rng.standard_normal(n), rng.random(n)
        gaps = rng.integers(g.gap_lo, g.gap_hi + 1, n)
        base = base_stake_c if base_stake_c is not None else self.base_stake_c
        base_idx = max(0, bisect.bisect_right(lad, base) - 1)
        lo, hi = max(0, base_idx - 2), min(len(lad) - 1, base_idx + 2)
        idx = base_idx
        if fixed_stake_c:
            idx = max(0, bisect.bisect_right(lad, fixed_stake_c) - 1)
        t = self.clock + timedelta(seconds=int(rng.integers(5, 15)))
        started = t - timedelta(seconds=int(rng.integers(1, 4)))
        placed: list[tuple[datetime, int, int]] = []
        for i in range(n):
            if t >= self.hard_end or t >= ctx.as_of - timedelta(minutes=2):
                break
            while idx >= 0 and lad[idx] > self.balance:
                idx -= 1
            if idx < 0:
                break
            stake = lad[idx]
            payout = 0
            if i >= force_losses and u[i] < g.p_win:
                mult = g.mean_mult * math.exp(g.sigma * z[i] - g.sigma**2 / 2)
                payout = int(round(stake * min(mult, MAX_MULTIPLIER)))
            self.balance += payout - stake
            placed.append((t, stake, payout))
            mk = month_key(t)
            self.month_loss[mk] += stake - payout
            if self.bonus is not None:
                b = self.bonus
                if t >= b[8]:
                    b[3], self.bonus = "expired", None
                else:
                    b[6] += stake
                    required = int(b[4] * b[5])
                    if b[6] >= required:
                        b[6], b[3], b[9], self.bonus = required, "completed", t, None
            if m.loss_limit_c and self.month_loss[mk] >= m.loss_limit_c:
                break
            if mode == "normal":
                if payout > stake:
                    if v[i] < 0.10:
                        idx = min(hi, idx + 1)
                    elif v[i] > 0.95 and idx > lo:
                        idx -= 1
                elif v[i] < 0.08 and idx > lo:
                    idx -= 1
            elif mode == "chase":
                idx = min(len(lad) - 1, idx + 1) if payout < stake else base_idx
            t += timedelta(seconds=int(gaps[i]))
        if not placed:
            return None
        dev_type, fingerprint = self.devices[0]
        if len(self.devices) > 1 and rng.random() < 0.3:
            dev_type, fingerprint = self.devices[1]
        ip, country = self._session_ip()
        sid = ctx.next_id("session")
        ended = placed[-1][0] + timedelta(seconds=int(rng.integers(1, 10)))
        ctx.sessions.append([sid, m.id, g.id, started, ended, dev_type, ip, country, fingerprint])
        for ts, stake, payout in placed:
            ctx.bets.append([ctx.next_id("bet"), sid, stake, payout, ts])
        stakes = [p[1] for p in placed]
        self.stake_list.extend(stakes)
        m.turnover_c += sum(stakes)
        m.last_session_at = ended
        self.clock = ended
        self.last_change = ended
        return SessionResult(sid, g, stakes, [p[2] for p in placed])

    # ----- everyday behaviour ---------------------------------------------------------------

    def ensure_funds(self) -> bool:
        rng = self.rng
        floor = max(100, 3 * self.base_stake_c)
        if self.balance >= floor:
            return True
        if self.deposits_ok and rng.random() > 0.80:
            return self.balance >= max(50, self.base_stake_c)
        amount = self.deposit_size()
        res = self.deposit(amount)
        if res is not None and res.status in (S_FAILED, S_CANCELLED) and rng.random() < 0.7:
            self.tick(30, 150)
            self.deposit(amount)  # one retry only: never looks like a burst of deposits
        return self.balance >= max(50, self.base_stake_c)

    def maybe_withdraw(self) -> None:
        rng = self.rng
        if self.m.kyc != "verified" or self.balance < max(3 * self.dep_med_c, 5000):
            return
        if rng.random() >= 0.40:
            return
        amount = int(self.balance * float(rng.uniform(0.5, 1.0))) // 100 * 100
        if STRUCTURING_BAND_C[0] <= amount < STRUCTURING_BAND_C[1]:
            amount = REPORTING_THRESHOLD_C + 500 * int(rng.integers(1, 6))
            amount = min(amount, self.balance // 100 * 100)
            if STRUCTURING_BAND_C[0] <= amount < STRUCTURING_BAND_C[1]:
                amount = 80_000  # background behaviour never lands in the structuring band
        self.tick(60, 600)
        self.withdraw(amount)

    def maybe_extras(self) -> None:
        rng, arch = self.rng, self.m.archetype
        r = float(rng.random())
        if r < 0.03:
            self.grant_bonus("free_spins", nice(int(rng.integers(500, 2000))), 35.0, 7)
        elif r < 0.05 and arch in ("regular", "high_roller"):
            self.grant_bonus("cashback", int(rng.integers(500, 5000)), 1.0, 14)
        elif r < 0.065 and arch in ("regular", "high_roller"):
            self.grant_bonus("loyalty", nice(int(rng.integers(1000, 10000))), 10.0, 30)
        elif r < 0.069 and self.m.persona is None:
            self.adjustment(nice(int(rng.integers(500, 5000))))

    def normal_day(self, day: date) -> None:
        rng = self.rng
        n_sessions = 1 + int(rng.random() < 0.22) + int(rng.random() < 0.08)
        for ts in sorted(self.time_on(day) for _ in range(n_sessions)):
            self.advance_to(ts)
            if self.clock >= self.play_until:
                return
            if not self.ensure_funds():
                return
            g = self.pick_game()
            self.play(g, self.n_bets(g))
        self.maybe_withdraw()
        self.maybe_extras()

    def run(self) -> None:
        m, rng, ctx = self.m, self.rng, self.ctx
        if m.archetype == "dormant":
            if rng.random() < 0.3:
                self.tick(600, 6 * 3600)
                self.deposit(self.deposit_size(), force_ok=False)
            self.finish()
            return
        d0, d1 = m.registered_at.date(), self.play_until.date()
        n_days = (d1 - d0).days + 1
        p_day = [
            self.rate / 7 * WEEKDAY_FACTOR[(d0 + timedelta(days=i)).weekday()]
            for i in range(max(n_days, 0))
        ]
        draws = rng.random(len(p_day)) < np.array(p_day) if p_day else []
        days = {d0 + timedelta(days=i) for i, hit in enumerate(draws) if hit}
        if self.play_until > m.registered_at + timedelta(minutes=45):
            days.add(d0)  # everybody who signs up tries the casino on day one
        hooks = persona_hooks(self)
        for day in sorted(days | set(hooks)):
            if self.clock >= self.hard_end:
                break
            if day in hooks:
                self.advance_to(self.time_on(day))
                hooks[day](self)
            if day in days:
                self.normal_day(day)
        self.finish()
        ctx.counters["players_simulated"] += 1

    def finish(self) -> None:
        m, ctx = self.m, self.ctx
        if m.status == "closed" and m.status_changed_at and self.clock < self.hard_end:
            self.clock = max(self.clock, m.status_changed_at - timedelta(hours=3))
            if m.kyc == "verified":
                self.withdraw(self.balance // 100 * 100, force_ok=True)
        self.clock = min(self.clock, ctx.as_of)
        self._refresh_bonus()
        if self.bonus and self.bonus[8] <= ctx.as_of and self.bonus[3] == "active":
            self.bonus[3] = "expired"
        m.balance_c = self.balance
        m.wallet_updated_at = self.last_change


# ---------------------------------------------------------------------------------------------
# Risk patterns ("personas"): same ledger primitives, deliberately suspicious behaviour
# ---------------------------------------------------------------------------------------------

Hook = Callable[[PlayerSim], None]


def persona_hooks(sim: PlayerSim) -> dict[date, Hook]:
    m, rng, ctx = sim.m, sim.rng, sim.ctx
    if m.persona in (None, "ring"):
        return {}
    first = (m.registered_at + timedelta(days=1)).date()

    def pick(last_offset_days: int, count: int) -> list[date]:
        last = (ctx.as_of - timedelta(days=last_offset_days)).date()
        span = (last - first).days
        offs = rng.choice(span, size=min(count, span), replace=False)
        return [first + timedelta(days=int(o)) for o in offs]

    if m.persona == "rapid":
        return {pick(2, 1)[0]: hook_rapid_deposits}
    if m.persona == "structuring":
        return {pick(6, 1)[0]: hook_structured_withdrawals}
    if m.persona == "chaser":
        return {d: hook_loss_chasing for d in pick(1, int(rng.integers(2, 5)))}
    return {d: hook_unusual_bet for d in pick(1, int(rng.integers(1, 3)))}


def _evidence(player_sim: PlayerSim, kind: str, **data) -> dict:
    ev = {"type": kind, "player": player_sim.m.id, **data}
    player_sim.ctx.evidence.append(ev)
    return ev


def hook_rapid_deposits(sim: PlayerSim) -> None:
    rng = sim.rng
    k = int(rng.integers(5, 9))
    results = []
    for _ in range(k):
        amount = nice(int(rng.uniform(2500, 15000)))
        method = "card" if rng.random() < 0.6 else "e_wallet"
        res = sim.deposit(amount, method)
        if res:
            results.append(res)
        sim.tick(30, 150)
    g = sim.pick_game(min_max_c=10000)
    sim.play(g, 40, base_stake_c=ladder_floor(max(sim.balance // 80, 100)))
    _evidence(
        sim, "rapid_deposits", tx=[r.tx_id for r in results], count=len(results),
        first=results[0].created_at, last=results[-1].created_at,
        total_c=sum(r.amount_c for r in results if r.status == S_DONE),
        failed=sum(1 for r in results if r.status != S_DONE), end=sim.clock,
    )  # fmt: skip


def hook_structured_withdrawals(sim: PlayerSim) -> None:
    rng = sim.rng
    n = int(rng.integers(4, 7))
    amounts = [int(rng.integers(900, 991)) * 100 for _ in range(n)]
    while sim.balance < sum(amounts) + 20_000:
        method = ["card", "e_wallet", "crypto"][int(rng.integers(0, 3))]
        sim.deposit(nice(int(rng.uniform(150_000, 300_000))), method, force_ok=True)
        sim.tick(120, 1800)
    sim.play(sim.pick_game(), 8, base_stake_c=100)  # barely plays: money passes through
    ids = []
    for a in amounts:
        sim.tick(4 * 3600, 12 * 3600)
        tid = sim.withdraw(a, force_ok=True)
        if tid:
            ids.append(tid)
    _evidence(sim, "structured_withdrawals", tx=ids, amounts_c=amounts[: len(ids)], end=sim.clock)


def hook_loss_chasing(sim: PlayerSim) -> None:
    rng = sim.rng
    sessions = []
    for _ in range(int(rng.integers(1, 3))):
        if sim.balance < 20_000:
            sim.deposit(nice(int(rng.uniform(25_000, 50_000))), force_ok=True)
        g = sim.pick_game(max_c=5000)  # stakes climb to 50.00 and stop there
        res = sim.play(
            g, int(rng.integers(9, 15)), mode="chase", base_stake_c=100,
            force_losses=int(rng.integers(6, 9)),
        )  # fmt: skip
        if res:
            sessions.append(res)
        sim.tick(600, 3600)
    if sessions:
        _evidence(sim, "loss_chasing", sessions=sessions, end=sim.clock)


def hook_unusual_bet(sim: PlayerSim) -> None:
    rng = sim.rng
    if sim.balance < 60_000:
        sim.deposit(nice(int(rng.uniform(60_000, 150_000))), force_ok=True)
    g = sim.pick_game(min_max_c=ODD_BET_MIN_C)
    res = sim.play(g, int(rng.integers(3, 6)), mode="odd", fixed_stake_c=ODD_BET_MIN_C)
    if res:
        _evidence(sim, "unusual_bet_size", session=res, sim=sim, end=sim.clock)


# ---------------------------------------------------------------------------------------------
# Assembly: renumber ids chronologically, alerts, notes, audit log, VIP tiers
# ---------------------------------------------------------------------------------------------


def renumber(rows: list[list], time_idx: int) -> dict[int, int]:
    """Give ids 1..N in time order; return old -> new."""
    order = sorted(range(len(rows)), key=lambda i: (rows[i][time_idx], rows[i][0]))
    mapping: dict[int, int] = {}
    for new_id, i in enumerate(order, start=1):
        mapping[rows[i][0]] = new_id
    for r in rows:
        r[0] = mapping[r[0]]
    rows.sort(key=lambda r: r[0])
    return mapping


def assign_vip_tiers(ctx: Ctx) -> None:
    ranked = sorted((m for m in ctx.players if m.turnover_c > 0), key=lambda m: -m.turnover_c)
    cuts = [("diamond", 0.01), ("platinum", 0.04), ("gold", 0.12), ("silver", 0.30)]
    n = len(ranked)
    for rank, m in enumerate(ranked):
        share = (rank + 1) / n
        m.vip_tier = next((name for name, c in cuts if share <= c), "standard")
    for name, _ in cuts:  # a tiny demo still gets every tier
        if n >= 5 and not any(m.vip_tier == name for m in ranked):
            ranked[0].vip_tier = "diamond"


def _pick(rng: np.random.Generator, seq: list):
    return seq[int(rng.integers(0, len(seq)))]


def build_alerts(ctx: Ctx, tx_map: dict[int, int], sess_map: dict[int, int]) -> None:
    rng = np.random.default_rng([ctx.cfg.seed, 11])
    by_player = {m.id: m for m in ctx.players}
    tx_time = {r[0]: r[6] for r in ctx.tx}
    items: list[tuple[str, int, str, datetime, dict]] = []  # type, player, severity, end, details

    for ev in ctx.evidence:
        kind, pid = ev["type"], ev["player"]
        if kind == "rapid_deposits":
            minutes = max(1, round((ev["last"] - ev["first"]).total_seconds() / 60))
            sev = "high" if ev["count"] >= 7 else "medium"
            det = {"rule": "5+ deposit attempts within 30 minutes", "deposit_count": ev["count"],
                   "window_minutes": minutes, "failed_attempts": ev["failed"],
                   "completed_total": money(ev["total_c"]),
                   "transaction_ids": [tx_map[t] for t in ev["tx"]]}  # fmt: skip
        elif kind == "structured_withdrawals":
            tx = [tx_map[t] for t in ev["tx"]]
            hours = max(
                1, round((tx_time[ev["tx"][-1]] - tx_time[ev["tx"][0]]).total_seconds() / 3600)
            )
            sev = "critical" if len(tx) >= 5 else "high"
            det = {"rule": "3+ withdrawals between 85% and 100% of the 1000.00 reporting threshold"
                           " within 72 hours",
                   "threshold": money(REPORTING_THRESHOLD_C), "withdrawal_count": len(tx),
                   "total": money(sum(ev["amounts_c"])), "window_hours": hours,
                   "transaction_ids": tx}  # fmt: skip
        elif kind == "loss_chasing":
            res = max(ev["sessions"], key=lambda s: len(s.stakes))
            net = sum(sum(s.stakes) - sum(s.payouts) for s in ev["sessions"])
            sev = "high" if net >= 30_000 else "medium"
            det = {"rule": "5+ consecutive stake increases after losses in one session",
                   "session_ids": [sess_map[s.session_id] for s in ev["sessions"]],
                   "example_session_id": sess_map[res.session_id], "game": res.game.name,
                   "example_stakes": [money(s) for s in res.stakes[:8]],
                   "net_loss": money(max(net, 0))}  # fmt: skip
        elif kind == "unusual_bet_size":
            continue
        else:
            continue
        items.append((kind, pid, sev, ev["end"], det))

    session_by_id = {session[0]: session for session in ctx.sessions}
    game_by_id = {game.id: game for game in ctx.games}
    player_bets: dict[int, list[list]] = defaultdict(list)
    for bet in ctx.bets:
        player_bets[session_by_id[bet[1]][1]].append(bet)
    for pid, bets in player_bets.items():
        median = float(np.median([bet[2] for bet in bets]))
        suspicious = [bet for bet in bets if bet[2] >= ODD_BET_MIN_C and bet[2] >= 20 * median]
        if not suspicious:
            continue
        bet = max(suspicious, key=lambda row: row[2])
        session = session_by_id[bet[1]]
        game = game_by_id[session[2]]
        top = bet[2]
        sev = "medium" if top < 20_000 else "high"
        det = {
            "rule": "stake >= 100.00 and >= 20x the player's median stake",
            "session_id": sess_map[session[0]],
            "game": game.name,
            "stake": money(top),
            "median_stake": money(int(median)),
            "ratio": round(top / median, 1),
        }
        items.append(("unusual_bet_size", pid, sev, session[4], det))

    rings: dict[int, list[PlayerMeta]] = defaultdict(list)
    for m in ctx.players:
        if m.persona == "ring":
            rings[m.ring].append(m)
    for members in rings.values():
        fp = members[0].ring_device[1]
        linked = [m.id for m in members]
        sev = "critical" if len(members) >= 5 else "high"
        for m in members:
            first_seen = ctx.as_of
            sessions = [s for s in ctx.sessions if s[1] == m.id]
            end = max((s[4] for s in sessions), default=m.registered_at)
            first_seen = min((s[3] for s in sessions), default=first_seen)
            det = {"rule": "1 device fingerprint used by 3+ accounts", "device_fingerprint": fp,
                   "accounts": len(members), "linked_player_ids": linked,
                   "first_seen": first_seen.isoformat()}  # fmt: skip
            items.append(("shared_device", m.id, sev, end, det))

    statuses = ["open", "in_review", "resolved", "dismissed"]
    for kind, pid, sev, end, det in items:
        created = end + timedelta(minutes=int(rng.integers(10, 180)))
        status = statuses[int(rng.choice(4, p=[0.40, 0.22, 0.22, 0.16]))]
        resolved = None
        if created > ctx.as_of - timedelta(minutes=5):
            created, status = ctx.as_of - timedelta(minutes=5), "open"
        if status in ("resolved", "dismissed"):
            resolved = created + timedelta(hours=int(rng.integers(4, 120)))
            if resolved > ctx.as_of:
                status, resolved = "in_review", None
        assigned = None
        if status != "open" or rng.random() < 0.3:
            assigned = _pick(rng, ctx.staff_ids)
        updated = resolved or min(created + timedelta(hours=int(rng.integers(0, 48))), ctx.as_of)
        note = _pick(rng, RESOLUTION_NOTES[status]) if resolved else None
        ctx.alerts.append(
            [0, pid, kind, sev, status, assigned, det, created, updated, resolved, note]
        )
    _ = by_player
    ids = renumber_alerts(ctx.alerts)
    del ids


def renumber_alerts(rows: list[list]) -> dict[int, int]:
    for i, r in enumerate(rows):
        r[0] = i + 1
    return renumber(rows, 7)


def build_notes_and_audit(ctx: Ctx) -> None:
    rng = np.random.default_rng([ctx.cfg.seed, 13])
    alert_players = {a[1] for a in ctx.alerts}
    for m in ctx.players:
        p = 0.60 if m.status != "active" else 0.5 if m.id in alert_players else 0.02
        if rng.random() >= p:
            continue
        end = m.status_changed_at or ctx.as_of
        for _ in range(int(rng.integers(1, 4))):
            span = max(int((end - m.registered_at).total_seconds()), 3600)
            ts = m.registered_at + timedelta(seconds=int(rng.integers(0, span)))
            admin = int(rng.choice(ctx.support_ids if rng.random() < 0.8 else ctx.staff_ids))
            ctx.notes.append([0, m.id, admin, _pick(rng, NOTE_TEMPLATES), ts])
    ctx.notes.sort(key=lambda r: r[4])
    for i, r in enumerate(ctx.notes, start=1):
        r[0] = i

    audit: list[list] = []  # [id, admin, action, resource_type, resource_id, details, ip, ts]

    def add(admin, action, rtype, rid, ts, details=None):
        audit.append([0, admin, action, rtype, None if rid is None else str(rid), details,
                      _pick(rng, ADMIN_IPS), ts])  # fmt: skip

    for n in ctx.notes:
        add(n[2], "player.note.create", "player", n[1], n[4])
    for a in ctx.alerts:
        if a[5]:
            add(a[5], "alert.assign", "risk_alert", a[0], a[7] + timedelta(minutes=20))
        if a[9]:
            add(a[5], "alert.resolve", "risk_alert", a[0], a[9], {"status": a[4]})
    for t in ctx.tx:
        if t[2] == T_ADJUST:
            add(t[9], "transaction.adjust", "transaction", t[0], t[6], {"amount": money(t[4])})
    for m in ctx.players:
        if m.status == "suspended":
            add(_pick(rng, ctx.support_ids), "player.suspend", "player", m.id, m.status_changed_at)
    actives = [a for a in ctx.admin_rows if a[5]]
    n_days = (ctx.as_of - ctx.start).days
    for day in range(n_days):
        base = utc_midnight((ctx.start + timedelta(days=day)).date())
        if base.weekday() >= 5:
            continue
        for a in actives:
            ts = base + timedelta(
                hours=13 + int(rng.integers(0, 6)), minutes=int(rng.integers(0, 60))
            )
            if rng.random() < 0.8 and ts < ctx.as_of:
                add(a[0], "auth.login", "admin_user", a[0], ts)
                for _ in range(int(rng.integers(0, 4))):
                    pid = int(rng.integers(1, len(ctx.players) + 1))
                    add(
                        a[0],
                        "player.view",
                        "player",
                        pid,
                        ts + timedelta(minutes=int(rng.integers(1, 240))),
                    )
    for _ in range(max(3, n_days // 15)):
        ts = ctx.start + timedelta(seconds=int(rng.integers(0, n_days * 86400)))
        add(
            _pick(rng, ctx.staff_ids),
            "export.csv",
            "transactions",
            None,
            ts,
            {"rows": int(rng.integers(50, 5000))},
        )
    audit = [r for r in audit if r[7] <= ctx.as_of]
    audit.sort(key=lambda r: r[7])
    for i, r in enumerate(audit, start=1):
        r[0] = i
    ctx.audit = audit
    last_login: dict[int, datetime] = {}
    for r in audit:
        if r[2] == "auth.login":
            last_login[r[1]] = r[7]
    for a in ctx.admin_rows:
        a[7] = last_login.get(a[0])


def generate(cfg: Config) -> Ctx:
    ctx = Ctx(cfg)
    build_games(ctx)
    build_admins(ctx)
    build_players(ctx)
    for m in ctx.players:
        PlayerSim(m, ctx).run()
    assign_vip_tiers(ctx)
    # chronological ids (players already are: they were numbered by signup time)
    tx_map = renumber(ctx.tx, 6)
    for b in ctx.bonuses:
        b[10] = tx_map[b[10]]
    renumber(ctx.bonuses, 7)
    sess_map = renumber(ctx.sessions, 3)
    for b in ctx.bets:
        b[1] = sess_map[b[1]]
    renumber(ctx.bets, 4)
    build_alerts(ctx, tx_map, sess_map)
    build_notes_and_audit(ctx)
    return ctx


def digest(ctx: Ctx) -> str:
    h = hashlib.sha256()
    for name in ("tx", "bonuses", "sessions", "bets", "alerts", "notes", "audit", "admin_rows"):
        for row in getattr(ctx, name):
            h.update(repr(row).encode())
    for m in ctx.players:
        h.update(
            repr((m.id, m.username, m.email, m.registered_at, m.balance_c, m.vip_tier)).encode()
        )
    return h.hexdigest()[:16]


# ---------------------------------------------------------------------------------------------
# Loading into PostgreSQL
# ---------------------------------------------------------------------------------------------


def table_data(ctx: Ctx):
    """(table, columns, rows) in foreign-key order. Rows are tuples ready for COPY."""
    cat_id = {code: i for i, code in enumerate(CATEGORIES, start=1)}
    yield "roles", ["id", "name", "description"], [(i, n, d) for i, (n, d) in enumerate(ROLES, 1)]
    yield (
        "admin_users",
        [
            "id",
            "username",
            "email",
            "password_hash",
            "full_name",
            "role_id",
            "is_active",
            "created_at",
            "last_login_at",
            "updated_at",
        ],
        [(a[0], a[1].split("@", 1)[0], a[1], *a[2:7], a[7], a[7] or a[6]) for a in ctx.admin_rows],
    )
    yield (
        "game_categories",
        ["id", "code", "name"],
        [(cat_id[c], c, v[0]) for c, v in CATEGORIES.items()],
    )
    yield "games", [
        "id", "category_id", "name", "provider", "theoretical_rtp", "volatility", "min_bet",
        "max_bet", "is_active", "released_at",
    ], [
        (g.id, cat_id[g.category], g.name, g.provider, f"{g.rtp:.2f}", g.volatility, money(g.min_c),
         money(g.max_c), g.retired_at is None, g.released)
        for g in ctx.games
    ]  # fmt: skip
    yield "players", [
        "id", "username", "email", "first_name", "last_name", "birth_date", "country_code",
        "status", "kyc_status", "vip_tier", "registration_channel", "registered_at",
        "last_login_at", "self_exclusion_until", "deposit_limit_monthly", "loss_limit_monthly",
        "updated_at",
    ], [
        (m.id, m.username, m.email, m.first_name, m.last_name, m.birth_date, m.country, m.status,
         m.kyc, m.vip_tier, m.channel, m.registered_at, m.last_session_at or m.registered_at,
         m.self_exclusion_until, None if m.deposit_limit_c is None else money(m.deposit_limit_c),
         None if m.loss_limit_c is None else money(m.loss_limit_c),
         max(m.status_changed_at or m.registered_at, m.last_session_at or m.registered_at))
        for m in ctx.players
    ]  # fmt: skip
    yield (
        "wallets",
        ["player_id", "balance", "updated_at"],
        [(m.id, money(m.balance_c), m.wallet_updated_at or m.registered_at) for m in ctx.players],
    )
    yield (
        "transactions",
        [
            "id",
            "player_id",
            "type",
            "status",
            "amount",
            "method",
            "created_at",
            "completed_at",
            "external_ref",
            "created_by_admin_id",
            "note",
            "ip_address",
        ],
        [(t[0], t[1], t[2], t[3], money(t[4]), *t[5:]) for t in ctx.tx],
    )
    yield (
        "bonuses",
        [
            "id",
            "player_id",
            "type",
            "status",
            "amount",
            "wagering_multiplier",
            "wagered_amount",
            "granted_at",
            "expires_at",
            "completed_at",
            "transaction_id",
        ],
        [
            (b[0], b[1], b[2], b[3], money(b[4]), f"{b[5]:.2f}", money(b[6]), *b[7:])
            for b in ctx.bonuses
        ],
    )
    yield (
        "game_sessions",
        [
            "id",
            "player_id",
            "game_id",
            "started_at",
            "ended_at",
            "device_type",
            "ip_address",
            "country_code",
            "device_fingerprint",
        ],
        ctx.sessions,
    )
    yield (
        "bets",
        ["id", "session_id", "stake", "payout", "placed_at"],
        ((b[0], b[1], money(b[2]), money(b[3]), b[4]) for b in ctx.bets),
    )
    yield "player_notes", ["id", "player_id", "admin_user_id", "note", "created_at"], ctx.notes
    yield (
        "risk_alerts",
        [
            "id",
            "player_id",
            "alert_type",
            "severity",
            "status",
            "assigned_to_admin_id",
            "details",
            "created_at",
            "updated_at",
            "resolved_at",
            "resolution_note",
        ],
        [(a[0], a[1], a[2], a[3], a[4], a[5], json.dumps(a[6]), *a[7:]) for a in ctx.alerts],
    )
    yield "audit_log", [
        "id", "admin_user_id", "action", "resource_type", "resource_id", "details", "ip_address",
        "created_at",
    ], [
        (r[0], r[1], r[2], r[3], r[4], None if r[5] is None else json.dumps(r[5]), r[6], r[7])
        for r in ctx.audit
    ]  # fmt: skip


def psycopg_url(sqlalchemy_url: str) -> str:
    url = make_url(sqlalchemy_url).set(drivername="postgresql")
    return url.render_as_string(hide_password=False)


def load(ctx: Ctx, database_url: str, *, reset: bool) -> None:
    with psycopg.connect(psycopg_url(database_url)) as conn:
        cur = conn.cursor()
        tables = [t.name for t in Base.metadata.sorted_tables]
        missing = [t for t in tables if not _exists(cur, t)]
        if missing:
            raise SystemExit(
                f"Tables missing ({', '.join(missing)}). Run `alembic upgrade head` first."
            )
        if reset:
            cur.execute("TRUNCATE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
        else:
            cur.execute("SELECT count(*) FROM players")
            if cur.fetchone()[0]:
                raise SystemExit("The database already has players. Use --reset to replace them.")
        for table, columns, rows in table_data(ctx):
            sql = f"COPY {table} ({', '.join(columns)}) FROM STDIN"
            with cur.copy(sql) as copy:
                for row in rows:
                    copy.write_row(row)
            if "id" in columns:
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"(SELECT max(id) FROM {table})) WHERE EXISTS (SELECT 1 FROM {table})"
                )
        cur.execute("REFRESH MATERIALIZED VIEW daily_game_stats")
        problems = run_checks(cur, ctx)
        if problems:
            conn.rollback()
            raise SystemExit("Validation failed, nothing was saved:\n - " + "\n - ".join(problems))
        conn.commit()
        cur.execute("ANALYZE")
        conn.commit()


def _exists(cur, table: str) -> bool:
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    return cur.fetchone()[0]


# ---------------------------------------------------------------------------------------------
# Validation (also used by the tests): money adds up, nothing is in the future, rules == alerts
# ---------------------------------------------------------------------------------------------

LEDGER_EVENTS = """
    SELECT player_id, COALESCE(completed_at, created_at) AS ts, 0 AS ord,
           CASE WHEN type IN ('deposit', 'bonus_credit', 'adjustment') AND status = 'completed'
                THEN amount ELSE 0 END AS delta
    FROM transactions WHERE type <> 'withdrawal'
    UNION ALL
    SELECT player_id, created_at, 0,
           CASE WHEN status IN ('completed', 'pending') THEN -amount ELSE 0 END
    FROM transactions WHERE type = 'withdrawal'
    UNION ALL
    SELECT s.player_id, b.placed_at, 1, b.payout - b.stake
    FROM bets b JOIN game_sessions s ON s.id = b.session_id
"""

RULE_QUERIES = {
    "rapid_deposits": """
        SELECT DISTINCT t1.player_id FROM transactions t1
        WHERE t1.type = 'deposit' AND (
            SELECT count(*) FROM transactions t2
            WHERE t2.player_id = t1.player_id AND t2.type = 'deposit'
              AND t2.created_at >= t1.created_at
              AND t2.created_at < t1.created_at + interval '30 minutes') >= 5""",
    "structured_withdrawals": f"""
        SELECT DISTINCT t1.player_id FROM transactions t1
        WHERE t1.type = 'withdrawal' AND t1.status IN ('completed', 'pending')
          AND t1.amount >= {STRUCTURING_BAND_C[0] / 100} AND t1.amount < {STRUCTURING_BAND_C[1] / 100}
          AND (
            SELECT count(*) FROM transactions t2
            WHERE t2.player_id = t1.player_id AND t2.type = 'withdrawal'
              AND t2.status IN ('completed', 'pending')
              AND t2.amount >= {STRUCTURING_BAND_C[0] / 100} AND t2.amount < {STRUCTURING_BAND_C[1] / 100}
              AND t2.created_at >= t1.created_at
              AND t2.created_at < t1.created_at + interval '72 hours') >= 3""",
    "shared_device": """
        SELECT DISTINCT player_id FROM game_sessions WHERE device_fingerprint IN (
            SELECT device_fingerprint FROM game_sessions
            GROUP BY device_fingerprint HAVING count(DISTINCT player_id) >= 3)""",
    "unusual_bet_size": f"""
        WITH med AS (
            SELECT s.player_id, percentile_cont(0.5) WITHIN GROUP (ORDER BY b.stake) AS m
            FROM bets b JOIN game_sessions s ON s.id = b.session_id GROUP BY s.player_id)
        SELECT DISTINCT s.player_id
        FROM bets b JOIN game_sessions s ON s.id = b.session_id JOIN med ON med.player_id = s.player_id
        WHERE b.stake >= {ODD_BET_MIN_C / 100} AND b.stake >= 20 * med.m""",
}


def chasing_players(cur) -> set[int]:
    """Sessions with 5+ consecutive stake increases, each right after a losing bet."""
    cur.execute(
        "SELECT s.player_id, b.session_id, b.stake, b.payout FROM bets b "
        "JOIN game_sessions s ON s.id = b.session_id ORDER BY b.session_id, b.id"
    )
    found: set[int] = set()
    session, run, prev = None, 0, None
    for player_id, session_id, stake, payout in cur:
        if session_id != session:
            session, run, prev = session_id, 0, None
        elif prev and stake > prev[0] and prev[1] < prev[0]:
            run += 1
            if run >= 5:
                found.add(player_id)
        else:
            run = 0
        prev = (stake, payout)
    return found


def run_checks(cur, ctx: Ctx) -> list[str]:
    problems: list[str] = []

    def one(sql: str, *params):
        cur.execute(sql, params)
        return cur.fetchone()[0]

    wrong = one(f"""
        WITH ev AS ({LEDGER_EVENTS}), led AS (SELECT player_id, sum(delta) AS bal FROM ev GROUP BY 1)
        SELECT count(*) FROM wallets w LEFT JOIN led ON led.player_id = w.player_id
        WHERE w.balance <> COALESCE(led.bal, 0)""")
    if wrong:
        problems.append(f"{wrong} wallets do not match their ledger")
    negative = one(f"""
        WITH ev AS ({LEDGER_EVENTS}), run AS (
            SELECT sum(delta) OVER (PARTITION BY player_id ORDER BY ts, ord
                                    ROWS UNBOUNDED PRECEDING) AS bal FROM ev)
        SELECT count(*) FROM run WHERE bal < 0""")
    if negative:
        problems.append(f"{negative} ledger steps leave a negative balance at some point in time")
    future = one(
        "SELECT (SELECT count(*) FROM transactions WHERE created_at > %s OR completed_at > %s)"
        " + (SELECT count(*) FROM bets WHERE placed_at > %s)"
        " + (SELECT count(*) FROM game_sessions WHERE ended_at > %s)",
        ctx.as_of, ctx.as_of, ctx.as_of, ctx.as_of,
    )  # fmt: skip
    if future:
        problems.append(f"{future} rows are dated after --as-of")
    early = one(
        "SELECT (SELECT count(*) FROM transactions t JOIN players p ON p.id = t.player_id"
        "        WHERE t.created_at < p.registered_at)"
        " + (SELECT count(*) FROM game_sessions s JOIN players p ON p.id = s.player_id"
        "        WHERE s.started_at < p.registered_at)"
    )
    if early:
        problems.append(f"{early} rows happen before the player registered")
    outside = one(
        "SELECT count(*) FROM bets b JOIN game_sessions s ON s.id = b.session_id "
        "WHERE b.placed_at < s.started_at OR b.placed_at > s.ended_at"
    )
    if outside:
        problems.append(f"{outside} bets fall outside their session")

    cur.execute("SELECT alert_type, player_id FROM risk_alerts")
    alerted: dict[str, set[int]] = defaultdict(set)
    for kind, pid in cur.fetchall():
        alerted[kind].add(pid)
    for kind, sql in RULE_QUERIES.items():
        cur.execute(sql)
        flagged = {r[0] for r in cur.fetchall()}
        if flagged != alerted[kind]:
            problems.append(
                f"rule {kind}: flags {len(flagged)} players, alerts exist for {len(alerted[kind])}"
                f" (difference: {sorted(flagged ^ alerted[kind])[:8]})"
            )
    flagged = chasing_players(cur)
    if flagged != alerted["loss_chasing"]:
        problems.append(
            f"rule loss_chasing: flags {len(flagged)} players, alerts exist for "
            f"{len(alerted['loss_chasing'])} (difference: {sorted(flagged ^ alerted['loss_chasing'])[:8]})"
        )
    return problems


def summary(cur, ctx: Ctx) -> str:
    def one(sql):
        cur.execute(sql)
        return cur.fetchone()[0]

    lines = [f"as of {ctx.as_of:%Y-%m-%d %H:%M} UTC, seed {ctx.cfg.seed}, {ctx.cfg.days} days"]
    for t in ("players", "wallets", "transactions", "bonuses", "game_sessions", "bets",
              "risk_alerts", "player_notes", "audit_log", "games", "admin_users"):  # fmt: skip
        lines.append(f"  {t:<15}{one(f'SELECT count(*) FROM {t}'):>9,}")
    staked, paid = one("SELECT sum(stake) FROM bets"), one("SELECT sum(payout) FROM bets")
    lines.append(f"  total staked {staked:,.2f}  paid {paid:,.2f}  GGR {staked - paid:,.2f}"
                 f"  (hold {100 * (staked - paid) / staked:.2f}%)")  # fmt: skip
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------


def parse_as_of(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Load realistic mock data into the casino database.")
    p.add_argument("--database-url", default=settings.database_url)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--as-of", type=parse_as_of, help="'now' of the data, e.g. 2026-10-23 (UTC)")
    p.add_argument("--days", type=int, default=180, help="length of the history (default 180)")
    p.add_argument("--players", type=int, default=1200)
    p.add_argument("--admin-password", default="Demo-Casino-2026!")
    p.add_argument("--reset", action="store_true", help="delete existing data first")
    args = p.parse_args(argv)
    cfg = Config(seed=args.seed, days=args.days, players=args.players,
                 admin_password=args.admin_password)  # fmt: skip
    if args.as_of:
        cfg.as_of = args.as_of
    if cfg.days < 60:
        raise SystemExit("--days must be at least 60")
    print(f"Generating data (as of {cfg.as_of:%Y-%m-%d}, seed {cfg.seed}) ...")
    ctx = generate(cfg)
    print(f"Loading into {make_url(args.database_url).render_as_string()} ...")
    load(ctx, args.database_url, reset=args.reset)
    with psycopg.connect(psycopg_url(args.database_url)) as conn:
        print(summary(conn.cursor(), ctx))
    print(f"Validation passed. Dataset digest: {digest(ctx)}")
    print(f"Admin accounts use the password: {cfg.admin_password}  (demo only)")


if __name__ == "__main__":
    main()
