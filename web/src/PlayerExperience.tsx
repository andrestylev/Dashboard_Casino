import { createContext, useContext, useEffect, useState } from "react";
import type { FormEvent, InputHTMLAttributes, ReactNode } from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import playerWalletIcon from "./assets/player-wallet.svg";
import velvetChipIcon from "./assets/velvet-chip.svg";
import vipCrownIcon from "./assets/vip-crown.svg";
import { ApiError, apiRequest } from "./api";

type Player = {
  id: number;
  username: string;
  first_name: string;
  balance: number;
  chip_balance: number;
  wallet_balance: number | string;
  vip_tier: string;
  vip_expires_at: string | null;
};

type PlayerWallet = {
  player: Player;
  wallet_balance: number | string;
  chip_balance: number;
  vip_tier: string;
  vip_expires_at: string | null;
  vip_discount: number | string;
  packages: { chips: number; base_price: number | string }[];
  vip_plans: { tier: string; price: number | string; discount: number | string }[];
  transactions: {
    id: number;
    type: string;
    amount: number | string;
    method: string | null;
    origin: string;
    note: string | null;
    created_at: string;
  }[];
  chip_entries: {
    id: number;
    delta: number;
    reason: string;
    created_at: string;
  }[];
};

type PlayerContextValue = {
  player: Player | null;
  setPlayer: (player: Player | null) => void;
};

type GameRound = {
  id: string;
  game: "slots" | "blackjack" | "roulette";
  status: "in_progress" | "completed";
  stake: number;
  symbols?: string[];
  winning_number?: number;
  color?: "red" | "black" | "green";
  bets?: { kind: RouletteBetKind; value: string | number; amount: number; won: boolean; payout: number }[];
  dealer_hand?: string[];
  hands?: { cards: string[]; status: string; stake: number }[];
  current_hand?: number;
  can_split?: boolean;
  outcome?: {
    result?: string;
    payout?: number;
    requested_payout?: number;
    multiplier?: number;
    winning_number?: number;
    color?: "red" | "black" | "green";
    bets?: { kind: RouletteBetKind; value: string | number; amount: number; won: boolean; payout: number }[];
    dealer_score?: number;
    hands?: { result: string; score: number; stake: number; payout: number }[];
  };
};

type RouletteBetKind = "number" | "color" | "parity" | "dozen";
type RouletteWager = { kind: RouletteBetKind; value: string | number; amount: number };
const ROULETTE_DEFAULT_VALUES: Record<RouletteBetKind, string> = {
  number: "0",
  color: "red",
  parity: "odd",
  dozen: "1",
};

const ROULETTE_WHEEL_ORDER = [
  0, 32, 15, 19, 4, 21, 2, 25, 17, 34, 6, 27, 13, 36, 11, 30, 8, 23, 10,
  5, 24, 16, 33, 1, 20, 14, 31, 9, 22, 18, 29, 7, 28, 12, 35, 3, 26,
];

const PlayerContext = createContext<PlayerContextValue | null>(null);

function usePlayer() {
  const context = useContext(PlayerContext);
  if (!context) throw new Error("Player experience context is unavailable");
  return context;
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "Ocurrió un error inesperado.";
}

function formatUsd(value: number | string): string {
  const amount = Number(value);
  return new Intl.NumberFormat("es-ES", {
    style: "currency",
    currency: "USD",
  }).format(Number.isFinite(amount) ? amount : 0);
}

export default function PlayerExperience() {
  const [player, setPlayer] = useState<Player | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    apiRequest<{ player: Player }>("/api/player/me")
      .then(({ player: current }) => setPlayer(current))
      .catch((error: unknown) => {
        if (!(error instanceof ApiError) || error.status !== 401) {
          console.error("Could not restore the player session", error);
        }
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!player) return;
    const timer = window.setInterval(() => {
      apiRequest<{ player: Player }>("/api/player/me")
        .then(({ player: updated }) => setPlayer(updated))
        .catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 401) {
            setPlayer(null);
            return;
          }
          console.error("Could not refresh the player wallet", error);
        });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [player?.id]);

  if (loading) {
    return <div className="player-loading"><span className="spinner" /> Cargando casino...</div>;
  }

  return (
    <PlayerContext.Provider value={{ player, setPlayer }}>
      <div className="player-app">
        <Routes>
          <Route path="/" element={<Lobby />} />
          <Route path="/login" element={player ? <Navigate to="/casino" replace /> : <PlayerAuth mode="login" />} />
          <Route path="/register" element={player ? <Navigate to="/casino" replace /> : <PlayerAuth mode="register" />} />
          <Route path="/wallet" element={<PlayerGate><PlayerWalletPage /></PlayerGate>} />
          <Route path="/slots" element={<PlayerGate><SlotsGame /></PlayerGate>} />
          <Route path="/blackjack" element={<PlayerGate><BlackjackGame /></PlayerGate>} />
          <Route path="/roulette" element={<PlayerGate><RouletteGame /></PlayerGate>} />
          <Route path="*" element={<Navigate to="/casino" replace />} />
        </Routes>
      </div>
    </PlayerContext.Provider>
  );
}

function PlayerGate({ children }: { children: ReactNode }) {
  const { player } = usePlayer();
  return player ? children : <Navigate to="/casino/login" replace />;
}

