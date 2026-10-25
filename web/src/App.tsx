import {
  createContext,
  Fragment,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { FormEvent } from "react";
import {
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { ApiError, apiDownload, apiRequest } from "./api";
import {
  getInitialLocale,
  getInitialTheme,
  systemTheme,
  translate,
} from "./i18n";
import type { Locale, ThemeMode } from "./i18n";
import type {
  Admin,
  DashboardDailyMetrics,
  DashboardDistributionItem,
  DashboardHeatmapCell,
  DashboardMetrics,
  DashboardMonthlyGGR,
  PageResult,
} from "./api";

type AuthContextValue = {
  admin: Admin | null;
  signOut: () => Promise<void>;
  setAdmin: (admin: Admin | null) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

type PreferencesContextValue = {
  locale: Locale;
  t: (message: string) => string;
  theme: ThemeMode;
  resolvedTheme: "light" | "dark";
  setLocale: (locale: Locale) => void;
  toggleTheme: () => void;
};

const PreferencesContext = createContext<PreferencesContextValue | null>(null);

function usePreferences() {
  const value = useContext(PreferencesContext);
  if (!value) throw new Error("UI preferences context is unavailable");
  return value;
}

function useT() {
  return usePreferences().t;
}

function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("Authentication context is unavailable");
  return value;
}

type PageConfig = {
  title: string;
  description: string;
  endpoint: string;
  columns: { key: string; label: string; kind?: "money" | "date" | "status" }[];
  searchable?: boolean;
  filters?: FilterConfig[];
  detailEndpoint?: (id: string) => string;
  exportable?: boolean;
  resource: string;
};

type FilterConfig = {
  key: string;
  label: string;
  type: "select" | "text" | "number" | "date";
  options?: { value: string; label: string }[];
};

const pages: Record<string, PageConfig> = {
  players: {
    title: "Players",
    description: "Player profiles, verification and wallet balances.",
    endpoint: "/api/players",
    resource: "players",
    exportable: true,
    searchable: true,
    detailEndpoint: (id) => `/api/players/${id}`,
    filters: [
      { key: "status", label: "Player status", type: "select", options: ["active", "suspended", "self_excluded", "closed"].map((value) => ({ value, label: value.replaceAll("_", " ") })) },
      { key: "kyc_status", label: "KYC status", type: "select", options: ["pending", "verified", "rejected"].map((value) => ({ value, label: value })) },
      { key: "vip_tier", label: "VIP tier", type: "select", options: ["standard", "silver", "gold", "platinum", "diamond"].map((value) => ({ value, label: value })) },
      { key: "country_code", label: "Country code", type: "text" },
      { key: "registered_after", label: "Registered from", type: "date" },
      { key: "registered_before", label: "Registered to", type: "date" },
    ],
    columns: [
      { key: "username", label: "Player" },
      { key: "email", label: "Email" },
      { key: "country_code", label: "Country" },
      { key: "status", label: "Status", kind: "status" },
      { key: "kyc_status", label: "KYC", kind: "status" },
      { key: "vip_tier", label: "VIP tier", kind: "status" },
      { key: "wallet_balance", label: "Wallet", kind: "money" },
      { key: "registered_at", label: "Registered", kind: "date" },
    ],
  },
  games: {
    title: "Games",
    description: "Browse the game catalogue and current availability.",
    endpoint: "/api/games",
    resource: "games",
    exportable: true,
    searchable: true,
    detailEndpoint: (id) => `/api/games/${id}/detail`,
    filters: [
      { key: "category_code", label: "Category code", type: "text" },
      { key: "provider", label: "Provider", type: "text" },
      { key: "is_active", label: "Availability", type: "select", options: [{ value: "true", label: "Active" }, { value: "false", label: "Inactive" }] },
    ],
    columns: [
      { key: "name", label: "Game" },
      { key: "category_name", label: "Category" },
      { key: "provider", label: "Provider" },
      { key: "theoretical_rtp", label: "RTP" },
      { key: "volatility", label: "Volatility", kind: "status" },
      { key: "min_bet", label: "Min bet", kind: "money" },
      { key: "max_bet", label: "Max bet", kind: "money" },
      { key: "is_active", label: "Availability", kind: "status" },
    ],
  },
  transactions: {
    title: "Transactions",
    description: "Deposits, withdrawals and account adjustments.",
    endpoint: "/api/transactions",
    resource: "transactions",
    exportable: true,
    detailEndpoint: (id) => `/api/transactions/${id}/detail`,
    filters: [
      { key: "player_id", label: "Player ID", type: "number" },
      { key: "type", label: "Type", type: "select", options: ["deposit", "withdrawal", "bonus_credit", "adjustment"].map((value) => ({ value, label: value.replaceAll("_", " ") })) },
      { key: "status", label: "Status", type: "select", options: ["pending", "completed", "failed", "cancelled"].map((value) => ({ value, label: value })) },
      { key: "created_after", label: "Created from", type: "date" },
      { key: "created_before", label: "Created to", type: "date" },
    ],
    columns: [
      { key: "id", label: "Reference" },
      { key: "player_id", label: "Player ID" },
      { key: "type", label: "Type", kind: "status" },
      { key: "status", label: "Status", kind: "status" },
      { key: "amount", label: "Amount", kind: "money" },
      { key: "method", label: "Method" },
      { key: "created_at", label: "Created", kind: "date" },
    ],
  },
  bets: {
    title: "Bets",
    description: "Recent wager activity across games and players.",
    endpoint: "/api/bets",
    resource: "bets",
    exportable: true,
    detailEndpoint: (id) => `/api/bets/${id}/detail`,
    filters: [
      { key: "player_id", label: "Player ID", type: "number" },
      { key: "game_id", label: "Game ID", type: "number" },
      { key: "is_win", label: "Result", type: "select", options: [{ value: "true", label: "Win" }, { value: "false", label: "Loss" }] },
      { key: "placed_after", label: "Placed from", type: "date" },
      { key: "placed_before", label: "Placed to", type: "date" },
    ],
    columns: [
      { key: "id", label: "Bet ID" },
      { key: "player_id", label: "Player ID" },
      { key: "game_id", label: "Game ID" },
      { key: "stake", label: "Stake", kind: "money" },
      { key: "payout", label: "Payout", kind: "money" },
      { key: "is_win", label: "Result", kind: "status" },
      { key: "placed_at", label: "Placed", kind: "date" },
    ],
  },
  "risk-alerts": {
    title: "Risk alerts",
    description: "Review flagged activity and alert severity.",
    endpoint: "/api/risk-alerts",
    resource: "risk-alerts",
    exportable: true,
    detailEndpoint: (id) => `/api/risk-alerts/${id}/detail`,
    filters: [
      { key: "player_id", label: "Player ID", type: "number" },
      { key: "alert_type", label: "Signal", type: "select", options: ["rapid_deposits", "structured_withdrawals", "shared_device", "loss_chasing", "unusual_bet_size"].map((value) => ({ value, label: value.replaceAll("_", " ") })) },
      { key: "severity", label: "Severity", type: "select", options: ["low", "medium", "high", "critical"].map((value) => ({ value, label: value })) },
      { key: "status", label: "Status", type: "select", options: ["open", "in_review", "resolved", "dismissed"].map((value) => ({ value, label: value.replaceAll("_", " ") })) },
      { key: "created_after", label: "Created from", type: "date" },
      { key: "created_before", label: "Created to", type: "date" },
    ],
    columns: [
      { key: "id", label: "Alert ID" },
      { key: "player_id", label: "Player ID" },
      { key: "alert_type", label: "Signal" },
      { key: "severity", label: "Severity", kind: "status" },
      { key: "status", label: "Status", kind: "status" },
      { key: "created_at", label: "Created", kind: "date" },
    ],
  },
  "audit-log": {
    title: "Audit log",
    description: "A traceable record of administrative activity.",
    endpoint: "/api/audit-log",
    resource: "audit-log",
    columns: [
      { key: "id", label: "Event ID" },
      { key: "admin_user_id", label: "Admin ID" },
      { key: "action", label: "Action" },
      { key: "resource_type", label: "Resource" },
      { key: "resource_id", label: "Resource ID" },
      { key: "created_at", label: "Timestamp", kind: "date" },
    ],
  },
};

const navItems = [
  { path: "/dashboard", label: "Dashboard", icon: "▦" },
  { path: "/players", label: "Players", icon: "◉" },
  { path: "/games", label: "Games", icon: "▧" },
  { path: "/transactions", label: "Transactions", icon: "↗" },
  { path: "/bets", label: "Bets", icon: "⌁" },
  { path: "/risk-alerts", label: "Risk alerts", icon: "△" },
];

function App() {
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [checkingSession, setCheckingSession] = useState(true);
  const [locale, setLocale] = useState<Locale>(getInitialLocale);
  const [theme, setTheme] = useState<ThemeMode>(getInitialTheme);
  const [resolvedTheme, setResolvedTheme] = useState<"light" | "dark">(
    () => theme === "system" ? systemTheme() : theme,
  );
  const t = useCallback((message: string) => translate(message, locale), [locale]);

  useEffect(() => {
    document.documentElement.lang = locale;
    if (theme !== "system") {
      localStorage.setItem("casino-dashboard-theme", theme);
      setResolvedTheme(theme);
      return;
    }
    localStorage.removeItem("casino-dashboard-theme");
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const updateTheme = () => setResolvedTheme(media.matches ? "dark" : "light");
    updateTheme();
    media.addEventListener("change", updateTheme);
    return () => media.removeEventListener("change", updateTheme);
  }, [locale, theme]);

  useEffect(() => {
    document.documentElement.dataset.theme = resolvedTheme;
    document.documentElement.style.colorScheme = resolvedTheme;
  }, [resolvedTheme]);

  const preferenceValues = useMemo<PreferencesContextValue>(
    () => ({
      locale,
      t,
      theme,
      resolvedTheme,
      setLocale: (nextLocale) => {
        localStorage.setItem("casino-dashboard-locale", nextLocale);
        setLocale(nextLocale);
      },
      toggleTheme: () => {
        const nextTheme = resolvedTheme === "dark" ? "light" : "dark";
        localStorage.setItem("casino-dashboard-theme", nextTheme);
        setTheme(nextTheme);
      },
    }),
    [locale, resolvedTheme, t, theme],
  );

  useEffect(() => {
    apiRequest<Admin>("/api/auth/me")
      .then(setAdmin)
      .catch((error: unknown) => {
        if (!(error instanceof ApiError) || error.status !== 401) {
          console.error("Could not restore the administrator session", error);
        }
      })
      .finally(() => setCheckingSession(false));
  }, []);

  const auth = useMemo<AuthContextValue>(
    () => ({
      admin,
      setAdmin,
      signOut: async () => {
        await apiRequest<void>("/api/auth/logout", { method: "POST" });
        setAdmin(null);
      },
    }),
    [admin],
  );

  if (checkingSession) {
    return (
      <PreferencesContext.Provider value={preferenceValues}>
        <div className="screen-loading"><span className="spinner" />{translate("Checking session", locale)}</div>
      </PreferencesContext.Provider>
    );
  }

  return (
    <PreferencesContext.Provider value={preferenceValues}>
      <AuthContext.Provider value={auth}>
        <Routes>
        <Route path="/login" element={admin ? <Navigate to="/dashboard" replace /> : <LoginPage />} />
        <Route element={<ProtectedLayout />}>
          <Route index element={<Navigate to="/dashboard" replace />} />
          <Route path="dashboard" element={<DashboardPage />} />
          {Object.keys(pages).filter((key) => key !== "audit-log").map((key) => (
            <Route key={key} path={key} element={<DataPage page={pages[key]} />} />
          ))}
          <Route path="audit-log" element={<SuperAdminPage />} />
          <Route path="access-requests" element={<AccessRequestsPage />} />
        </Route>
        <Route path="*" element={<Navigate to={admin ? "/dashboard" : "/login"} replace />} />
        </Routes>
      </AuthContext.Provider>
    </PreferencesContext.Provider>
  );
}

function PreferencesControls() {
  const { locale, setLocale, resolvedTheme, toggleTheme, t } = usePreferences();
  const targetTheme = resolvedTheme === "dark" ? "light" : "dark";
  return (
    <div className="preferences-controls" role="group" aria-label={t("Display preferences")}>
      <label className="language-select">
        <span className="visually-hidden">{t("Language")}</span>
        <select
          aria-label={t("Language")}
          value={locale}
          onChange={(event) => setLocale(event.target.value === "es" ? "es" : "en")}
        >
          <option value="en">🇬🇧 English</option>
          <option value="es">🇪🇸 Español</option>
        </select>
      </label>
      <button
        className="theme-toggle"
        type="button"
        onClick={toggleTheme}
        aria-label={t(`Switch to ${targetTheme} theme`)}
        title={t(`Switch to ${targetTheme} theme`)}
      >
        <span aria-hidden="true">{resolvedTheme === "dark" ? "☀" : "☾"}</span>
        <span>{t(`Switch to ${targetTheme} theme`)}</span>
      </button>
    </div>
  );
}

function LoginPage() {
  const { setAdmin } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [registrationSent, setRegistrationSent] = useState(false);

  async function submitForm(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (mode === "login") {
        const result = await apiRequest<{ admin: Admin }>("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({ username, password }),
        });
        setAdmin(result.admin);
        navigate("/dashboard", { replace: true });
      } else {
        await apiRequest<{ status: string }>("/api/auth/register", {
          method: "POST",
          body: JSON.stringify({ username, email, full_name: fullName, password }),
        });
        setRegistrationSent(true);
      }
    } catch (cause) {
      setError(t(cause instanceof Error ? cause.message : "Could not sign in"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-screen">
      <div className="auth-preferences"><PreferencesControls /></div>
      <section className="auth-card">
        <div className="auth-visual">
          <Brand />
          <div className="visual-copy">
            <p className="eyebrow">{t("Casino Demo · Operations")}</p>
            <h1>{t("One clear view of your casino.")}</h1>
            <p>{t("Securely monitor players, transactions and risk signals from one place.")}</p>
          </div>
          <div className="visual-footer"><span className="live-dot" /> {t("Secure admin workspace")}</div>
          <div className="visual-orbit orbit-one" />
          <div className="visual-orbit orbit-two" />
        </div>
        <div className="auth-panel">
          {registrationSent ? (
            <>
              <div className="success-icon">✓</div>
              <p className="eyebrow">{t("Registration submitted")}</p>
              <h2>{t("Request received")}</h2>
              <p className="muted">
                {t("A super administrator must approve your support account before you can sign in. You can now return to the sign-in screen.")}
              </p>
              <button className="button button-primary button-wide" onClick={() => { setRegistrationSent(false); setMode("login"); }}>
                {t("Return to sign in")}
              </button>
            </>
          ) : (
            <>
              <p className="eyebrow">{t("Administrator access")}</p>
              <h2>{t(mode === "login" ? "Welcome back" : "Request an account")}</h2>
              <p className="muted">{t(mode === "login" ? "Sign in with your username and password." : "New accounts are created as support and need super-admin approval.")}</p>
              <div className="auth-mode" role="group" aria-label={t("Sign-in method")}>
                <button
                  type="button"
                  aria-pressed={mode === "login"}
                  className={mode === "login" ? "selected" : ""}
                  onClick={() => { setMode("login"); setError(""); }}
                >
                  {t("Sign in")}
                </button>
                <button
                  type="button"
                  aria-pressed={mode === "register"}
                  className={mode === "register" ? "selected" : ""}
                  onClick={() => { setMode("register"); setError(""); }}
                >
                  {t("Register")}
                </button>
              </div>
              <form onSubmit={submitForm} className="auth-form">
                <label htmlFor="username">{t("Username")}</label>
                <input
                  id="username"
                  autoComplete="username"
                  placeholder={t("e.g. alex.morgan")}
                  minLength={3}
                  maxLength={40}
                  pattern="[A-Za-z0-9._-]+"
                  value={username}
                  onChange={(event) => setUsername(event.target.value)}
                  required
                />
                {mode === "register" && (
                  <>
                    <label htmlFor="full-name">{t("Full name")}</label>
                    <input
                      id="full-name"
                      autoComplete="name"
                      maxLength={120}
                      value={fullName}
                      onChange={(event) => setFullName(event.target.value)}
                      required
                    />
                    <label htmlFor="email">{t("Email")}</label>
                    <input
                      id="email"
                      type="email"
                      autoComplete="email"
                      placeholder={t("name@example.com")}
                      maxLength={255}
                      value={email}
                      onChange={(event) => setEmail(event.target.value)}
                      required
                    />
                  </>
                )}
                <label htmlFor="password">{t("Password")}</label>
                <input
                  id="password"
                  type="password"
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  placeholder={t("Enter your password")}
                  minLength={mode === "register" ? 12 : 1}
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
                {error && <p className="form-error" role="alert">{error}</p>}
                <button className="button button-primary button-wide" disabled={busy}>
                  {busy ? t("Please wait…") : mode === "login" ? t("Sign in") : t("Submit registration")}
                </button>
              </form>
              <p className="auth-note"><span className="lock-icon">◇</span> {t("Password protected · Five failed attempts lock access for 15 minutes")}</p>
            </>
          )}
        </div>
      </section>
      <p className="auth-copyright">{t("CASINO DEMO · LOCAL ADMINISTRATION ONLY")}</p>
    </main>
  );
}

function ProtectedLayout() {
  const { admin, signOut } = useAuth();
  const t = useT();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [signOutError, setSignOutError] = useState("");
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  const closeNavigation = useCallback(() => {
    setMenuOpen(false);
    menuButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!menuOpen) return;
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") closeNavigation();
    }
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [closeNavigation, menuOpen]);

  if (!admin) return <Navigate to="/login" state={{ from: location }} replace />;

  async function handleSignOut() {
    setSignOutError("");
    try {
      await signOut();
      navigate("/login", { replace: true });
    } catch (error) {
      console.error("Could not revoke the administrator session", error);
      setSignOutError(t("Could not sign out. Check your connection and try again."));
    }
  }

  return (
    <div className="app-shell">
      <aside className={`sidebar ${menuOpen ? "sidebar-open" : ""}`}>
        <Link to="/dashboard" className="brand-link"><Brand /></Link>
        <p className="nav-section-label">{t("WORKSPACE")}</p>
        <nav id="primary-navigation" aria-label={t("Main navigation")}>
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
              onClick={() => setMenuOpen(false)}
            >
              <span className="nav-icon">{item.icon}</span>
              {t(item.label)}
            </NavLink>
          ))}
          {admin.role === "super_admin" && (
            <>
              <NavLink
                to="/access-requests"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                onClick={() => setMenuOpen(false)}
              >
                <span className="nav-icon">♧</span>
                {t("Access requests")}
              </NavLink>
              <NavLink
                to="/audit-log"
                className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
                onClick={() => setMenuOpen(false)}
              >
                <span className="nav-icon">≋</span>
                {t("Audit log")}
              </NavLink>
            </>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div className="security-card">
            <span className="security-mark">✓</span>
            <div><strong>{t("Account secured")}</strong><small>{t("Password and session protection")}</small></div>
          </div>
          <button className="profile-button" onClick={handleSignOut}>
            <span className="avatar">{admin.full_name.slice(0, 1).toUpperCase()}</span>
            <span className="profile-copy"><strong>{admin.full_name}</strong><small>{t(admin.role)}</small></span>
            <span className="signout-icon">↗</span>
          </button>
        </div>
      </aside>
      {menuOpen && <button aria-label={t("Close navigation")} className="sidebar-scrim" onClick={closeNavigation} />}
      <div className="main-shell">
        <header className="topbar">
          <button
            ref={menuButtonRef}
            className="menu-button"
            aria-label={t(menuOpen ? "Close navigation" : "Open navigation")}
            aria-expanded={menuOpen}
            aria-controls="primary-navigation"
            onClick={() => setMenuOpen((open) => !open)}
          >
            ☰
          </button>
          <div className="breadcrumb"><span>{t("Casino Demo")}</span><b>/</b><strong>{t(titleFromPath(location.pathname))}</strong></div>
          <div className="topbar-right"><span className="environment-pill"><span className="live-dot" /> {t("LOCAL DEMO")}</span><PreferencesControls /><span className="top-avatar">{admin.full_name.slice(0, 1).toUpperCase()}</span></div>
        </header>
        {signOutError && <div className="signout-error" role="alert">{signOutError}</div>}
        <main className="content"><Outlet /></main>
        <footer className="app-footer"><span>{t("Casino Admin")}</span><span>{t("Fictional demo data · Single currency")}</span></footer>
      </div>
    </div>
  );
}

function SuperAdminPage() {
  const { admin } = useAuth();
  return admin?.role === "super_admin"
    ? <DataPage page={pages["audit-log"]} />
    : <Navigate to="/players" replace />;
}

function DashboardPage() {
  const { setAdmin } = useAuth();
  const { locale } = usePreferences();
  const t = useT();
  const [startDate, setStartDate] = useState(() => {
    const start = new Date();
    start.setUTCDate(start.getUTCDate() - 29);
    return start.toISOString().slice(0, 10);
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [registrationMonths, setRegistrationMonths] = useState("all");
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let timeoutId: number | undefined;

    if (!startDate || !endDate) {
      setError(t("Select both dates to load dashboard metrics."));
      setLoading(false);
      return () => controller.abort();
    }

    if (startDate > endDate) {
      setError(t("Start date must be on or before end date."));
      setLoading(false);
      return () => controller.abort();
    }

    async function refreshMetrics() {
      const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate,
        registration_months: registrationMonths,
      });
      try {
        const result = await apiRequest<DashboardMetrics>(
          `/api/dashboard/metrics?${params}`,
          { signal: controller.signal },
        );
        if (!cancelled) {
          setMetrics(result);
          setError("");
          setLastUpdated(new Date());
        }
      } catch (cause) {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        if (cause instanceof ApiError && cause.status === 401) {
          setAdmin(null);
          return;
        }
        if (!cancelled) {
          setError(t(cause instanceof Error ? cause.message : "Could not load dashboard metrics"));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
          timeoutId = window.setTimeout(refreshMetrics, 5000);
        }
      }
    }

    setError("");
    void refreshMetrics();
    return () => {
      cancelled = true;
      controller.abort();
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
    };
  }, [endDate, registrationMonths, setAdmin, startDate]);

  return (
    <section className="dashboard-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("CASINO OPERATIONS")}</p>
          <h1>{t("Dashboard")}</h1>
          <p className="page-description">{t("Performance overview and activity trends.")}</p>
        </div>
        <div className="heading-meta"><span className="live-dot" /> {t("Live database · refreshes every 5 seconds")}</div>
      </div>

      

      {error && <div className="dashboard-error" role="alert">{error}</div>}
      {loading && !metrics ? (
        <div className="metrics-loading"><span className="spinner" /> {t("Loading dashboard metrics…")}</div>
      ) : metrics && (
        <>
          <section className="date-range-group" aria-labelledby="range-group-title">
            <div className="dashboard-toolbar">
        <div><strong>{t("Date range")}</strong><span>{t("All dashboard metrics use UTC dates")}</span></div>
        <label>{t("From")}<input aria-label={t("Start date")} type="date" value={startDate} max={endDate} onChange={(event) => setStartDate(event.target.value)} /></label>
        <label>{t("To")}<input aria-label={t("End date")} type="date" value={endDate} min={startDate} onChange={(event) => setEndDate(event.target.value)} /></label>
        <label className="registration-period">{t("Registration period")}
          <select aria-label={t("Registration channel period")} value={registrationMonths} onChange={(event) => setRegistrationMonths(event.target.value)}>
            <option value="all">{t("All time")}</option>
            <option value="1">{t("Last month")}</option>
            <option value="3">{t("Last 3 months")}</option>
            <option value="6">{t("Last 6 months")}</option>
          </select>
        </label>
        <span className="last-updated">
          {lastUpdated ? t("Updated {time}").replace("{time}", lastUpdated.toLocaleTimeString(locale)) : loading ? t("Loading metrics…") : t("Waiting for data")}
        </span>
      </div>
            <div className="analytics-section-heading">
              <div>
                <p className="eyebrow">{t("SELECTED PERIOD")}</p>
                <h2 id="range-group-title">{t("Date-range performance")}</h2>
                <p>{t("Cards and charts in this section use the date range above.")}</p>
              </div>
            </div>
          <div className="metric-grid">
            <MetricCard label={t("Gross gaming revenue")} value={formatMoney(metrics.ggr, locale)} detail={t("Stakes minus payouts")} accent="green" />
            <MetricCard label={t("Completed deposits")} value={formatMoney(metrics.deposits, locale)} detail={t("Settled deposits in range")} accent="lime" />
            <MetricCard label={t("Completed withdrawals")} value={formatMoney(metrics.withdrawals, locale)} detail={t("Settled withdrawals in range")} accent="blue" />
            <MetricCard label={t("Active players")} value={metrics.active_players.toLocaleString(locale)} detail={t("Players with at least one bet")} accent="violet" />
            <MetricCard label={t("Bets placed")} value={metrics.bets_count.toLocaleString(locale)} detail={t("All bets placed in range")} accent="orange" />
          </div>
          <div className="chart-grid">
            <MetricChart
              title={t("Daily gross gaming revenue")}
              subtitle={t("Stake value minus payout by UTC day")}
              daily={metrics.daily}
              series={[{ key: "ggr", label: "GGR", color: "var(--chart-green)" }]}
              signed
            />
            <MetricChart
              title={t("Completed cash flow")}
              subtitle={t("Settled deposits and withdrawals by UTC day")}
              daily={metrics.daily}
              series={[
                { key: "deposits", label: t("Deposits"), color: "var(--chart-green)" },
                { key: "withdrawals", label: t("Withdrawals"), color: "var(--chart-amber)" },
              ]}
            />
          </div>
          </section>
          <section className="all-time-group" aria-labelledby="all-time-group-title">
            <div className="analytics-section-heading">
              <div>
                <p className="eyebrow">{t("PLAYER & LIFETIME INSIGHTS")}</p>
                <h2 id="all-time-group-title">{t("All-time and historical overview")}</h2>
                <p>{t("These charts use all-time player data or the latest six calendar months.")}</p>
              </div>
            </div>
            <div className="lifetime-metric">
              <MetricCard label={t("Total GGR · all time")} value={formatMoney(metrics.all_time_ggr, locale)} detail={t("All bets since the start")} accent="violet" />
            </div>
          <div className="insight-grid">
            <RegistrationChannelChart
              items={metrics.registration_channels}
              total={metrics.registration_channels.reduce((sum, item) => sum + item.count, 0)}
              period={metrics.registration_channel_period}
            />
            <DistributionChart title={t("Players by VIP tier")} subtitle={t("All registered players")} items={metrics.vip_tiers} />
            <DistributionChart title={t("Players by current age")} subtitle={t("All registered players · current age")} items={metrics.age_bands} />
          </div>
          <div className="chart-grid extended-charts">
            <MonthlyGGRChart items={metrics.monthly_ggr} />
            <BetHeatmap cells={metrics.bet_heatmap} />
          </div>
          </section>
        </>
      )}
    </section>
  );
}

