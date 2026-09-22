// Thin API client. All requests go to relative /api paths — the Vite dev
// server (and nginx in production) proxies them to the backend.

import type {
  AuditEntry,
  CaseItem,
  UserAccount,
  AIExplanation,
  AnalyticsOverview,
  CrossMachineOut,
  ErrorStat,
  InsightsOut,
  MaintenanceOut,
  PatternDetection,
  RuleSuggestion,
  TrendsOut,
  DashboardSummary,
  DiagnosticReport,
  HardwareTimeline,
  Health,
  ListResponse,
  LogFile,
  LogFileCreateResult,
  LogFileStatus,
  LogLine,
  Machine,
  MachineHealthMetrics,
  MachineModel,
  TimelineOut,
  Transaction,
  TransactionDetail,
} from "../types";

const BASE = "/api";

export class ApiError extends Error {
  code: string;
  requestId: string;
  status: number;

  constructor(status: number, code: string, message: string, requestId: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

function authToken(): string | null {
  try {
    return localStorage.getItem("cdm_token");
  } catch {
    return null;
  }
}

function withAuth(init?: RequestInit): RequestInit {
  const token = authToken();
  const base: RequestInit = init ?? {};
  if (!token) return base;
  return {
    ...base,
    headers: { ...(base.headers ?? {}), Authorization: `Bearer ${token}` },
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, withAuth(init));
  if (response.status === 401 && !path.startsWith("/auth/login")) {
    // Session expired/revoked: drop local state and show the login page.
    try {
      localStorage.removeItem("cdm_token");
      localStorage.removeItem("cdm_user");
    } catch { /* ignore */ }
    if (!window.location.pathname.startsWith("/login")) {
      window.location.assign("/login");
    }
  }
  if (!response.ok) {
    let code = `http_${response.status}`;
    let message = response.statusText || "Request failed";
    let requestId = "";
    try {
      const body = await response.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
      requestId = body?.request_id ?? "";
    } catch {
      /* non-JSON error body — keep defaults */
    }
    throw new ApiError(response.status, code, message, requestId);
  }
  return response.json() as Promise<T>;
}

// ---- logs ------------------------------------------------------------------

export interface LogsQuery {
  status?: string;
  source?: string;
  machine_id?: string;
  file_role?: string;
  limit?: number;
  offset?: number;
}

function query(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

export interface TransactionsQuery {
  model_code?: string;
  machine_id?: string;
  status?: string;
  transaction_id?: string;
  date_from?: string;
  date_to?: string;
  time_from?: string;
  time_to?: string;
  amount_min?: number | string;
  amount_max?: number | string;
  currency?: string;
  host_result?: string;
  cash_state?: string;
  event_code?: string;
  device?: string;
  error_code?: string;
  sort?: string;
  dir?: string;
  limit?: number;
  offset?: number;
}

export interface LogLinesQuery {
  q?: string;
  level?: string;
  line_from?: number;
  line_to?: number;
  ts_from?: string;
  ts_to?: string;
  limit?: number;
  offset?: number;
}

// ---- Phase 10: auth / cases / users / audit ---------------------------------

export interface LoginResponse {
  token: string;
  token_type: string;
  expires_at: string;
  user: UserAccount;
}

export const api = {
  login: (username: string, password: string) =>
    request<LoginResponse>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),

  logout: () => request<void>("/auth/logout", { method: "POST" }),

  me: () => request<UserAccount>("/auth/me"),

  changePassword: (oldPassword: string, newPassword: string) =>
    request<void>("/auth/change-password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old_password: oldPassword, new_password: newPassword }),
    }),

  listUsers: () => request<UserAccount[]>("/auth/users"),

  createUser: (payload: { username: string; password: string; role: string; full_name?: string }) =>
    request<UserAccount>("/auth/users", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateUser: (id: string, payload: { role?: string; is_active?: boolean }) =>
    request<UserAccount>(`/auth/users/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  resetUserPassword: (id: string, newPassword: string) =>
    request<void>(`/auth/users/${id}/reset-password`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ new_password: newPassword }),
    }),

  listCases: (params?: { status?: string }) =>
    request<CaseItem[]>(`/cases${query(params ?? {})}`),

  createCase: (payload: {
    title: string;
    description?: string;
    priority?: string;
    machine_id?: string;
    transaction_ref?: string;
  }) =>
    request<CaseItem>("/cases", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateCase: (id: string, payload: { status?: string; priority?: string; title?: string }) =>
    request<CaseItem>(`/cases/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listAudit: (params?: { action?: string; actor?: string; result?: string; limit?: number }) =>
    request<AuditEntry[]>(`/audit${query(params ?? {})}`),
  health: () => request<Health>("/health"),

  listLogs: (q: LogsQuery = {}) =>
    request<ListResponse<LogFile>>(`/logs${query(q)}`),

  getLog: (id: string) => request<LogFile>(`/logs/${id}`),

  getLogStatus: (id: string) => request<LogFileStatus>(`/logs/${id}/status`),

  getLogLines: (id: string, q: LogLinesQuery = {}) =>
    request<ListResponse<LogLine>>(`/logs/${id}/lines${query(q)}`),

  // ---- models -------------------------------------------------------------

  listModels: () => request<MachineModel[]>("/models"),

  toggleModel: (code: string, enabled: boolean) =>
    request<{ model_code: string; enabled: boolean }>(
      `/models/${code}/${enabled ? "enable" : "disable"}`,
      { method: "POST" },
    ),

  // ---- transactions (universal — every model) -------------------------------

  listTransactions: (q: TransactionsQuery = {}) =>
    request<ListResponse<Transaction>>(`/transactions${query(q)}`),

  getTransaction: (id: string) => request<TransactionDetail>(`/transactions/${id}`),

  getTransactionTimeline: (id: string) => request<TimelineOut>(`/transactions/${id}/timeline`),

  getTransactionHardware: (id: string) => request<HardwareTimeline>(`/transactions/${id}/hardware`),

  getTransactionDiagnostics: (id: string) =>
    request<DiagnosticReport>(`/transactions/${id}/diagnostics`),

  // ---- AI explanation & vendor reporting (Phase 8) ---------------------------

  getAIExplanation: (id: string) =>
    request<AIExplanation>(`/transactions/${id}/ai-explanation`),

  generateAIExplanation: (id: string) =>
    request<AIExplanation>(`/transactions/${id}/ai-explanation`, { method: "POST" }),

  reportPdfUrl: (id: string) => `${BASE}/transactions/${id}/report.pdf`,

  reportXlsxUrl: (id: string) => `${BASE}/transactions/${id}/report.xlsx`,

  // ---- dashboard / health (Phase 7) ------------------------------------------

  dashboardSummary: (q: { machine_id?: string; model_code?: string; date_from?: string; date_to?: string } = {}) =>
    request<DashboardSummary>(`/dashboard/summary${query(q)}`),

  machineHealth: (machineId: string, windowDays = 30) =>
    request<MachineHealthMetrics>(
      `/machines/${machineId}/health${query({ window_days: windowDays })}`,
    ),

  // ---- analytics (Phase 9) ---------------------------------------------------

  analyticsOverview: (windowDays = 90) =>
    request<AnalyticsOverview>(`/analytics/overview${query({ window_days: windowDays })}`),

  analyticsTrends: (bucket: string, windowDays = 90) =>
    request<TrendsOut>(`/analytics/trends${query({ bucket, window_days: windowDays })}`),

  analyticsErrors: (windowDays = 90) =>
    request<{ window_days: number; errors: ErrorStat[]; note: string }>(
      `/analytics/errors${query({ window_days: windowDays })}`,
    ),

  analyticsPatterns: (windowDays = 90) =>
    request<{ window_days: number; patterns: PatternDetection[]; note: string }>(
      `/analytics/patterns${query({ window_days: windowDays })}`,
    ),

  analyticsCrossMachine: (windowDays = 90) =>
    request<CrossMachineOut>(`/analytics/cross-machine${query({ window_days: windowDays })}`),

  analyticsMaintenance: (recentDays = 7, baselineDays = 30) =>
    request<MaintenanceOut>(
      `/analytics/maintenance${query({ recent_days: recentDays, baseline_days: baselineDays })}`,
    ),

  analyticsInsights: (windowDays = 90) =>
    request<InsightsOut>(`/analytics/insights${query({ window_days: windowDays })}`),

  listRuleSuggestions: (status?: string) =>
    request<RuleSuggestion[]>(`/analytics/rule-suggestions${query({ status })}`),

  createRuleSuggestion: (payload: {
    title: string;
    pattern_type: string;
    rationale?: string;
    pattern_stats?: Record<string, unknown>;
    draft_rule?: Record<string, unknown>;
  }) =>
    request<RuleSuggestion>("/analytics/rule-suggestions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  reviewRuleSuggestion: (
    id: string,
    payload: { status: string; reviewed_by?: string; review_note?: string },
  ) =>
    request<RuleSuggestion>(`/analytics/rule-suggestions/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // ---- machines -------------------------------------------------------------

  listMachines: (limit = 200, offset = 0) =>
    request<ListResponse<Machine>>(`/machines${query({ limit, offset })}`),

  createMachine: (payload: {
    serial_number: string;
    model_code?: string;
    name?: string;
    location?: string;
    status?: string;
  }) =>
    request<Machine>("/machines", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  // ---- upload (XHR so we get progress events) --------------------------------

  uploadLog(
    file: File,
    options: { machineId?: string; modelCode?: string; onProgress?: (pct: number) => void },
  ): Promise<LogFileCreateResult> {
    return new Promise((resolve, reject) => {
      const form = new FormData();
      form.append("file", file);
      if (options.machineId) form.append("machine_id", options.machineId);
      if (options.modelCode) form.append("model_code", options.modelCode);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/logs/upload`);
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && options.onProgress) {
          options.onProgress(Math.round((event.loaded / event.total) * 100));
        }
      };
      xhr.onload = () => {
        try {
          const body = JSON.parse(xhr.responseText);
          if (xhr.status >= 200 && xhr.status < 300) {
            resolve(body as LogFileCreateResult);
          } else {
            reject(
              new ApiError(
                xhr.status,
                body?.error?.code ?? `http_${xhr.status}`,
                body?.error?.message ?? "Upload failed",
                body?.request_id ?? "",
              ),
            );
          }
        } catch {
          reject(new ApiError(xhr.status, "bad_response", "Upload failed", ""));
        }
      };
      xhr.onerror = () => reject(new ApiError(0, "network_error", "Network error during upload", ""));
      const token = authToken();
      if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      xhr.send(form);
    });
  },
};
