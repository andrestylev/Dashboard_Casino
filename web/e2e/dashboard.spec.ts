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
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());

    if (pathname === "/api/auth/me" && request.method() === "GET") {
      await route.fulfill({ status: 401, json: { detail: "Authentication required" } });
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