function MetricCard({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string;
  detail: string;
  accent: string;
}) {
  const t = useT();
  return (
    <article className={`metric-card metric-${accent}`}>
      <span className="metric-accent" />
      <p>{t(label)}</p>
      <strong>{value}</strong>
      <small>{detail}</small>
    </article>
  );
}

function MetricChart({
  title,
  subtitle,
  daily,
  series,
  signed = false,
}: {
  title: string;
  subtitle: string;
  daily: DashboardDailyMetrics[];
  series: { key: "ggr" | "deposits" | "withdrawals"; label: string; color: string }[];
  signed?: boolean;
}) {
  const { locale } = usePreferences();
  const t = useT();
  const width = 720;
  const height = 210;
  const baseline = signed ? 95 : 160;
  const top = 18;
  const chartHeight = signed ? 70 : baseline - top;
  const values = daily.flatMap((day) => series.map(({ key }) => Number(day[key])));
  const maximum = Math.max(1, ...values.map((value) => Math.abs(value)));
  const slot = width / Math.max(daily.length, 1);
  const barWidth = Math.max(2, Math.min(12, (slot * 0.7) / series.length));
  const labelIndexes = new Set(
    [0, Math.floor((daily.length - 1) / 4), Math.floor((daily.length - 1) / 2),
      Math.floor(((daily.length - 1) * 3) / 4), daily.length - 1],
  );

  return (
    <section className="chart-card">
      <div className="chart-heading"><div><h2>{title}</h2><p>{subtitle}</p></div></div>
      <div className="chart-legend">
        {series.map((item) => <span key={item.key}><i style={{ backgroundColor: item.color }} />{item.label}</span>)}
      </div>
      <svg className="metric-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
        <line x1="0" y1={baseline} x2={width} y2={baseline} className="chart-axis" />
        {daily.map((day, dayIndex) => {
          const groupWidth = slot * 0.7;
          const groupStart = dayIndex * slot + (slot - groupWidth) / 2;
          return series.map((item, seriesIndex) => {
            const value = Number(day[item.key]);
            const barHeight = (Math.abs(value) / maximum) * chartHeight;
            const x = groupStart + seriesIndex * barWidth;
            const y = signed && value < 0 ? baseline : baseline - barHeight;
            return (
              <g
                key={`${day.date}-${item.key}`}
                className="bar-mark"
                tabIndex={0}
                role="img"
                aria-label={`${day.date}: ${t(item.label)} ${formatMoney(value, locale)}`}
              >
                <rect
                  className="chart-bar"
                  x={x}
                  y={y}
                  width={barWidth - 1}
                  height={Math.max(1, barHeight)}
                  rx="2"
                  fill={item.color}
                />
                <SvgBarTooltip
                  x={x + (barWidth - 1) / 2}
                  y={y}
                  width={width}
                  label={`${day.date} · ${t(item.label)}`}
                  value={formatMoney(value, locale)}
                />
              </g>
            );
          });
        })}
        {[...labelIndexes].map((index) => daily[index] && (
          <text key={daily[index].date} x={index * slot + slot / 2} y="194" textAnchor="middle" className="chart-label">
            {daily[index].date.slice(5)}
          </text>
        ))}
      </svg>
      {daily.length === 0 && <p className="chart-empty">{t("No activity in this date range.")}</p>}
    </section>
  );
}

