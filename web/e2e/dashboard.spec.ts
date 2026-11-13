import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const admin = {
  id: 1,
  email: "demo.admin@example.test",
  full_name: "Demo Admin",
  role: "super_admin",
};

const metrics = {
  start_date: "2026-10-01",
  end_date: "2026-10-24",
  ggr: "125.00",
  deposits: "200.00",
  withdrawals: "75.00",
  active_players: 12,
  bets_count: 42,
  daily: [{ date: "2026-10-24", ggr: "125.00", deposits: "200.00", withdrawals: "75.00" }],
  registration_channel_period: "all",
  registration_channels: [
    { key: "web", label: "Web", count: 8, percentage: 66.7 },
    { key: "mobile", label: "Mobile", count: 4, percentage: 33.3 },
  ],
  vip_tiers: [{ key: "gold", label: "Gold", count: 12, percentage: 100 }],
  age_bands: [{ key: "26-35", label: "26-35", count: 12, percentage: 100 }],
  all_time_ggr: "512.00",
  monthly_ggr: [{ month: "2026-10-01", label: "Oct 2026", ggr: "125.00" }],
  bet_heatmap: [{ weekday: 4, hour: 12, bets_count: 2 }],
};

async function mockApi(page: import("@playwright/test").Page) {
  let playerSession = false;
  let usdBalance = 0;
  let chipBalance = 0;
  let slotSpins = 0;
  let vipTier = "standard";
  let vipExpiresAt: string | null = null;
  const transactions: {
    id: number;
    type: string;
    amount: number;
    method: string | null;
    origin: string;
    note: string | null;
    created_at: string;
  }[] = [];
  const chipEntries: { id: number; delta: number; reason: string; created_at: string }[] = [];
  const player = () => ({
    id: 1,
    username: "demo.player",
    first_name: "Demo",
    balance: chipBalance,
    chip_balance: chipBalance,
    wallet_balance: usdBalance,
    vip_tier: vipTier,
    vip_expires_at: vipExpiresAt,
  });
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());

    if (pathname === "/api/auth/me" && request.method() === "GET") {
      await route.fulfill({ status: 401, json: { detail: "Authentication required" } });
      return;
    }
    if (pathname === "/api/player/me" && request.method() === "GET") {
      await route.fulfill(playerSession
        ? { status: 200, json: { player: player() } }
        : { status: 401, json: { detail: "Player authentication required" } });
      return;
    }
    if (pathname === "/api/player/register" && request.method() === "POST") {
      playerSession = true;
      await route.fulfill({
        status: 201,
        json: { player: player() },
      });
      return;
    }
    if (pathname === "/api/player/wallet" && request.method() === "GET") {
      await route.fulfill({
        status: 200,
        json: {
          player: player(),
          wallet_balance: usdBalance,
          chip_balance: chipBalance,
          vip_tier: vipTier,
          vip_expires_at: vipExpiresAt,
          vip_discount: vipTier === "gold" ? 0.05 : 0,
          packages: [
            { chips: 100, base_price: 10 },
            { chips: 500, base_price: 50 },
            { chips: 1000, base_price: 100 },
            { chips: 5000, base_price: 500 },
          ],
          vip_plans: [
            { tier: "silver", price: 4.99, discount: 0.02 },
            { tier: "gold", price: 14.99, discount: 0.05 },
            { tier: "platinum", price: 39.99, discount: 0.08 },
            { tier: "diamond", price: 79.99, discount: 0.12 },
          ],
          transactions,
          chip_entries: chipEntries,
        },
      });
      return;
    }
    if (pathname === "/api/player/wallet/top-up" && request.method() === "POST") {
      const payload = request.postDataJSON() as { amount: string; method: string };
      usdBalance += Number(payload.amount);
      transactions.unshift({
        id: transactions.length + 1,
        type: "deposit",
        amount: Number(payload.amount),
        method: payload.method,
        origin: "player_casino_demo",
        note: "Simulated player top-up",
        created_at: new Date().toISOString(),
      });
      await route.fulfill({ status: 200, json: { player: player(), wallet_balance: usdBalance } });
      return;
    }
    if (pathname === "/api/player/chips/purchase" && request.method() === "POST") {
      const payload = request.postDataJSON() as { chips: number };
      const price = payload.chips / 10 * (1 - (vipTier === "gold" ? 0.05 : 0));
      usdBalance -= price;
      chipBalance += payload.chips;
      chipEntries.unshift({
        id: chipEntries.length + 1,
        delta: payload.chips,
        reason: "chip_purchase",
        created_at: new Date().toISOString(),
      });
      await route.fulfill({
        status: 200,
        json: { player: player(), price, chips_purchased: payload.chips },
      });
      return;
    }
    if (pathname === "/api/player/games/slots/spin" && request.method() === "POST") {
      const payload = request.postDataJSON() as { stake: number };
      const won = slotSpins++ === 0;
      const payout = won ? 20 : 0;
      chipBalance += payout - payload.stake;
      await route.fulfill({
        status: 200,
        json: {
          round: {
            id: "slots-round",
            game: "slots",
            status: "completed",
            stake: payload.stake,
            symbols: won ? ["🍒", "🍒", "🍒"] : ["🍒", "🍋", "⭐"],
            outcome: { result: won ? "win" : "loss", payout, multiplier: won ? 2 : 0 },
          },
          balance: chipBalance,
        },
      });
      return;
    }
    if (pathname === "/api/player/games/blackjack/active" && request.method() === "GET") {
      await route.fulfill({ status: 200, json: { round: null } });
      return;
    }
    if (pathname === "/api/player/games/blackjack/start" && request.method() === "POST") {
      const payload = request.postDataJSON() as { stake: number };
      await route.fulfill({
        status: 200,
        json: {
          round: {
            id: "blackjack-round",
            game: "blackjack",
            status: "completed",
            stake: payload.stake,
            dealer_hand: ["10H", "7D"],
            hands: [{ cards: ["10S", "7C"], status: "stood", stake: payload.stake }],
            current_hand: 0,
            can_split: false,
            outcome: {
              result: "push",
              payout: payload.stake,
              dealer_score: 17,
              hands: [{ result: "push", score: 17, stake: payload.stake, payout: payload.stake }],
            },
          },
          balance: chipBalance,
        },
      });
      return;
    }
    if (pathname === "/api/player/games/roulette/spin" && request.method() === "POST") {
      chipBalance += 340;
      await route.fulfill({
        status: 200,
        json: {
          round: {
            id: "roulette-round",
            game: "roulette",
            status: "completed",
            stake: 20,
            winning_number: 17,
            color: "black",
            bets: [
              { kind: "number", value: 17, amount: 10, won: true, payout: 360 },
              { kind: "color", value: "red", amount: 10, won: false, payout: 0 },
            ],
            outcome: {
              result: "win",
              payout: 360,
              winning_number: 17,
              color: "black",
              bets: [
                { kind: "number", value: 17, amount: 10, won: true, payout: 360 },
                { kind: "color", value: "red", amount: 10, won: false, payout: 0 },
              ],
            },
          },
          balance: chipBalance,
        },
      });
      return;
    }
    if (pathname === "/api/auth/login" && request.method() === "POST") {
      await route.fulfill({ status: 200, json: { admin } });
      return;
    }
    if (pathname === "/api/dashboard/metrics") {
      await route.fulfill({ status: 200, json: metrics });
      return;
    }
    if (pathname === "/api/players") {
      await route.fulfill({
        status: 200,
        json: {
          items: [{
            id: 27,
            username: "sample.player",
            email: "sample@example.test",
            country_code: "CO",
            status: "active",
            kyc_status: "verified",
            vip_tier: "gold",
            wallet_balance: "25.00",
            registered_at: "2026-10-01T12:00:00Z",
          }],
          total: 1,
          page: 1,
          page_size: 10,
        },
      });
      return;
    }
    if (pathname === "/api/chip-entries") {
      await route.fulfill({
        status: 200,
        json: {
          items: [{
            id: 1,
            player_id: 27,
            delta: 375,
            reason: "migration",
            round_id: null,
            created_at: "2026-10-24T12:00:00Z",
          }],
          total: 1,
          page: 1,
          page_size: 10,
        },
      });
      return;
    }
    await route.fulfill({ status: 404, json: { detail: "Not found" } });
  });
}