function PlayerHeader() {
  const { player, setPlayer } = usePlayer();
  const navigate = useNavigate();

  async function signOut() {
    try {
      await apiRequest<void>("/api/player/logout", { method: "POST" });
      setPlayer(null);
      navigate("/casino/login");
    } catch (error) {
      console.error("Could not sign out player", error);
    }
  }

  return (
    <header className="player-header">
      <Link to="/casino" className="player-brand">
        <span className="player-brand-mark">♠</span>
        <span>VELVET<span className="player-brand-accent">PLAY</span></span>
      </Link>
      <nav aria-label="Navegación del casino">
        <Link to="/casino">Lobby</Link>
        {player ? (
          <>
            <Link to="/casino/wallet">Cartera</Link>
            <Link to="/casino/slots">Tragamonedas</Link>
            <Link to="/casino/blackjack">Blackjack</Link>
            <Link to="/casino/roulette">Ruleta</Link>
          </>
        ) : null}
      </nav>
      <div className="player-header-actions">
        {player ? (
          <>
            <div className="player-header-wallets">
              <Link
                className="player-balance player-balance-chips"
                to="/casino/wallet"
              >
                <img src={velvetChipIcon} alt="" aria-hidden="true" />
                <span className="player-balance-value">
                  <small>FICHAS</small>
                  <strong>{player.chip_balance.toLocaleString("es-ES")} VCH</strong>
                </span>
              </Link>
              <Link
                className="player-balance player-balance-usd"
                to="/casino/wallet"
              >
                <img src={playerWalletIcon} alt="" aria-hidden="true" />
                <span className="player-balance-value">
                  <small>CARTERA USD</small>
                  <strong>{formatUsd(player.wallet_balance)}</strong>
                </span>
              </Link>
            </div>
            <span className="player-greeting">Hola, {player.first_name}</span>
            <button type="button" className="player-button player-button-quiet" onClick={signOut}>Salir</button>
          </>
        ) : (
          <>
            <Link className="player-login-link" to="/casino/login">Iniciar sesión</Link>
            <Link className="player-button player-button-gold" to="/casino/register">Crear cuenta</Link>
          </>
        )}
      </div>
    </header>
  );
}

function DemoNotice() {
  return (
    <aside className="demo-notice">
      <span aria-hidden="true">ⓘ</span>
      Simulación local: USD y fichas ficticios, sin dinero real ni retiros. Los métodos de pago son simulados.
    </aside>
  );
}

function Lobby() {
  const { player } = usePlayer();
  return (
    <>
      <PlayerHeader />
      <main>
        <section className="player-hero">
          <div className="player-hero-copy">
            <p className="player-eyebrow">EL CLUB DE JUEGO DEMO</p>
            <h1>Tu próxima partida<br /><span>empieza aquí.</span></h1>
            <p>Explora juegos clásicos con una cartera simulada en USD y fichas Velvet Chips, sin dinero real.</p>
            {player ? (
              <Link className="player-button player-button-gold player-button-large" to="/casino/slots">Entrar al lobby <span aria-hidden="true">→</span></Link>
            ) : (
              <Link className="player-button player-button-gold player-button-large" to="/casino/register">Jugar gratis <span aria-hidden="true">→</span></Link>
            )}
          </div>
          <div className="player-hero-art" aria-hidden="true">
            <div className="hero-orbit hero-orbit-one" />
            <div className="hero-orbit hero-orbit-two" />
            <div className="hero-card hero-card-back">♠</div>
            <div className="hero-card hero-card-front"><span>A</span><strong>♠</strong><span>A</span></div>
            <div className="hero-chip">✦</div>
          </div>
        </section>
        <DemoNotice />
        <section className="player-games">
          <div className="player-section-heading">
            <div><p className="player-eyebrow">ELIGE TU MESA</p><h2>Juegos destacados</h2></div>
            <span className="player-live-label"><i /> Disponibles ahora</span>
          </div>
          <div className="player-game-grid">
            <GameCard
              icon="✦"
              title="Lucky Lanterns"
              description="Tres rodillos, un giro y premios por combinaciones triples."
              to={player ? "/casino/slots" : "/casino/login"}
              tag="TRAGAMONEDAS"
              art="slot"
            />
            <GameCard
              icon="♠"
              title="Blackjack clásico"
              description="Acércate a 21 y decide cuándo pedir o plantarte."
              to={player ? "/casino/blackjack" : "/casino/login"}
              tag="JUEGO DE CARTAS"
              art="cards"
            />
            <GameCard
              icon="◎"
              title="Ruleta europea"
              description="Elige número, color, paridad o docena en la rueda de un solo cero."
              to={player ? "/casino/roulette" : "/casino/login"}
              tag="RULETA · UN CERO"
              art="roulette"
            />
          </div>
        </section>
        <section className="player-how">
          <div><span>01</span><strong>Crea tu cuenta</strong><p>Solo para personas adultas. Sin verificación de correo en esta demo local.</p></div>
          <div><span>02</span><strong>Explora tu cartera</strong><p>Empiezas con $0 y 0 fichas; usa recargas y compras de fichas simuladas.</p></div>
          <div><span>03</span><strong>Disfruta los juegos</strong><p>Tragamonedas, blackjack y ruleta apuestan fichas VCH con resultados calculados en el servidor.</p></div>
        </section>
      </main>
      <footer className="player-footer">VELVETPLAY · DEMO LOCAL · SOLO PARA MAYORES DE 18 AÑOS</footer>
    </>
  );
}

function GameCard({
  icon,
  title,
  description,
  to,
  tag,
  art,
}: {
  icon: string;
  title: string;
  description: string;
  to: string;
  tag: string;
  art: "slot" | "cards" | "roulette";
}) {
  return (
    <Link to={to} className={`player-game-card player-game-art-${art}`}>
      <div className="game-card-art" aria-hidden="true"><span>{icon}</span></div>
      <div className="game-card-copy">
        <span className="player-game-tag">{tag}</span>
        <h3>{title}</h3>
        <p>{description}</p>
        <span className="player-game-cta">Jugar ahora <span aria-hidden="true">→</span></span>
      </div>
    </Link>
  );
}