function formatMoney(value: string | number, locale: Locale = "en") {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? new Intl.NumberFormat(locale === "es" ? "es-ES" : "en-US", { style: "currency", currency: "USD" }).format(amount)
    : "—";
}

function formatCompactMoney(value: string | number, locale: Locale) {
  const amount = Number(value);
  return Number.isFinite(amount)
    ? new Intl.NumberFormat(locale === "es" ? "es-ES" : "en-US", {
      style: "currency",
      currency: "USD",
      notation: "compact",
      maximumFractionDigits: 1,
    }).format(amount)
    : "—";
}

function SvgBarTooltip({
  x,
  y,
  width,
  label,
  value,
}: {
  x: number;
  y: number;
  width: number;
  label: string;
  value: string;
}) {
  const tooltipWidth = 148;
  const tooltipHeight = 43;
  const tooltipX = Math.max(tooltipWidth / 2 + 3, Math.min(width - tooltipWidth / 2 - 3, x));
  const tooltipY = Math.max(tooltipHeight / 2 + 3, y - tooltipHeight / 2 - 7);

  return (
    <g className="bar-tooltip" transform={`translate(${tooltipX}, ${tooltipY})`} aria-hidden="true">
      <rect x={-tooltipWidth / 2} y={-tooltipHeight / 2} width={tooltipWidth} height={tooltipHeight} rx="7" />
      <text className="bar-tooltip-label" x="0" y="-5" textAnchor="middle">{label}</text>
      <text className="bar-tooltip-value" x="0" y="12" textAnchor="middle">{value}</text>
    </g>
  );
}