async function signIn(page: import("@playwright/test").Page) {
  await page.getByLabel("Username").fill("demo.admin");
  await page.getByLabel("Password").fill("demo-password");
  await page.locator(".auth-form").getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

test("preferences follow the system until manually changed and persist", async ({ page }) => {
  await mockApi(page);
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/login");

  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await page.getByRole("combobox", { name: "Language" }).selectOption("es");
  await expect(page.locator("html")).toHaveAttribute("lang", "es");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Te damos la bienvenida" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

  await page.getByLabel("Usuario").fill("demo.admin");
  await page.getByLabel("Contraseña").fill("demo-password");
  await page.locator(".auth-form").getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(page.getByRole("heading", { name: "Panel" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Rendimiento del período" })).toBeVisible();
});

test("mobile navigation supports Escape and reaches the player workspace", async ({ page }) => {
  await mockApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(() => {
    localStorage.setItem("casino-dashboard-locale", "en");
    localStorage.setItem("casino-dashboard-theme", "light");
  });

  await page.goto("/login");
  await signIn(page);

  const menuButton = page.locator(".menu-button");
  await menuButton.click();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeFocused();

  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("navigation", { name: "Main navigation" }).getByRole("link", { name: "Players" }).click();
  await expect(page.getByRole("heading", { name: "Players", exact: true })).toBeVisible();
  await expect(page.getByText("sample.player")).toBeVisible();
  await expect(page.getByRole("region", { name: "Table: players" })).toBeVisible();
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page
    .getByRole("navigation", { name: "Main navigation" })
    .getByRole("link", { name: "Chip ledger" })
    .click();
  await expect(page.getByRole("heading", { name: "Chip ledger", exact: true })).toBeVisible();
  await expect(page.getByText("375", { exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => ({
    viewport: window.innerWidth,
    page: document.documentElement.scrollWidth,
    offenders: [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((element) => element.getBoundingClientRect().right > window.innerWidth + 1)
      .map((element) => ({
        tag: element.tagName,
        className: element.className,
        right: Math.round(element.getBoundingClientRect().right),
        width: Math.round(element.getBoundingClientRect().width),
      }))
      .slice(0, 12),
  }));
  expect(overflow.page, JSON.stringify(overflow)).toBeLessThanOrEqual(overflow.viewport);

  const playerScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    playerScan.violations.map((violation) => ({
      rule: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
});

test("player casino lobby and age-gated registration are separate from admin login", async ({ page }) => {
  await mockApi(page);
  await page.goto("/casino");

  await expect(page.getByRole("heading", { name: "Tu próxima partida empieza aquí." })).toBeVisible();
  await page.getByRole("link", { name: "Jugar gratis" }).click();
  await expect(page.getByRole("heading", { name: "Crear cuenta" })).toBeVisible();
  const nameInput = await page.getByLabel("Nombre", { exact: true }).boundingBox();
  const registerButton = await page.getByRole("button", { name: "Crear cuenta" }).boundingBox();
  expect(nameInput?.height ?? 0).toBeGreaterThanOrEqual(44);
  expect(registerButton?.height ?? 0).toBeGreaterThanOrEqual(44);
  await page.getByLabel("Nombre", { exact: true }).fill("Demo");
  await page.getByLabel("Apellido").fill("Player");
  await page.getByLabel("Correo electrónico").fill("demo@example.test");
  await page.getByLabel("Nombre de usuario").fill("demo.player");
  await page.getByLabel("Contraseña (mínimo 12 caracteres)").fill("player-password-123");
  await page.getByLabel("Fecha de nacimiento").fill("1990-01-01");
  await page.getByLabel("País (código ISO)").fill("ES");
  await page.getByRole("checkbox", { name: "Confirmo que tengo 18 años o más." }).check();
  await page.getByRole("button", { name: "Crear cuenta" }).click();

  await expect(page.getByText("Hola, Demo")).toBeVisible();
  await expect(page.getByRole("link", { name: /FICHAS 0 VCH/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /CARTERA USD/ })).toBeVisible();
  await page.getByRole("link", { name: "Cartera", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tu cartera" })).toBeVisible();
  await expect(page.locator(".wallet-balance-label img")).toHaveCount(3);
  const amountInput = await page.getByLabel("Importe USD").boundingBox();
  expect(amountInput?.height ?? 0).toBeGreaterThanOrEqual(44);
  await page.getByLabel("Importe USD").fill("20");
  await page.getByRole("button", { name: "Simular recarga" }).click();
  await expect(page.getByRole("status")).toContainText("Recarga simulada");
  await page.getByRole("button", { name: /100 VCH/ }).click();
  await expect(page.locator(".wallet-chip-card strong")).toHaveText("100");
  await page.getByRole("link", { name: "Tragamonedas", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Lucky Lanterns" })).toBeVisible();
  const slotStakeSelect = await page.getByLabel("Apuesta").boundingBox();
  expect(slotStakeSelect?.height ?? 0).toBeGreaterThanOrEqual(44);
  await page.getByRole("button", { name: "Girar rodillos" }).click();
  await expect(page.getByRole("status")).toContainText("¡Combinación ganadora!");
  await page.getByRole("button", { name: "Girar rodillos" }).click();
  await expect(page.getByRole("status")).toContainText("Esta vez no hubo premio");
  await expect(page.locator(".slot-lever")).toBeVisible();
  await page.getByRole("link", { name: "Ruleta", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Ruleta europea" })).toBeVisible();
  const betTypeSelect = await page.getByLabel("Tipo").boundingBox();
  expect(betTypeSelect?.height ?? 0).toBeGreaterThanOrEqual(44);
  await page.getByLabel("Tipo").selectOption("number");
  await page.getByLabel("Selección").selectOption("17");
  await page.getByRole("button", { name: "Añadir a mis apuestas" }).click();
  await page.getByLabel("Tipo").selectOption("color");
  await page.getByLabel("Selección").selectOption("red");
  await page.getByRole("button", { name: "Añadir a mis apuestas" }).click();
  await expect(page.locator(".roulette-wheel-caption")).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Girar", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("17 · negro");
  await expect(page.locator(".roulette-outcome ul")).toContainText("Número 17: ganó");
  const rouletteScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    rouletteScan.violations.map((violation) => ({
      rule: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);

  await page.getByRole("link", { name: "Blackjack", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Blackjack clásico" })).toBeVisible();
  await page.getByRole("button", { name: "Repartir" }).click();
  await expect(page.getByRole("status")).toContainText("Empate: tu apuesta vuelve a ti");
  await expect(page.getByRole("img", { name: "10 de corazones" })).toBeVisible();
  const blackjackScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    blackjackScan.violations.map((violation) => ({
      rule: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
});

test("login and dashboard have no automated WCAG 2 A/AA violations", async ({ page }) => {
  await mockApi(page);
  await page.addInitScript(() => {
    localStorage.setItem("casino-dashboard-locale", "en");
    localStorage.setItem("casino-dashboard-theme", "light");
  });
  await page.goto("/login");
  const loginScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    loginScan.violations.map((violation) => ({
      rule: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);

  await signIn(page);
  const dashboardScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    dashboardScan.violations.map((violation) => ({
      rule: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);

  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  const darkDashboardScan = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(
    darkDashboardScan.violations.map((violation) => ({
      rule: violation.id,
      targets: violation.nodes.map((node) => node.target),
    })),
  ).toEqual([]);
});
