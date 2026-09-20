// Thin API client. All requests go to relative /api paths — the Vite dev
// server (and nginx in production) proxies them to the backend.

import type {
  Health,
  ListResponse,
  LogFile,
  LogFileCreateResult,
  LogFileStatus,
  LogLine,
  Machine,
  MachineModel,
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

export const api = {
  health: () => request<Health>("/health"),

  listLogs: (q: LogsQuery = {}) =>
    request<ListResponse<LogFile>>(`/logs${query(q)}`),

  getLog: (id: string) => request<LogFile>(`/logs/${id}`),

  getLogStatus: (id: string) => request<LogFileStatus>(`/logs/${id}/status`),

  getLogLines: (id: string, limit = 100, offset = 0) =>
    request<ListResponse<LogLine>>(`/logs/${id}/lines${query({ limit, offset })}`),

  // ---- models -------------------------------------------------------------

  listModels: () => request<MachineModel[]>("/models"),

  toggleModel: (code: string, enabled: boolean) =>
    request<{ model_code: string; enabled: boolean }>(
      `/models/${code}/${enabled ? "enable" : "disable"}`,
      { method: "POST" },
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