const chartColors = [
  "var(--chart-green)",
  "var(--chart-amber)",
  "var(--chart-blue)",
  "var(--chart-violet)",
  "var(--chart-orange)",
];

function RegistrationChannelChart({
  items,
  total,
  period,
}: {
  items: DashboardDistributionItem[];
  total: number;
  period: string;
}) {
  const { locale } = usePreferences();
  const t = useT();
  const radius = 43;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  const slices = items.map((item, index) => {
    const length = total ? circumference * item.count / total : 0;
    const slice = { ...item, color: chartColors[index % chartColors.length], length, offset };
    offset += length;
    return slice;
  });
  const periodLabel = period === "all"
    ? t("All time")
    : t(period === "1" ? "Last month" : "Last {count} months").replace("{count}", period);

  return (
    <section className="chart-card insight-card">
      <div className="chart-heading"><div><h2>{t("Players by registration channel")}</h2><p>{periodLabel} · {t("registration source, not login device")}</p></div></div>
      <div className="donut-layout">
        <svg className="donut-chart" viewBox="0 0 120 120" role="img" aria-label={t("Registration channel percentages")}>
          <circle cx="60" cy="60" r={radius} fill="none" stroke="var(--chart-track)" strokeWidth="15" />
          {slices.map((slice) => (
            <circle
              key={slice.key}
              cx="60"
              cy="60"
              r={radius}
              fill="none"
              stroke={slice.color}
              strokeWidth="15"
              strokeDasharray={`${slice.length} ${circumference - slice.length}`}
              strokeDashoffset={-slice.offset}
              transform="rotate(-90 60 60)"
            >
              <title>{`${t(slice.label)}: ${slice.percentage}% (${slice.count})`}</title>
            </circle>
          ))}
          <text x="60" y="57" textAnchor="middle" className="donut-total">{total.toLocaleString(locale)}</text>
          <text x="60" y="71" textAnchor="middle" className="donut-caption">{t("players")}</text>
        </svg>
        <div className="donut-legend">
          {slices.map((slice) => (
            <div key={slice.key}>
              <span><i style={{ backgroundColor: slice.color }} />{t(slice.label)}</span>
              <strong>{slice.percentage}% <small>({slice.count.toLocaleString(locale)})</small></strong>
            </div>
          ))}
          {total === 0 && <p className="chart-empty">{t("No players in this period.")}</p>}
        </div>
      </div>
    </section>
  );
}

