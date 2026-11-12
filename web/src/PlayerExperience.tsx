import { createContext, useContext, useEffect, useState } from "react";
import type { FormEvent, InputHTMLAttributes, ReactNode } from "react";
import {
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from "react-router-dom";
import { ApiError, apiRequest } from "./api";

type Player = {
  id: number;
  username: string;
  first_name: string;
  balance: number;
};

type PlayerContextValue = {
  player: Player | null;
  setPlayer: (player: Player | null) => void;
};

type GameRound = {
  id: string;
  game: "slots" | "blackjack";
  status: "in_progress" | "completed";
  stake: number;
  symbols?: string[];
  dealer_hand?: string[];
  hands?: { cards: string[]; status: string; stake: number }[];
  current_hand?: number;
  can_split?: boolean;
  outcome?: {
    result?: string;
    payout?: number;
    multiplier?: number;
    dealer_score?: number;
    hands?: { result: string; score: number; stake: number; payout: number }[];
  };
};

const PlayerContext = createContext<PlayerContextValue | null>(null);

function usePlayer() {
  const context = useContext(PlayerContext);
  if (!context) throw new Error("Player experience context is unavailable");
  return context;
}

function messageFrom(error: unknown): string {
  return error instanceof Error ? error.message : "Ocurrió un error inesperado.";
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
          <Route path="/slots" element={<PlayerGate><SlotsGame /></PlayerGate>} />
          <Route path="/blackjack" element={<PlayerGate><BlackjackGame /></PlayerGate>} />
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
            <Link to="/casino/slots">Tragamonedas</Link>
            <Link to="/casino/blackjack">Blackjack</Link>
          </>
        ) : null}
      </nav>
      <div className="player-header-actions">
        {player ? (
          <>
            <span className="player-balance"><span aria-hidden="true">✦</span> {player.balance.toLocaleString("es-ES")}</span>
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
      Demo de entretenimiento: créditos ficticios sin valor monetario, compra ni retiro.
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
            <p>Explora juegos clásicos en un espacio seguro, con créditos ficticios y sin dinero real.</p>
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
          </div>
        </section>
        <section className="player-how">
          <div><span>01</span><strong>Crea tu cuenta</strong><p>Solo para personas adultas. Sin verificación de correo en esta demo local.</p></div>
          <div><span>02</span><strong>Recibe 1.000 créditos</strong><p>Tu saldo es ficticio, independiente de cualquier billetera del dashboard.</p></div>
          <div><span>03</span><strong>Disfruta los juegos</strong><p>Tragamonedas y blackjack, con resultados calculados en el servidor.</p></div>
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
  art: "slot" | "cards";
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
          <p>Juega por diversión con créditos ficticios. Sin pagos, retiros ni premios canjeables.</p>
          <Link to="/casino">← Volver al lobby</Link>
        </div>
        <form className="player-auth-card" onSubmit={handleSubmit}>
          <p className="player-eyebrow">{registering ? "EMPIEZA A JUGAR" : "ACCESO DE JUGADOR"}</p>
          <h2>{registering ? "Crear cuenta" : "Iniciar sesión"}</h2>
          <p className="player-auth-helper">{registering ? "Completa tus datos para recibir 1.000 créditos demo." : "Entra a tu cuenta para continuar jugando."}</p>
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
      if (player) setPlayer({ ...player, balance: result.balance });
    } catch (spinError) {
      setError(messageFrom(spinError));
    } finally {
      setBusy(false);
    }
  }

  return (
    <GameShell title="Lucky Lanterns" subtitle="Tres símbolos iguales en línea para ganar.">
      <section className="player-table">
        <p className="player-game-rule">Premios triples: 🍒 2× · 🍋 3× · 🔔 5× · ⭐ 10×. Los premios se acreditan hasta el máximo de 1.000 créditos.</p>
        <div className="slot-machine">
          <div className="slot-reels" aria-live="polite">
            {(round?.symbols ?? ["✦", "✦", "✦"]).map((symbol, index) => <span className="slot-reel" key={`${index}-${symbol}`}>{symbol}</span>)}
          </div>
          {round?.outcome ? (
            <p className={`game-result ${round.outcome.result === "win" ? "game-result-win" : ""}`}>
              {round.outcome.result === "win" ? `¡Premio! +${round.outcome.payout} créditos` : "Esta vez no hubo combinación ganadora."}
            </p>
          ) : <p className="game-result">¿Listo para girar?</p>}
        </div>
        <div className="game-controls">
          <label className="player-field player-stake-field"><span>Apuesta</span><select value={stake} onChange={(event) => setStake(Number(event.target.value))}>{[10, 20, 50, 100].map((amount) => <option key={amount} value={amount}>{amount} créditos</option>)}</select></label>
          <button className="player-button player-button-gold" type="button" onClick={spin} disabled={busy || (player?.balance ?? 0) < stake}>{busy ? "Girando..." : "Girar rodillos"}</button>
        </div>
        {error ? <p className="player-form-error" role="alert">{error}</p> : null}
      </section>
    </GameShell>
  );
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
      if (player) setPlayer({ ...player, balance: result.balance });
    } catch (actionError) {
      setError(messageFrom(actionError));
    } finally {
      setBusy(false);
    }
  }

  const active = round?.status === "in_progress";
  const currentHand = round?.hands?.[round.current_hand ?? 0];

  return (
    <GameShell title="Blackjack clásico" subtitle="Acércate a 21 sin pasarte. El croupier debe superar la mano para ganar.">
      <section className="player-table blackjack-table">
        <p className="player-game-rule">Blackjack natural paga 3:2. Se permite una división por ronda con cartas iniciales del mismo valor; los ases divididos reciben una carta y se plantan automáticamente. Empates devuelven la apuesta.</p>
        {round ? (
          <div className="blackjack-board" aria-live="polite">
            <div className="blackjack-hand blackjack-dealer"><span className="blackjack-label">CROUPIER</span><div className="blackjack-cards">{round.dealer_hand?.map((card, index) => <span className="playing-card" key={`${card}-${index}`}>{card}</span>)}</div>{round.outcome ? <span className="blackjack-score">Puntaje: {round.outcome.dealer_score}</span> : null}</div>
            <div className="blackjack-divider"><span>♣</span></div>
            {round.hands?.map((hand, index) => {
              const handResult = round.outcome?.hands?.[index];
              return (
                <div className={`blackjack-hand ${index === round.current_hand && active ? "blackjack-hand-current" : ""}`} key={index}>
                  <span className="blackjack-label">TU MANO {round.hands && round.hands.length > 1 ? index + 1 : ""}{hand.status !== "playing" && active ? ` · ${hand.status === "bust" ? "PASADA" : "PLANTADA"}` : ""}</span>
                  <div className="blackjack-cards">{hand.cards.map((card, cardIndex) => <span className="playing-card" key={`${card}-${cardIndex}`}>{card}</span>)}</div>
                  <span className="blackjack-score">Puntaje: {hand.cards.length ? handScore(hand.cards) : 0} · Apuesta: {hand.stake}</span>
                  {handResult ? <span className={`blackjack-result ${handResult.result === "win" || handResult.result === "blackjack" ? "game-result-win" : ""}`}>{handResult.result} · {handResult.payout ? `+${handResult.payout}` : "0"} créditos</span> : null}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="blackjack-welcome"><span aria-hidden="true">♠</span><h2>La mesa está lista</h2><p>Recibe dos cartas y juega tu mano contra el croupier.</p></div>
        )}
        {round?.outcome ? <p className="game-result game-result-win">{round.outcome.hands?.some((hand) => hand.result === "win" || hand.result === "blackjack") ? "Ronda finalizada: ¡bien jugado!" : "Ronda finalizada."}</p> : null}
        <div className="game-controls">
          {!round || !active ? (
            <>
              <label className="player-field player-stake-field"><span>Apuesta</span><select value={stake} onChange={(event) => setStake(Number(event.target.value))}>{[10, 20, 50, 100].map((amount) => <option key={amount} value={amount}>{amount} créditos</option>)}</select></label>
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