function PlayerAuth({ mode }: { mode: "login" | "register" }) {
  const registering = mode === "register";
  const { setPlayer } = usePlayer();
  const navigate = useNavigate();
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setSubmitting(true);
    const form = new FormData(event.currentTarget);
    const payload = registering
      ? {
          username: form.get("username"),
          email: form.get("email"),
          password: form.get("password"),
          first_name: form.get("first_name"),
          last_name: form.get("last_name"),
          birth_date: form.get("birth_date"),
          country_code: form.get("country_code"),
        }
      : { username: form.get("username"), password: form.get("password") };
    try {
      const path = registering ? "/api/player/register" : "/api/player/login";
      const result = await apiRequest<{ player: Player }>(path, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setPlayer(result.player);
      navigate("/casino", { replace: true });
    } catch (submitError) {
      setError(messageFrom(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="player-auth-page">
      <PlayerHeader />
      <main className="player-auth-layout">
        <div className="player-auth-aside">
          <span className="player-auth-symbol">♠</span>
          <p className="player-eyebrow">VELVETPLAY DEMO</p>
          <h1>{registering ? "Una mesa te espera." : "Qué bueno verte."}</h1>
          <p>Juega por diversión con dinero y fichas simulados. Sin pagos reales, retiros ni premios canjeables.</p>
          <Link to="/casino">← Volver al lobby</Link>
        </div>
        <form className="player-auth-card" onSubmit={handleSubmit}>
          <p className="player-eyebrow">{registering ? "EMPIEZA A JUGAR" : "ACCESO DE JUGADOR"}</p>
          <h2>{registering ? "Crear cuenta" : "Iniciar sesión"}</h2>
          <p className="player-auth-helper">{registering ? "Completa tus datos para crear una cartera en cero. Todas las operaciones son simuladas." : "Entra a tu cuenta para continuar jugando."}</p>
          {registering ? (
            <>
              <div className="player-form-row">
                <PlayerField label="Nombre" name="first_name" autoComplete="given-name" required />
                <PlayerField label="Apellido" name="last_name" autoComplete="family-name" required />
              </div>
              <PlayerField label="Correo electrónico" name="email" type="email" autoComplete="email" required />
              <PlayerField label="Nombre de usuario" name="username" autoComplete="username" minLength={3} required />
              <PlayerField label="Contraseña (mínimo 12 caracteres)" name="password" type="password" autoComplete="new-password" minLength={12} required />
              <div className="player-form-row">
                <PlayerField label="Fecha de nacimiento" name="birth_date" type="date" required />
                <PlayerField label="País (código ISO)" name="country_code" placeholder="ES" maxLength={2} minLength={2} required />
              </div>
              <label className="player-age-consent"><input type="checkbox" required /> Confirmo que tengo 18 años o más.</label>
            </>
          ) : (
            <>
              <PlayerField label="Nombre de usuario" name="username" autoComplete="username" required />
              <PlayerField label="Contraseña" name="password" type="password" autoComplete="current-password" required />
            </>
          )}
          {error ? <div className="player-form-error" role="alert">{error}</div> : null}
          <button type="submit" className="player-button player-button-gold player-auth-submit" disabled={submitting}>
            {submitting ? "Un momento..." : registering ? "Crear cuenta" : "Entrar"}
          </button>
          <p className="player-auth-switch">
            {registering ? "¿Ya tienes una cuenta?" : "¿Primera vez por aquí?"}{" "}
            <Link to={registering ? "/casino/login" : "/casino/register"}>
              {registering ? "Inicia sesión" : "Regístrate"}
            </Link>
          </p>
          <DemoNotice />
        </form>
      </main>
    </div>
  );
}

function PlayerField({
  label,
  name,
  ...props
}: {
  label: string;
  name: string;
} & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="player-field">
      <span>{label}</span>
      <input name={name} {...props} />
    </label>
  );
}

function PlayerWalletPage() {
  const { player, setPlayer } = usePlayer();
  const [wallet, setWallet] = useState<PlayerWallet | null>(null);
  const [amount, setAmount] = useState("100");
  const [method, setMethod] = useState("card");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function refreshWallet() {
    try {
      const current = await apiRequest<PlayerWallet>("/api/player/wallet");
      setWallet(current);
      setPlayer(current.player);
    } catch (loadError) {
      setError(messageFrom(loadError));
    }
  }

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = async () => {
      try {
        const current = await apiRequest<PlayerWallet>("/api/player/wallet");
        if (active) {
          setWallet(current);
          setPlayer(current.player);
          setError("");
        }
      } catch (loadError) {
        if (active) setError(messageFrom(loadError));
      } finally {
        if (active) timer = window.setTimeout(load, 5000);
      }
    };
    void load();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [setPlayer]);

  async function topUp(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ player: Player }>("/api/player/wallet/top-up", {
        method: "POST",
        body: JSON.stringify({ amount, method }),
      });
      setPlayer(result.player);
      setNotice("Recarga simulada registrada en la cartera.");
      await refreshWallet();
    } catch (actionError) {
      setError(messageFrom(actionError));
    } finally {
      setBusy(false);
    }
  }

  async function buyChips(chips: number) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ player: Player; price: string | number }>(
        "/api/player/chips/purchase",
        { method: "POST", body: JSON.stringify({ chips }) },
      );
      setPlayer(result.player);
      setNotice(`Compra simulada confirmada por ${formatUsd(result.price)}.`);
      await refreshWallet();
    } catch (actionError) {
      setError(messageFrom(actionError));
    } finally {
      setBusy(false);
    }
  }

  async function buyVip(tier: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await apiRequest<{ player: Player; price: string | number }>(
        "/api/player/vip/purchase",
        { method: "POST", body: JSON.stringify({ tier }) },
      );
      setPlayer(result.player);
      setNotice(`Membresía ${tier} activada por 30 días.`);
      await refreshWallet();
    } catch (actionError) {
      setError(messageFrom(actionError));
    } finally {
      setBusy(false);
    }
  }

  const vipUntil = wallet?.vip_expires_at
    ? new Date(wallet.vip_expires_at).toLocaleDateString("es-ES")
    : null;

  return (
    <>
      <PlayerHeader />
      <main className="player-game-page player-wallet-page">
        <Link className="player-back-link" to="/casino">← Volver al lobby</Link>
        <div className="player-game-page-heading">
          <p className="player-eyebrow">CARTERA DE JUGADOR</p>
          <h1>Tu cartera</h1>
          <p>Saldo y compras de demostración, sin procesar dinero real ni datos de pago.</p>
        </div>
        <DemoNotice />
        <section className="wallet-balance-grid" aria-label="Saldos de cartera">
          <article className="wallet-balance-card">
            <span className="wallet-balance-label"><img src={playerWalletIcon} alt="" aria-hidden="true" />Saldo USD simulado</span>
            <strong>{formatUsd(wallet?.wallet_balance ?? player?.wallet_balance ?? 0)}</strong>
            <small>Límite: $500.000</small>
          </article>
          <article className="wallet-balance-card wallet-chip-card">
            <span className="wallet-balance-label"><img src={velvetChipIcon} alt="" aria-hidden="true" />Velvet Chips (VCH)</span>
            <strong>{(wallet?.chip_balance ?? player?.chip_balance ?? 0).toLocaleString("es-ES")}</strong>
            <small>Límite: 10.000.000 VCH</small>
          </article>
          <article className="wallet-balance-card">
            <span className="wallet-balance-label"><img src={vipCrownIcon} alt="" aria-hidden="true" />Nivel VIP</span>
            <strong>{(wallet?.vip_tier ?? player?.vip_tier ?? "standard").toUpperCase()}</strong>
            <small>{vipUntil ? `Vigente hasta ${vipUntil}` : "Sin membresía activa"}</small>
          </article>
        </section>

        <div className="wallet-action-grid">
          <section className="player-table wallet-panel">
            <h2>Recargar cartera</h2>
            <p className="player-game-rule">Recargas ficticias de $1 a $50.000 por operación. El método solo se registra como referencia.</p>
            <form className="wallet-form" onSubmit={topUp}>
              <PlayerField label="Importe USD" name="amount" type="number" min="1" max="50000" step="0.01" value={amount} onChange={(event) => setAmount(event.target.value)} required />
              <label className="player-field">
                <span>Método simulado</span>
                <select value={method} onChange={(event) => setMethod(event.target.value)}>
                  <option value="card">Tarjeta simulada</option>
                  <option value="e_wallet">Billetera electrónica</option>
                  <option value="bank_transfer">Transferencia bancaria</option>
                  <option value="crypto">Cripto simulada</option>
                </select>
              </label>
              <button className="player-button player-button-gold" type="submit" disabled={busy}>
                {busy ? "Procesando..." : "Simular recarga"}
              </button>
            </form>
          </section>

          <section className="player-table wallet-panel">
            <h2>Comprar Velvet Chips</h2>
            <p className="player-game-rule">Conversión base: $1 = 10 VCH. El descuento VIP se aplica al precio y solo los VCH se apuestan.</p>
            <div className="wallet-package-list">
              {wallet?.packages.map((pack) => {
                const discount = Number(wallet.vip_discount);
                const price = Number(pack.base_price) * (1 - discount);
                return (
                  <button className="wallet-package" type="button" key={pack.chips} onClick={() => void buyChips(pack.chips)} disabled={busy}>
                    <span className="wallet-package-heading">
                      <img src={velvetChipIcon} alt="" aria-hidden="true" />
                      <strong>{pack.chips.toLocaleString("es-ES")} VCH</strong>
                    </span>
                    <span className="wallet-package-price">{formatUsd(price)}</span>
                    {discount > 0 ? <small>Precio base {formatUsd(pack.base_price)} · descuento VIP {Math.round(discount * 100)}%</small> : null}
                  </button>
                );
              })}
            </div>
          </section>
        </div>

        <section className="player-table wallet-panel">
          <h2>Membresías VIP · 30 días</h2>
          <p className="player-game-rule">La membresía se paga con saldo USD. Renovar el mismo nivel extiende su vigencia; cambiarlo lo reemplaza inmediatamente. Sin renovación automática.</p>
          <div className="wallet-vip-list">
            {wallet?.vip_plans.map((plan) => (
              <article className={`wallet-vip-card ${plan.tier === wallet.vip_tier ? "wallet-vip-current" : ""}`} key={plan.tier}>
                <span className="wallet-vip-tier"><img src={vipCrownIcon} alt="" aria-hidden="true" />{plan.tier.toUpperCase()}</span>
                <strong>{formatUsd(plan.price)}<small> / 30 días</small></strong>
                <b>{Math.round(Number(plan.discount) * 100)}% de descuento en fichas</b>
                <p>Beneficios adicionales informativos para esta demo.</p>
                <button className="player-button player-button-quiet" type="button" onClick={() => void buyVip(plan.tier)} disabled={busy}>
                  {plan.tier === wallet.vip_tier ? "Renovar nivel" : "Elegir nivel"}
                </button>
              </article>
            ))}
          </div>
        </section>

        {notice ? <p className="wallet-success" role="status">{notice}</p> : null}
        {error ? <p className="player-form-error" role="alert">{error}</p> : null}

        <section className="player-table wallet-panel">
          <h2>Actividad reciente</h2>
          <div className="wallet-activity-columns">
            <div>
              <h3>Movimientos USD</h3>
              {wallet?.transactions.length ? (
                <ul className="wallet-activity-list">
                  {wallet.transactions.map((transaction) => (
                    <li key={transaction.id}>
                      <span>{transaction.type.replaceAll("_", " ")} · {transaction.origin === "player_casino_demo" ? "simulado" : "demo"}</span>
                      <strong>{formatUsd(transaction.amount)}</strong>
                    </li>
                  ))}
                </ul>
              ) : <p className="wallet-empty">Aún no hay transacciones USD.</p>}
            </div>
            <div>
              <h3>Ledger VCH</h3>
              {wallet?.chip_entries.length ? (
                <ul className="wallet-activity-list">
                  {wallet.chip_entries.map((entry) => (
                    <li key={entry.id}>
                      <span>{entry.reason.replaceAll("_", " ")}</span>
                      <strong>{entry.delta > 0 ? "+" : ""}{entry.delta.toLocaleString("es-ES")} VCH</strong>
                    </li>
                  ))}
                </ul>
              ) : <p className="wallet-empty">Aún no hay movimientos de fichas.</p>}
            </div>
          </div>
        </section>
      </main>
    </>
  );
}