function DistributionChart({
  title,
  subtitle,
  items,
}: {
  title: string;
  subtitle: string;
  items: DashboardDistributionItem[];
}) {
  const { locale } = usePreferences();
  const t = useT();
  return (
    <section className="chart-card insight-card">
      <div className="chart-heading"><div><h2>{t(title)}</h2><p>{t(subtitle)}</p></div></div>
      <div className="distribution-list">
        {items.map((item, index) => (
          <div className="distribution-row" key={item.key}>
            <div className="distribution-label">
              <span>{t(item.label)}</span>
              <strong>{item.count.toLocaleString(locale)} <small>· {item.percentage}%</small></strong>
            </div>
            <div className="distribution-track" role="img" aria-label={`${t(item.label)}: ${item.count.toLocaleString(locale)} ${t("players")}, ${item.percentage}%`}>
              <span style={{ width: `${Math.min(item.percentage, 100)}%`, backgroundColor: chartColors[index % chartColors.length] }} />
            </div>
          </div>
        ))}
        {items.every((item) => item.count === 0) && <p className="chart-empty">{t("No player data available.")}</p>}
      </div>
    </section>
  );
}

function MonthlyGGRChart({ items }: { items: DashboardMonthlyGGR[] }) {
  const { locale } = usePreferences();
  const t = useT();
  const width = 720;
  const height = 240;
  const baseline = 112;
  const top = 29;
  const bottom = 190;
  const max = Math.max(1, ...items.map((item) => Math.abs(Number(item.ggr))));
  const slot = width / Math.max(items.length, 1);
  const barWidth = Math.min(46, slot * 0.48);

  return (
    <section className="chart-card">
      <div className="chart-heading"><div><h2>{t("GGR by month")}</h2><p>{t("Six UTC calendar months · current month may be partial")}</p></div></div>
      <svg className="metric-chart monthly-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={t("Gross gaming revenue by month")}>
        <line x1="0" y1={baseline} x2={width} y2={baseline} className="chart-axis" />
        {items.map((item, index) => {
          const value = Number(item.ggr);
          const barHeight = Math.abs(value) / max * Math.min(baseline - top, bottom - baseline);
          const x = index * slot + (slot - barWidth) / 2;
          const y = value < 0 ? baseline : baseline - barHeight;
          const monthLabel = new Intl.DateTimeFormat(locale === "es" ? "es-ES" : "en-US", {
            month: "short",
            year: "numeric",
            timeZone: "UTC",
          }).format(new Date(`${item.month}T00:00:00Z`));
          return (
            <g
              key={item.month}
              className="bar-mark"
              tabIndex={0}
              role="img"
              aria-label={`${monthLabel}: ${formatMoney(value, locale)}`}
            >
              <rect
                className="chart-bar"
                x={x}
                y={y}
                width={barWidth}
                height={Math.max(barHeight, 1)}
                rx="3"
                fill={value < 0 ? "var(--chart-negative)" : "var(--chart-green)"}
              />
              <text
                x={index * slot + slot / 2}
                y={value < 0 ? Math.min(bottom + 14, y + Math.max(barHeight, 1) + 14) : Math.max(15, y - 7)}
                textAnchor="middle"
                className="monthly-value-label"
              >
                {formatCompactMoney(value, locale)}
              </text>
              <SvgBarTooltip
                x={index * slot + slot / 2}
                y={y}
                width={width}
                label={monthLabel}
                value={formatMoney(value, locale)}
              />
              <text x={index * slot + slot / 2} y="230" textAnchor="middle" className="chart-label">{monthLabel}</text>
            </g>
          );
        })}
      </svg>
      {items.every((item) => Number(item.ggr) === 0) && <p className="chart-empty">{t("No GGR recorded in these months.")}</p>}
    </section>
  );
}

const weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function BetHeatmap({ cells }: { cells: DashboardHeatmapCell[] }) {
  const { locale } = usePreferences();
  const t = useT();
  const maximum = Math.max(0, ...cells.map((cell) => cell.bets_count));
  const countsByTime = new Map(
    cells.map((cell) => [`${cell.weekday}-${cell.hour}`, cell.bets_count]),
  );
  const colorFor = (count: number) => {
    if (!count || maximum === 0) return "var(--heatmap-0)";
    const intensity = count / maximum;
    if (intensity < 0.2) return "var(--heatmap-1)";
    if (intensity < 0.4) return "var(--heatmap-2)";
    if (intensity < 0.6) return "var(--heatmap-3)";
    if (intensity < 0.8) return "var(--heatmap-4)";
    return "var(--heatmap-5)";
  };

  return (
    <section className="chart-card">
      <div className="chart-heading"><div><h2>{t("Bet activity heatmap")}</h2><p>{t("All time · UTC weekday and hour")}</p></div></div>
      <div className="heatmap-scroll" role="region" aria-label={t("Scroll heatmap by hour")} tabIndex={0}>
        <div className="heatmap-grid" role="grid" aria-label={t("Bet counts by weekday and UTC hour")}>
          <span className="heatmap-corner" />
          {Array.from({ length: 24 }, (_, hour) => <span className="heatmap-hour" key={hour}>{hour % 3 === 0 ? String(hour).padStart(2, "0") : ""}</span>)}
          {weekdayLabels.map((day, weekday) => {
            const localizedDay = new Intl.DateTimeFormat(locale === "es" ? "es-ES" : "en-US", {
              weekday: "short",
              timeZone: "UTC",
            }).format(new Date(Date.UTC(2024, 0, weekday + 1)));
            return (
            <div className="heatmap-row" role="row" key={day}>
              <span className="heatmap-day" role="rowheader">{localizedDay}</span>
              {Array.from({ length: 24 }, (_, hour) => {
                const count = countsByTime.get(`${weekday}-${hour}`) ?? 0;
                return (
                  <span
                    key={`${weekday}-${hour}`}
                    className="heatmap-cell"
                    role="gridcell"
                    aria-label={`${localizedDay} ${String(hour).padStart(2, "0")}:00 UTC: ${count.toLocaleString(locale)} ${t("bets")}`}
                    title={`${localizedDay} ${String(hour).padStart(2, "0")}:00 UTC · ${count.toLocaleString(locale)} ${t("bets")}`}
                    style={{ backgroundColor: colorFor(count) }}
                  />
                );
              })}
            </div>
            );
          })}
        </div>
      </div>
      <div className="heatmap-scale"><span>{t("Less")}</span>{Array.from({ length: 6 }, (_, index) => <i key={index} style={{ backgroundColor: `var(--heatmap-${index})` }} />)}<span>{t("More")}</span></div>
    </section>
  );
}

type PendingRegistration = {
  id: number;
  username: string;
  email: string;
  full_name: string;
  created_at: string;
};

