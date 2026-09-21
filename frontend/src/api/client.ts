// Thin API client. All requests go to relative /api paths — the Vite dev
// server (and nginx in production) proxies them to the backend.

import type {
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
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

export const api = {
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

  // ---- dashboard / health (Phase 7) ------------------------------------------

  dashboardSummary: (q: { machine_id?: string; model_code?: string; date_from?: string; date_to?: string } = {}) =>
    request<DashboardSummary>(`/dashboard/summary${query(q)}`),

  machineHealth: (machineId: string, windowDays = 30) =>
    request<MachineHealthMetrics>(
      `/machines/${machineId}/health${query({ window_days: windowDays })}`,
    ),

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
      xhr.send(form);
    });
  },
};
