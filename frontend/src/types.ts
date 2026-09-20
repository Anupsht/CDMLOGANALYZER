// API contract types (mirror backend/app/schemas).

export type ProcessingStatus =
  | "UPLOADED"
  | "VALIDATING"
  | "EXTRACTING"
  | "IDENTIFYING"
  | "PARSING"
  | "COMPLETED"
  | "PARTIAL"
  | "FAILED";

export interface SourceDetection {
  code: string;
  name?: string | null;
  confidence?: number | null;
  method?: string | null;
}

export interface LogFile {
  id: string;
  original_filename: string;
  stored_filename: string;
  file_type: string;
  file_role: "upload" | "extracted";
  size_bytes: number;
  checksum_sha256: string;
  mime_type?: string | null;
  status: ProcessingStatus;
  status_message?: string | null;
  parent_file_id?: string | null;
  original_path?: string | null;
  machine_id?: string | null;
  machine_model_id?: string | null;
  machine_model_code?: string | null;
  log_source?: SourceDetection | null;
  parser_code?: string | null;
  parser_version?: string | null;
  line_count?: number | null;
  duplicate_of_id?: string | null;
  created_at: string;
  updated_at: string;
  processing_started_at?: string | null;
  processing_finished_at?: string | null;
}

export interface LogFileCreateResult extends LogFile {
  is_duplicate: boolean;
}

export interface LogFileStatus {
  id: string;
  original_filename: string;
  status: ProcessingStatus;
  status_message?: string | null;
  line_count?: number | null;
  processing_started_at?: string | null;
  processing_finished_at?: string | null;
  files: LogFileStatus[];
}

export interface LogLine {
  id: number;
  log_file_id: string;
  line_number: number;
  raw_text: string;
  timestamp?: string | null;
  source?: string | null;
  level?: string | null;
  normalized_data?: Record<string, unknown> | null;
  created_at: string;
}

export interface ListResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface MachineModel {
  id?: string | null;
  code: string;
  name: string;
  vendor: string;
  description?: string | null;
  is_active: boolean;
  is_placeholder: boolean;
  supported: boolean;
  supported_sources?: string[];
  parser_code?: string | null;
  analysis_status?: string | null;
}

export interface Machine {
  id: string;
  serial_number: string;
  name?: string | null;
  machine_model_id?: string | null;
  location?: string | null;
  status: string;
  commissioned_at?: string | null;
  extra_metadata?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  machine_model?: MachineModel | null;
}

export interface Health {
  status: "ok" | "degraded";
  version: string;
  environment: string;
  database: boolean;
  queue: string;
}

export const PROCESSING_STATUSES: ProcessingStatus[] = [
  "UPLOADED",
  "VALIDATING",
  "EXTRACTING",
  "IDENTIFYING",
  "PARSING",
  "COMPLETED",
  "PARTIAL",
  "FAILED",
];

export const IN_FLIGHT_STATUSES: ProcessingStatus[] = [
  "UPLOADED",
  "VALIDATING",
  "EXTRACTING",
  "IDENTIFYING",
  "PARSING",
];