function GameShell({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: ReactNode;
}) {
  return (
    <>
      <PlayerHeader />
      <main className="player-game-page">
        <Link className="player-back-link" to="/casino">← Volver al lobby</Link>
        <div className="player-game-page-heading"><p className="player-eyebrow">MODO DEMO</p><h1>{title}</h1><p>{subtitle}</p></div>
        <DemoNotice />
        {children}
      </main>
    </>
  );
}

type GameResultTone = "win" | "draw" | "loss";

function GameResultBanner({
  tone,
  title,
  detail,
  reward,
  rewardLabel,
}: {
  tone: GameResultTone;
  title: string;
  detail: string;
  reward?: string;
  rewardLabel?: string;
}) {
  const symbol = tone === "win" ? "✦" : tone === "draw" ? "↔" : "×";
  const label = tone === "win" ? "BUENA JUGADA" : tone === "draw" ? "RONDA EMPATADA" : "SIGUIENTE RONDA";

  return (
    <div className={`game-result-banner game-result-${tone}`} role="status" aria-live="polite">
      <span className="game-result-emblem" aria-hidden="true">{symbol}</span>
      <div className="game-result-copy">
        <span className="game-result-kicker">{label}</span>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
      {reward ? (
        <div className="game-result-reward">
          <small>{rewardLabel ?? "PREMIO"}</small>
          <strong>{reward}</strong>
        </div>
      ) : null}
    </div>
  );
}