function AccessRequestsPage() {
  const { admin } = useAuth();
  const { locale } = usePreferences();
  const t = useT();
  const [requests, setRequests] = useState<PendingRegistration[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    apiRequest<PageResult<PendingRegistration>>(
      "/api/admin/pending-registrations?page=1&page_size=100",
      { signal: controller.signal },
    )
      .then((result) => setRequests(result.items))
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(t(cause instanceof Error ? cause.message : "Could not load access requests"));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [t]);

  if (admin?.role !== "super_admin") return <Navigate to="/players" replace />;

  async function approve(userId: number) {
    setBusyId(userId);
    setError("");
    try {
      await apiRequest<Admin>(`/api/admin/users/${userId}/approve`, { method: "POST" });
      setRequests((current) => current.filter((user) => user.id !== userId));
    } catch (cause) {
      setError(t(cause instanceof Error ? cause.message : "Could not approve registration"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="data-page">
      <div className="page-heading">
        <div>
          <p className="eyebrow">{t("ACCOUNT ADMINISTRATION")}</p>
          <h1>{t("Access requests")}</h1>
          <p className="page-description">{t("Review and approve new support accounts.")}</p>
        </div>
      </div>
      <div className="table-card">
        <div className="table-toolbar">
          <div>
            <h2>{t("Pending registrations")}</h2>
            <p>{loading ? t("Loading requests") : `${requests.length.toLocaleString(locale)} ${t("requests awaiting review")}`}</p>
          </div>
        </div>
        {error && <div className="table-error" role="alert">{error}</div>}
        <div
          className="table-scroll"
          role="region"
          aria-label={t("Table: access requests")}
          tabIndex={0}
        >
          <table>
            <thead><tr><th>{t("Username")}</th><th>{t("Name")}</th><th>{t("Email")}</th><th>{t("Requested")}</th><th>{t("Action")}</th></tr></thead>
            <tbody>
              {loading && <tr><td className="table-state" colSpan={5}><span className="spinner" /> {t("Loading requests…")}</td></tr>}
              {!loading && requests.map((request) => (
                <tr key={request.id}>
                  <td>{request.username}</td>
                  <td>{request.full_name}</td>
                  <td>{request.email}</td>
                  <td>{renderCell(request.created_at, "date", locale, t)}</td>
                  <td>
                    <button
                      className="button button-search"
                      disabled={busyId !== null}
                      onClick={() => approve(request.id)}
                    >
                      {busyId === request.id ? t("Approving…") : t("Approve support")}
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && requests.length === 0 && <tr><td className="table-state" colSpan={5}>{t("No pending requests.")}</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
      <div className="phase-note"><span>✓</span><p><strong>{t("Least-privilege access")}</strong><br />{t("Approved accounts receive the support role. Only existing super administrators can approve a request or view this page.")}</p></div>
    </section>
  );
}

function DataPage({ page }: { page: PageConfig }) {
  const { admin, setAdmin } = useAuth();
  const { locale } = usePreferences();
  const t = useT();
  const [result, setResult] = useState<PageResult<Record<string, unknown>> | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [search, setSearch] = useState("");
  const [activeSearch, setActiveSearch] = useState("");
  const [draftFilters, setDraftFilters] = useState<Record<string, string>>({});
  const [activeFilters, setActiveFilters] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [details, setDetails] = useState<Record<string, Record<string, unknown>>>({});
  const [detailLoadingId, setDetailLoadingId] = useState<string | null>(null);
  const [detailError, setDetailError] = useState("");
  const [actionBusyId, setActionBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const pageSize = 10;

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ page: String(currentPage), page_size: String(pageSize) });
    if (activeSearch.trim() && page.searchable) params.set("q", activeSearch.trim());
    addFiltersToParams(params, activeFilters);
    setLoading(true);
    setError("");
    apiRequest<PageResult<Record<string, unknown>>>(`${page.endpoint}?${params}`, {
      signal: controller.signal,
    })
      .then(setResult)
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        if (cause instanceof ApiError && cause.status === 401) {
          setAdmin(null);
          return;
        }
        setError(t(cause instanceof Error ? cause.message : "Could not load records"));
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, [activeFilters, activeSearch, currentPage, page, reloadToken, setAdmin, t]);

  const totalPages = Math.max(1, Math.ceil((result?.total ?? 0) / pageSize));
  const extraColumns = Number(Boolean(page.detailEndpoint))
    + Number(["players", "games", "risk-alerts"].includes(page.resource));

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCurrentPage(1);
    setActiveSearch(search);
    setActiveFilters({ ...draftFilters });
    setExpandedId(null);
  }

  async function toggleDetails(row: Record<string, unknown>) {
    const id = String(row.id);
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    setDetailError("");
    if (!page.detailEndpoint || details[id]) return;

    setDetailLoadingId(id);
    try {
      const detail = await apiRequest<Record<string, unknown>>(page.detailEndpoint(id));
      setDetails((current) => ({ ...current, [id]: detail }));
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setAdmin(null);
        return;
      }
      setDetailError(t(cause instanceof Error ? cause.message : "Could not load record details"));
    } finally {
      setDetailLoadingId(null);
    }
  }

  async function exportFilteredRows() {
    setExporting(true);
    setError("");
    try {
      const params = new URLSearchParams();
      if (activeSearch.trim() && page.searchable) params.set("q", activeSearch.trim());
      addFiltersToParams(params, activeFilters);
      const query = params.toString();
      const { blob, filename } = await apiDownload(
        `/api/exports/${page.resource}.csv${query ? `?${query}` : ""}`,
      );
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setAdmin(null);
        return;
      }
      setError(t(cause instanceof Error ? cause.message : "Could not export filtered records"));
    } finally {
      setExporting(false);
    }
  }

  async function performRowAction(row: Record<string, unknown>, action: string) {
    const id = String(row.id);
    let path = "";
    let body: Record<string, unknown> = {};
    if (page.resource === "players") {
      const status = action as "active" | "suspended" | "closed";
      if (status === "closed" && !window.confirm(t("Close this player account? This cannot be undone."))) return;
      path = `/api/players/${id}/status`;
      body = { status };
    } else if (page.resource === "games") {
      const isActive = action === "activate";
      path = `/api/games/${id}/status`;
      body = { is_active: isActive };
    } else if (page.resource === "risk-alerts") {
      path = `/api/risk-alerts/${id}`;
      if (action === "in_review") {
        body = { status: action };
      } else {
        const note = window.prompt(t("Add a resolution note to {action} this alert:").replace("{action}", t(action)));
        if (!note?.trim()) return;
        body = { status: action, resolution_note: note.trim() };
      }
    } else {
      return;
    }

    setActionBusyId(id);
    setActionError("");
    try {
      const updated = await apiRequest<Record<string, unknown>>(path, {
        method: "PATCH",
        body: JSON.stringify(body),
      });
      setDetails((current) => ({ ...current, [id]: updated }));
      setReloadToken((current) => current + 1);
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 401) {
        setAdmin(null);
        return;
      }
      setActionError(t(cause instanceof Error ? cause.message : "Could not update this record"));
    } finally {
      setActionBusyId(null);
    }
  }

  return (
    <section className="data-page">
      <div className="page-heading">
        <div><p className="eyebrow">{t("CASINO OPERATIONS")}</p><h1>{t(page.title)}</h1><p className="page-description">{t(page.description)}</p></div>
        <div className="heading-meta"><span className="live-dot" /> {t("Live database")}</div>
      </div>
      <div className="table-card">
        <div className="table-toolbar">
          <div><h2>{t("All {resource}").replace("{resource}", t(page.title.toLowerCase()))}</h2><p>{result ? t("{count} records").replace("{count}", result.total.toLocaleString(locale)) : t("Loading records")}</p></div>
          {page.exportable && <button className="button button-export" type="button" disabled={exporting} onClick={() => void exportFilteredRows()}>{exporting ? t("Preparing CSV…") : t("Export filtered CSV")}</button>}
        </div>
        {(page.searchable || page.filters?.length) && (
          <form className="data-filters" onSubmit={submitSearch}>
            {page.searchable && (
              <label className="filter-field filter-search">{t("Search")}
                <input aria-label={t("Search {resource}").replace("{resource}", t(page.title.toLowerCase()))} placeholder={t("Search {resource}…").replace("{resource}", t(page.title.toLowerCase()))} value={search} onChange={(event) => setSearch(event.target.value)} />
              </label>
            )}
            {page.filters?.map((filter) => (
              <label className="filter-field" key={filter.key}>{t(filter.label)}
                {filter.type === "select" ? (
                  <select
                    aria-label={t(filter.label)}
                    value={draftFilters[filter.key] ?? ""}
                    onChange={(event) => setDraftFilters((current) => ({ ...current, [filter.key]: event.target.value }))}
                  >
                    <option value="">{t("All")}</option>
                    {filter.options?.map((option) => <option value={option.value} key={option.value}>{t(option.label)}</option>)}
                  </select>
                ) : (
                  <input
                    aria-label={t(filter.label)}
                    type={filter.type}
                    min={filter.type === "number" ? "1" : undefined}
                    value={draftFilters[filter.key] ?? ""}
                    onChange={(event) => setDraftFilters((current) => ({ ...current, [filter.key]: event.target.value }))}
                  />
                )}
              </label>
            ))}
            <div className="filter-actions">
              <button className="button button-search" type="submit">{t("Apply filters")}</button>
              <button
                className="button button-clear-filters"
                type="button"
                onClick={() => {
                  setSearch("");
                  setActiveSearch("");
                  setDraftFilters({});
                  setActiveFilters({});
                  setCurrentPage(1);
                  setExpandedId(null);
                }}
              >
                {t("Clear")}
              </button>
            </div>
          </form>
        )}
        {error && <div className="table-error" role="alert"><span>{error}</span><button className="text-button" onClick={() => setReloadToken((value) => value + 1)}>{t("Retry")}</button></div>}
        {actionError && <div className="table-error" role="alert">{actionError}</div>}
        <div
          className="table-scroll"
          role="region"
          aria-label={t("Table: {resource}").replace("{resource}", t(page.title.toLowerCase()))}
          tabIndex={0}
        >
          <table>
            <thead><tr>{page.columns.map((column) => <th key={column.key}>{t(column.label)}</th>)}{page.detailEndpoint && <th>{t("Details")}</th>}{["players", "games", "risk-alerts"].includes(page.resource) && <th>{t("Manage")}</th>}</tr></thead>
            <tbody>
              {loading && <tr><td className="table-state" colSpan={page.columns.length + extraColumns}><span className="spinner" /> {t("Loading records…")}</td></tr>}
              {!loading && result?.items.map((row, rowIndex) => (
                <Fragment key={String(row.id ?? rowIndex)}>
                <tr>
                  {page.columns.map((column) => <td key={column.key}>{renderCell(row[column.key], column.kind, locale, t)}</td>)}
                  {page.detailEndpoint && <td><button type="button" className="text-button" onClick={() => void toggleDetails(row)}>{t(expandedId === String(row.id) ? "Hide" : "View")}</button></td>}
                  {["players", "games", "risk-alerts"].includes(page.resource) && (
                    <td><RowActions
                      page={page}
                      row={row}
                      role={admin?.role ?? "support"}
                      busy={actionBusyId === String(row.id)}
                      onAction={(action) => void performRowAction(row, action)}
                      t={t}
                    /></td>
                  )}
                </tr>
                {expandedId === String(row.id) && (
                  <tr key={`${String(row.id)}-details`}>
                    <td colSpan={page.columns.length + extraColumns}>
                      <div className="record-details">
                        <h3>{t("Record details")}</h3>
                        {detailLoadingId === String(row.id) && <p>{t("Loading details…")}</p>}
                        {detailError && <p className="form-error" role="alert">{detailError}</p>}
                        {details[String(row.id)] && <DetailFields record={details[String(row.id)]} locale={locale} t={t} />}
                      </div>
                    </td>
                  </tr>
                )}
                </Fragment>
              ))}
              {!loading && result?.items.length === 0 && (
                <tr><td className="table-state" colSpan={page.columns.length + extraColumns}>{t("No records match the current filters.")}</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <div className="table-pagination">
          <span>{t("Showing {shown} of {total} records").replace("{shown}", (result?.items.length ?? 0).toLocaleString(locale)).replace("{total}", result?.total.toLocaleString(locale) ?? "—")}</span>
          <div className="pagination-actions">
            <span>{t("Page {current} of {total}").replace("{current}", currentPage.toLocaleString(locale)).replace("{total}", totalPages.toLocaleString(locale))}</span>
            <button aria-label={t("Previous page")} disabled={currentPage <= 1 || loading} onClick={() => setCurrentPage((value) => value - 1)}>←</button>
            <button aria-label={t("Next page")} disabled={currentPage >= totalPages || loading} onClick={() => setCurrentPage((value) => value + 1)}>→</button>
          </div>
        </div>
      </div>
      <div className="phase-note"><span>✦</span><p><strong>{t("Protected management workspace")}</strong><br />{t("Exports include all rows matching the applied filters, up to 10,000 records. Financial transactions and bets remain read-only; management actions are role-restricted and audited.")}</p></div>
    </section>
  );
}

function addFiltersToParams(params: URLSearchParams, filters: Record<string, string>) {
  for (const [key, rawValue] of Object.entries(filters)) {
    const value = rawValue.trim();
    if (!value) continue;
    if (value && (key.endsWith("_after") || key.endsWith("_before"))) {
      params.set(key, `${value}T${key.endsWith("_before") ? "23:59:59.999999" : "00:00:00"}Z`);
    } else {
      params.set(key, value);
    }
  }
}

function DetailFields({
  record,
  locale,
  t,
}: {
  record: Record<string, unknown>;
  locale: Locale;
  t: (message: string) => string;
}) {
  return (
    <dl className="detail-fields">
      {Object.entries(record).map(([key, value]) => (
        <div key={key}>
          <dt>{t(key.replaceAll("_", " "))}</dt>
          <dd>{value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : renderCell(value, key.endsWith("_at") ? "date" : key.endsWith("_status") || key === "status" ? "status" : undefined, locale, t)}</dd>
        </div>
      ))}
    </dl>
  );
}

function RowActions({
  page,
  row,
  role,
  busy,
  onAction,
  t,
}: {
  page: PageConfig;
  row: Record<string, unknown>;
  role: string;
  busy: boolean;
  onAction: (action: string) => void;
  t: (message: string) => string;
}) {
  if (busy) return <span className="empty-value">{t("Saving…")}</span>;
  if (page.resource === "players") {
    if (role !== "super_admin") return <span className="empty-value">{t("Super admin only")}</span>;
    const status = String(row.status);
    if (status === "closed") return <span className="empty-value">{t("Closed")}</span>;
    if (status === "self_excluded") {
      const exclusionEnd = row.self_exclusion_until ? new Date(String(row.self_exclusion_until)) : null;
      const exclusionActive = !exclusionEnd || exclusionEnd > new Date();
      return (
        <div className="row-actions">
          {exclusionActive
            ? <span className="empty-value">{t("Self-excluded")}</span>
            : <button type="button" className="text-button" onClick={() => onAction("active")}>{t("Reactivate")}</button>}
          <button type="button" className="text-button danger-action" onClick={() => onAction("closed")}>{t("Close")}</button>
        </div>
      );
    }
    return (
      <div className="row-actions">
        {status !== "active" && <button type="button" className="text-button" onClick={() => onAction("active")}>{t("Activate")}</button>}
        {status === "active" && <button type="button" className="text-button" onClick={() => onAction("suspended")}>{t("Suspend")}</button>}
        <button type="button" className="text-button danger-action" onClick={() => onAction("closed")}>{t("Close")}</button>
      </div>
    );
  }
  if (page.resource === "games") {
    if (role !== "super_admin") return <span className="empty-value">{t("Super admin only")}</span>;
    return <button type="button" className="text-button" onClick={() => onAction(row.is_active ? "deactivate" : "activate")}>{t(row.is_active ? "Deactivate" : "Activate")}</button>;
  }
  const status = String(row.status);
  if (status === "open") return <button type="button" className="text-button" onClick={() => onAction("in_review")}>{t("Start review")}</button>;
  if (status === "in_review") {
    return (
      <div className="row-actions">
        <button type="button" className="text-button" onClick={() => onAction("resolved")}>{t("Resolve")}</button>
        <button type="button" className="text-button danger-action" onClick={() => onAction("dismissed")}>{t("Dismiss")}</button>
      </div>
    );
  }
  return <span className="empty-value">{t(status.replaceAll("_", " "))}</span>;
}

function renderCell(
  value: unknown,
  kind: "money" | "date" | "status" | undefined,
  locale: Locale,
  t: (message: string) => string,
) {
  if (value === null || value === undefined || value === "") return <span className="empty-value">—</span>;
  if (kind === "money") {
    const number = Number(value);
    return Number.isFinite(number)
      ? new Intl.NumberFormat(locale === "es" ? "es-ES" : "en-US", { style: "currency", currency: "USD" }).format(number)
      : String(value);
  }
  if (kind === "date") {
    const parsed = new Date(String(value));
    return Number.isNaN(parsed.getTime())
      ? String(value)
      : parsed.toLocaleString(locale === "es" ? "es-ES" : "en-US", { dateStyle: "medium", timeStyle: "short" });
  }
  if (kind === "status") {
    const label = t(typeof value === "boolean" ? (value ? "Active" : "Inactive") : String(value).replaceAll("_", " "));
    return <span className={`status-chip ${toneForStatus(String(value))}`}>{label}</span>;
  }
  return String(value);
}

function toneForStatus(value: string) {
  const status = value.toLowerCase();
  if (["active", "approved", "completed", "resolved", "true", "win", "verified"].includes(status)) return "tone-green";
  if (["pending", "review", "medium", "open"].includes(status)) return "tone-amber";
  if (["suspended", "rejected", "failed", "high", "blocked", "false"].includes(status)) return "tone-red";
  return "tone-neutral";
}

function Brand() {
  return <div className="brand"><span className="brand-mark">C</span><span>CASINO<span className="brand-light"> / ADMIN</span></span></div>;
}

function titleFromPath(path: string) {
  const key = path.split("/").filter(Boolean)[0] ?? "dashboard";
  if (key === "dashboard") return "Dashboard";
  return pages[key]?.title ?? "Players";
}

export default App;
