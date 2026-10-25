export type Admin = {
  id: number;
  email: string;
  full_name: string;
  role: "super_admin" | "support" | string;
};

export type PageResult<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
};

export type DashboardDailyMetrics = {
  date: string;
  ggr: string;
  deposits: string;
  withdrawals: string;
};

export type DashboardDistributionItem = {
  key: string;
  label: string;
  count: number;
  percentage: number;
};

export type DashboardMonthlyGGR = {
  month: string;
  label: string;
  ggr: string;
};

export type DashboardHeatmapCell = {
  weekday: number;
  hour: number;
  bets_count: number;
};

export type DashboardMetrics = {
  start_date: string;
  end_date: string;
  ggr: string;
  deposits: string;
  withdrawals: string;
  active_players: number;
  bets_count: number;
  daily: DashboardDailyMetrics[];
  registration_channel_period: string;
  registration_channels: DashboardDistributionItem[];
  vip_tiers: DashboardDistributionItem[];
  age_bands: DashboardDistributionItem[];
  all_time_ggr: string;
  monthly_ggr: DashboardMonthlyGGR[];
  bet_heatmap: DashboardHeatmapCell[];
};

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body: { detail?: string | { msg?: string }[] } = await response.json();
      if (typeof body.detail === "string") {
        message = body.detail;
      } else if (Array.isArray(body.detail)) {
        message = body.detail.map((item) => item.msg ?? "Invalid request").join("; ");
      }
    } catch {
      if (response.statusText) message = response.statusText;
    }
    throw new ApiError(response.status, message);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body: { detail?: string } = await response.json();
      if (body.detail) message = body.detail;
    } catch {
      if (response.statusText) message = response.statusText;
    }
    throw new ApiError(response.status, message);
  }

  const disposition = response.headers.get("Content-Disposition");
  const filename = disposition?.match(/filename="([^"]+)"/i)?.[1] ?? "export.csv";
  return { blob: await response.blob(), filename };
}