function SlotsGame() {
  const { player, setPlayer } = usePlayer();
  const [stake, setStake] = useState(10);
  const [round, setRound] = useState<GameRound | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function spin() {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<{ round: GameRound; balance: number }>("/api/player/games/slots/spin", {
        method: "POST",
        body: JSON.stringify({ stake }),
      });
      setRound(result.round);
      if (player) setPlayer({ ...player, balance: result.balance, chip_balance: result.balance });
    } catch (spinError) {
      setError(messageFrom(spinError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <GameShell title="Lucky Lanterns" subtitle="Tres símbolos iguales en línea para ganar.">
      <section className="player-table">
        <p className="player-game-rule">Premios triples: 🍒 2× · 🍋 3× · 🔔 5× · ⭐ 10×. Las apuestas y premios se liquidan en Velvet Chips (VCH).</p>
        <div className={`slot-machine ${busy ? "slot-machine-spinning" : ""}`}>
          <div className="slot-reels" aria-live="polite">
            {(round?.symbols ?? ["✦", "✦", "✦"]).map((symbol, index) => <span className="slot-reel" key={`${index}-${symbol}`}>{symbol}</span>)}
          </div>
          <div className="slot-lever" aria-hidden="true">
            <span className="slot-lever-arm" />
            <span className="slot-lever-knob" />
            <span className="slot-lever-base" />
          </div>
          {round?.outcome ? (
            <GameResultBanner
              tone={round.outcome.result === "win" ? "win" : "loss"}
              title={round.outcome.result === "win" ? "¡Combinación ganadora!" : "Esta vez no hubo premio"}
              detail={round.outcome.result === "win" ? "Tus símbolos iguales activaron el premio." : "Prueba otra apuesta cuando quieras."}
              reward={round.outcome.result === "win" ? `+${round.outcome.payout ?? 0} VCH` : undefined}
            />
          ) : <p className="game-result">{busy ? "Girando los rodillos..." : "¿Listo para probar suerte?"}</p>}
        </div>
        <div className="game-controls">
          <label className="player-field player-stake-field">
            <span><img className="player-field-chip" src={velvetChipIcon} alt="" aria-hidden="true" />Apuesta</span>
            <select value={stake} onChange={(event) => setStake(Number(event.target.value))}>
              {[10, 20, 50, 100].map((amount) => <option key={amount} value={amount}>{amount} VCH</option>)}
            </select>
          </label>
          <button className="player-button player-button-gold" type="button" onClick={spin} disabled={busy || (player?.balance ?? 0) < stake}>{busy ? "Girando..." : "Girar rodillos"}</button>
        </div>
        {error ? <p className="player-form-error" role="alert">{error}</p> : null}
      </section>
    </GameShell>
  );
}

function RouletteGame() {
  const { player, setPlayer } = usePlayer();
  const [kind, setKind] = useState<RouletteBetKind>("color");
  const [value, setValue] = useState("red");
  const [amount, setAmount] = useState(10);
  const [bets, setBets] = useState<RouletteWager[]>([]);
  const [round, setRound] = useState<GameRound | null>(null);
  const [wheelRotation, setWheelRotation] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const totalStake = bets.reduce((total, bet) => total + bet.amount, 0);
  const options = kind === "number"
    ? Array.from({ length: 37 }, (_, number) => ({ value: String(number), label: String(number) }))
    : kind === "dozen"
      ? [
          { value: "1", label: "1.ª docena (1–12)" },
          { value: "2", label: "2.ª docena (13–24)" },
          { value: "3", label: "3.ª docena (25–36)" },
        ]
      : kind === "color"
        ? [{ value: "red", label: "Rojo" }, { value: "black", label: "Negro" }]
        : [{ value: "odd", label: "Impar" }, { value: "even", label: "Par" }];

  function changeKind(nextKind: RouletteBetKind) {
    setKind(nextKind);
    setValue(ROULETTE_DEFAULT_VALUES[nextKind]);
  }

  function addBet() {
    const selectedValue = kind === "number" || kind === "dozen" ? Number(value) : value;
    setBets((current) => [...current, { kind, value: selectedValue, amount }]);
    setRound(null);
    setError("");
  }

  async function spin() {
    setBusy(true);
    setError("");
    setRound(null);
    try {
      const result = await apiRequest<{ round: GameRound; balance: number }>(
        "/api/player/games/roulette/spin",
        { method: "POST", body: JSON.stringify({ bets }) },
      );
      setRound(result.round);
      if (player) setPlayer({ ...player, balance: result.balance, chip_balance: result.balance });
      const wheelIndex = ROULETTE_WHEEL_ORDER.indexOf(result.round.winning_number ?? 0);
      setWheelRotation((Math.floor(wheelRotation / 360) + 6) * 360 - (wheelIndex + 0.5) * (360 / 37));
      const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      await new Promise((resolve) => window.setTimeout(resolve, reducedMotion ? 0 : 4300));
    } catch (spinError) {
      setError(messageFrom(spinError));
    } finally {
      setBusy(false);
    }
  }

  const wheelBackground = `conic-gradient(${ROULETTE_WHEEL_ORDER.map((number, index) => {
    const color = number === 0 ? "#268c58" : [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36].includes(number) ? "#b53c39" : "#18221d";
    const start = index * (360 / 37);
    const end = (index + 1) * (360 / 37);
    return `${color} ${start}deg ${end}deg`;
  }).join(", ")})`;

  return (
    <GameShell title="Ruleta europea" subtitle="Una rueda, un cero y varias formas de apostar fichas Velvet Chips.">
      <section className="player-table roulette-table">
        <p className="player-game-rule">Apuesta a un número (35:1), color o paridad (1:1), o docena (2:1). Los premios incluyen la apuesta original y se acreditan en VCH. El cero es verde y hace perder las apuestas que no cubren el 0.</p>
        <div className="roulette-game-layout">
          <div className="roulette-wheel-stage">
            <span className="roulette-pointer" aria-hidden="true" />
            <div className="roulette-wheel" style={{ transform: `rotate(${wheelRotation}deg)`, background: wheelBackground }} aria-hidden="true">
              <div className="roulette-wheel-labels">
                {ROULETTE_WHEEL_ORDER.map((number, index) => (
                  <span
                    className={number === 0 ? "roulette-number roulette-number-zero" : "roulette-number"}
                    key={number}
                    style={{
                      transform: `rotate(${(index + 0.5) * (360 / 37)}deg) translateY(-36cqw) rotate(${-(index + 0.5) * (360 / 37)}deg)`,
                    }}
                  >
                    {number}
                  </span>
                ))}
              </div>
              <div className="roulette-wheel-center"><span>VELVET</span><strong>✦</strong><span>PLAY</span></div>
            </div>
          </div>
          <aside className="roulette-bets-panel" aria-label="Panel de apuestas">
            <div className="roulette-panel-heading">
              <span className="player-game-tag">TU APUESTA</span>
              <strong><img src={velvetChipIcon} alt="" aria-hidden="true" />{totalStake} VCH</strong>
            </div>
            <div className="roulette-builder-heading">
              <span className="roulette-builder-icon" aria-hidden="true">✦</span>
              <div><strong>Configura tu apuesta</strong><span>Elige una casilla, color o paridad.</span></div>
            </div>
            <div className="roulette-bet-form">
              <label className="player-field">
                <span>Tipo</span>
                <select value={kind} onChange={(event) => changeKind(event.target.value as RouletteBetKind)}>
                  <option value="number">Número</option>
                  <option value="color">Color</option>
                  <option value="parity">Paridad</option>
                  <option value="dozen">Docena</option>
                </select>
              </label>
              <label className="player-field">
                <span>Selección</span>
                <select value={value} onChange={(event) => setValue(event.target.value)}>
                  {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label className="player-field">
                <span>Importe</span>
                <select value={amount} onChange={(event) => setAmount(Number(event.target.value))}>
                  {[10, 20, 30, 50, 100].map((chipAmount) => <option key={chipAmount} value={chipAmount}>{chipAmount} VCH</option>)}
                </select>
              </label>
              <button className="player-button player-button-quiet roulette-add-bet-button" type="button" onClick={addBet} disabled={totalStake + amount > 100}>
                <span aria-hidden="true">＋</span>Añadir a mis apuestas
              </button>
            </div>
            <div className="roulette-bet-list-heading"><strong>Tus apuestas</strong><span>Máximo 100 VCH por giro</span></div>
            <ul className="roulette-bet-list" aria-label="Apuestas añadidas">
              {bets.map((bet, index) => (
                <li key={`${bet.kind}-${bet.value}-${index}`}>
                  <span>{rouletteBetLabel(bet.kind, bet.value)}</span>
                  <strong><img src={velvetChipIcon} alt="" aria-hidden="true" />{bet.amount}</strong>
                  <button type="button" aria-label={`Quitar ${rouletteBetLabel(bet.kind, bet.value)}`} onClick={() => {
                    setBets((current) => current.filter((_, betIndex) => betIndex !== index));
                    setRound(null);
                  }}>×</button>
                </li>
              ))}
              {bets.length === 0 ? <li className="roulette-empty-bets">Añade una o varias apuestas. Total por giro: 10–100.</li> : null}
            </ul>
            <button className="player-button player-button-gold roulette-spin-button" type="button" onClick={spin} disabled={busy || totalStake < 10 || totalStake > 100 || (player?.balance ?? 0) < totalStake}>
              {busy ? "Girando la ruleta..." : "Girar"}
            </button>
          </aside>
        </div>
        {round?.outcome && !busy ? (
          <div className="roulette-outcome">
            <GameResultBanner
              tone={round.outcome.result === "win" ? "win" : "loss"}
              title={`${round.outcome.result === "win" ? "¡Premio!" : "Salió"} ${round.winning_number} · ${round.color === "red" ? "rojo" : round.color === "black" ? "negro" : "verde"}`}
              detail={round.outcome.result === "win" ? "Una de tus apuestas acertó. El premio ya está en tu saldo." : "Esta vez no hubo apuestas ganadoras. La próxima ronda te espera."}
              reward={round.outcome.result === "win" ? `+${round.outcome.payout ?? 0} VCH` : undefined}
            />
            <ul>{round.outcome.bets?.map((bet, index) => <li key={`${bet.kind}-${bet.value}-${index}`}>{rouletteBetLabel(bet.kind, bet.value)}: {bet.won ? `ganó (${bet.payout} VCH)` : "sin premio"}</li>)}</ul>
          </div>
        ) : <p className="roulette-result-placeholder" aria-live="polite">{busy ? "La bola está girando..." : "El resultado aparecerá aquí después del giro."}</p>}
        {error ? <p className="player-form-error" role="alert">{error}</p> : null}
      </section>
    </GameShell>
  );
}

function rouletteBetLabel(kind: RouletteBetKind, value: string | number): string {
  if (kind === "number") return `Número ${value}`;
  if (kind === "dozen") return `${value}.ª docena`;
  if (kind === "color") return value === "red" ? "Rojo" : "Negro";
  return value === "odd" ? "Impar" : "Par";
}

function BlackjackGame() {
  const { player, setPlayer } = usePlayer();
  const [stake, setStake] = useState(10);
  const [round, setRound] = useState<GameRound | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function reloadActiveRound() {
    try {
      const result = await apiRequest<{ round: GameRound | null }>("/api/player/games/blackjack/active");
      setRound(result.round);
    } catch (loadError) {
      setError(messageFrom(loadError));
    }
  }

  useEffect(() => {
    void reloadActiveRound();
  }, []);

  async function perform(path: string, body?: object) {
    setBusy(true);
    setError("");
    try {
      const result = await apiRequest<{ round: GameRound; balance: number }>(path, {
        method: "POST",
        ...(body ? { body: JSON.stringify(body) } : {}),
      });
      setRound(result.round);
      if (player) setPlayer({ ...player, balance: result.balance, chip_balance: result.balance });
    } catch (actionError) {
      setError(messageFrom(actionError));
    } finally {
      setBusy(false);
    }
  }

  const active = round?.status === "in_progress";
  const currentHand = round?.hands?.[round.current_hand ?? 0];
  const handResults = round?.outcome?.hands ?? [];
  const blackjackTone: GameResultTone = handResults.some((hand) => hand.result === "win" || hand.result === "blackjack")
    ? "win"
    : handResults.length > 0 && handResults.every((hand) => hand.result === "push")
      ? "draw"
      : "loss";
  const roundPayout = handResults.reduce((total, hand) => total + (hand.payout ?? 0), 0);

  return (
    <GameShell title="Blackjack clásico" subtitle="Acércate a 21 sin pasarte. El croupier debe superar la mano para ganar.">
      <section className="player-table blackjack-table">
        <p className="player-game-rule">Blackjack natural paga 3:2. Se permite una división por ronda con cartas iniciales del mismo valor; los ases divididos reciben una carta y se plantan automáticamente. Empates devuelven la apuesta en VCH.</p>
        {round ? (
          <div className="blackjack-board" aria-live="polite">
            <div className="blackjack-hand blackjack-dealer"><span className="blackjack-label">CROUPIER</span><div className="blackjack-cards">{round.dealer_hand?.map((card, index) => <PlayingCard card={card} key={`${card}-${index}`} />)}</div>{round.outcome ? <span className="blackjack-score">Puntaje: {round.outcome.dealer_score}</span> : null}</div>
            <div className="blackjack-divider"><span>♣</span></div>
            {round.hands?.map((hand, index) => {
              const handResult = round.outcome?.hands?.[index];
              const resultTone: GameResultTone = handResult?.result === "win" || handResult?.result === "blackjack"
                ? "win"
                : handResult?.result === "push"
                  ? "draw"
                  : "loss";
              const resultLabel = handResult?.result === "blackjack" ? "Blackjack" : handResult?.result === "push" ? "Empate" : handResult?.result === "bust" ? "Te pasaste" : handResult?.result === "lose" ? "Derrota" : "Victoria";
              return (
                <div className={`blackjack-hand ${index === round.current_hand && active ? "blackjack-hand-current" : ""}`} key={index}>
                  <span className="blackjack-label">TU MANO {round.hands && round.hands.length > 1 ? index + 1 : ""}{hand.status !== "playing" && active ? ` · ${hand.status === "bust" ? "PASADA" : "PLANTADA"}` : ""}</span>
                  <div className="blackjack-cards">{hand.cards.map((card, cardIndex) => <PlayingCard card={card} key={`${card}-${cardIndex}`} />)}</div>
                  <span className="blackjack-score">Puntaje: {hand.cards.length ? handScore(hand.cards) : 0} · Apuesta: {hand.stake}</span>
                  {handResult ? <span className={`blackjack-result blackjack-result-${resultTone}`}>{resultLabel} · {handResult.payout ? `+${handResult.payout}` : "0"} VCH</span> : null}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="blackjack-welcome"><span aria-hidden="true">♠</span><h2>La mesa está lista</h2><p>Recibe dos cartas y juega tu mano contra el croupier.</p></div>
        )}
        {round?.outcome ? (
          <GameResultBanner
            tone={blackjackTone}
            title={blackjackTone === "win" ? (handResults.some((hand) => hand.result === "blackjack") ? "¡Blackjack!" : "¡Mano ganadora!") : blackjackTone === "draw" ? "Empate: tu apuesta vuelve a ti" : "Ronda finalizada"}
            detail={blackjackTone === "win" ? "Superaste al croupier y el premio se acreditó en fichas." : blackjackTone === "draw" ? "Ni tú ni el croupier superaron al otro; no perdiste fichas." : "El croupier ganó esta mano. Puedes intentarlo de nuevo."}
            reward={blackjackTone !== "loss" ? `+${roundPayout} VCH` : undefined}
            rewardLabel={blackjackTone === "draw" ? "DEVOLUCIÓN" : "PAGO TOTAL"}
          />
        ) : null}
        <div className="game-controls">
          {!round || !active ? (
            <>
              <label className="player-field player-stake-field">
                <span><img className="player-field-chip" src={velvetChipIcon} alt="" aria-hidden="true" />Apuesta</span>
                <select value={stake} onChange={(event) => setStake(Number(event.target.value))}>
                  {[10, 20, 50, 100].map((amount) => <option key={amount} value={amount}>{amount} VCH</option>)}
                </select>
              </label>
              <button className="player-button player-button-gold" type="button" onClick={() => perform("/api/player/games/blackjack/start", { stake })} disabled={busy || (player?.balance ?? 0) < stake}>{busy ? "Repartiendo..." : "Repartir"}</button>
            </>
          ) : (
            <>
              <button className="player-button player-button-quiet" type="button" onClick={() => perform(`/api/player/games/blackjack/${round.id}/action`, { action: "hit" })} disabled={busy}>Pedir carta</button>
              <button className="player-button player-button-gold" type="button" onClick={() => perform(`/api/player/games/blackjack/${round.id}/action`, { action: "stand" })} disabled={busy}>Plantarse</button>
              {round.can_split ? <button className="player-button player-button-quiet" type="button" onClick={() => perform(`/api/player/games/blackjack/${round.id}/action`, { action: "split" })} disabled={busy || (player?.balance ?? 0) < (currentHand?.stake ?? 0)}>Dividir</button> : null}
            </>
          )}
        </div>
        {error ? <p className="player-form-error" role="alert">{error}</p> : null}
      </section>
    </GameShell>
  );
}

function PlayingCard({ card }: { card: string }) {
  const rank = card.slice(0, -1);
  const suitCode = card.slice(-1);
  const suitSymbols: Record<string, string> = { H: "♥", D: "♦", C: "♣", S: "♠" };
  const suitNames: Record<string, string> = { H: "corazones", D: "diamantes", C: "tréboles", S: "picas" };
  const rankNames: Record<string, string> = { A: "As", K: "Rey", Q: "Reina", J: "Jota" };
  const suit = suitSymbols[suitCode] ?? suitCode;
  const suitName = suitNames[suitCode] ?? "desconocido";
  const rankName = rankNames[rank] ?? rank;
  const isRed = suitCode === "H" || suitCode === "D";

  if (card === "🂠") {
    return <span className="playing-card playing-card-back" role="img" aria-label="Carta oculta"><span aria-hidden="true">✦</span></span>;
  }

  return (
    <span className={`playing-card ${isRed ? "playing-card-red" : ""}`} role="img" aria-label={`${rankName} de ${suitName}`}>
      <span className="playing-card-corner" aria-hidden="true"><strong>{rank}</strong><span>{suit}</span></span>
      <span className="playing-card-suit" aria-hidden="true">{suit}</span>
      <span className="playing-card-corner playing-card-corner-bottom" aria-hidden="true"><strong>{rank}</strong><span>{suit}</span></span>
    </span>
  );
}

function handScore(cards: string[]): number {
  let score = cards.reduce((total, card) => {
    const rank = card.slice(0, -1);
    return total + (rank === "A" ? 11 : ["K", "Q", "J"].includes(rank) ? 10 : Number(rank));
  }, 0);
  let aces = cards.filter((card) => card.startsWith("A")).length;
  while (score > 21 && aces > 0) {
    score -= 10;
    aces -= 1;
  }
  return score;
}
