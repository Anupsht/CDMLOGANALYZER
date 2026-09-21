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

// ---------------------------------------------------------------------------
// Phase 7 — technician dashboard types (mirror backend/app/schemas)
// ---------------------------------------------------------------------------

export interface Transaction {
  id: string;
  transaction_id: string;
  machine_id?: string | null;
  machine_model_id?: string | null;
  model_code?: string | null;
  start_time?: string | null;
  end_time?: string | null;
  amount?: number | null;
  currency?: string | null;
  status: string;
  correlation_confidence: number;
  correlation_method?: string | null;
  source_file_id?: string | null;
  created_at: string;
}

export interface TransactionDetail extends Transaction {
  stages_confirmed: string[];
  complete: boolean;
}

export interface RawEvidence {
  file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
}

export interface TimelineEntry {
  timestamp?: string | null;
  event: string;
  stage?: string | null;
  device?: string | null;
  severity: string;
  source?: string | null;
  detail?: Record<string, unknown> | unknown[] | null;
  not_confirmed?: boolean;
  raw?: RawEvidence | null;
}

export interface TimelineOut {
  transaction: Transaction;
  entries: TimelineEntry[];
  not_confirmed_stages: TimelineEntry[];
  stages_confirmed: string[];
  stages_not_confirmed: string[];
  complete: boolean;
}

export interface EvidenceRef {
  file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
}

export interface CashMovement {
  note_id?: string | null;
  from_state: string;
  to_state: string;
  timestamp?: string | null;
  device?: string | null;
  evidence_event: string;
  confidence: number;
  note_info?: Record<string, unknown> | null;
  log_file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
}

export interface SensorEvent {
  sensor: string;
  previous_state?: string | null;
  new_state?: string | null;
  timestamp?: string | null;
  expected_state?: string | null;
  actual_state?: string | null;
  abnormal_duration_ms?: number | null;
  device?: string | null;
  log_file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
  detail?: Record<string, unknown> | null;
}

export interface MotorEvent {
  motor: string;
  started_at?: string | null;
  stopped_at?: string | null;
  duration_ms?: number | null;
  timeout_ms?: number | null;
  timed_out: boolean;
  transport_name?: string | null;
  sensor_transitions?: unknown[] | null;
  device?: string | null;
  log_file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
  stop_line_number?: number | null;
  stop_raw_text?: string | null;
}

export interface GateEvent {
  kind: string;
  name: string;
  command?: string | null;
  expected_state?: string | null;
  actual_state?: string | null;
  transition_ms?: number | null;
  timeout_ms?: number | null;
  timed_out: boolean;
  state_mismatch: boolean;
  device?: string | null;
  log_file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
  position_evidence?: Record<string, unknown> | null;
}

export interface TransportEvent {
  name: string;
  started_at?: string | null;
  ended_at?: string | null;
  outcome: string;
  timeout_ms?: number | null;
  detail?: Record<string, unknown> | null;
  device?: string | null;
  log_file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
}

export interface FaultAssessment {
  subject_kind: string;
  subject_name?: string | null;
  classification: string;
  statement: string;
  evidence?: EvidenceRef[] | null;
  analysis_window?: Record<string, unknown> | null;
  assessed_at?: string | null;
}

export interface HwTimelineEntry {
  timestamp?: string | null;
  kind: string;
  name?: string | null;
  event: string;
  device?: string | null;
  severity: string;
  detail?: Record<string, unknown> | unknown[] | null;
  raw?: EvidenceRef | null;
}

export interface HardwareTimeline {
  transaction: Transaction;
  final_cash_state: string;
  cash_movements: CashMovement[];
  sensor_events: SensorEvent[];
  motor_events: MotorEvent[];
  gate_events: GateEvent[];
  shutter_events: GateEvent[];
  transport_events: TransportEvent[];
  faults: FaultAssessment[];
  timeline: HwTimelineEntry[];
  extras?: Record<string, unknown> | null;
}

export interface FindingEvidence {
  kind: string;
  event?: string | null;
  timestamp?: string | null;
  device?: string | null;
  file_id?: string | null;
  line_number?: number | null;
  raw_text?: string | null;
  transition?: string | null;
  sensor?: string | null;
  motor?: string | null;
  name?: string | null;
  outcome?: string | null;
  classification?: string | null;
  issue?: string | null;
  statement?: string | null;
  detail?: Record<string, unknown> | null;
}

export interface Finding {
  finding_id: string;
  rule_id: string;
  diagnosis_class: string;
  category?: string | null;
  severity: string;
  confidence: string;
  summary: string;
  interpretation: string;
  possible_causes?: unknown[] | null;
  recommended_action?: string | null;
  evidence?: FindingEvidence[] | null;
  cash_states?: string[] | null;
}

export interface DiagnosticReport {
  transaction: Transaction;
  summary: string;
  classification: string;
  diagnosis_class: string;
  severity: string;
  confidence: string;
  final_cash_state?: string | null;
  findings: Finding[];
}

export interface FleetStatus {
  total: number;
  online: number;
  offline: number;
  window_hours: number;
  note: string;
}

export interface TransactionCounts {
  total: number;
  completed: number;
  declined: number;
  failed: number;
  incomplete: number;
}

export interface FindingCounts {
  hardware_errors: number;
  possible_jams: number;
  confirmed_jams: number;
  cash_exceptions: number;
  host_failures: number;
}

export interface ModelBreakdownEntry {
  model_code: string;
  transactions: number;
  completed: number;
  failed: number;
  declined: number;
  incomplete: number;
}

export interface DashboardSummary {
  generated_at: string;
  window_start?: string | null;
  window_end?: string | null;
  fleet: FleetStatus;
  transactions: TransactionCounts;
  findings: FindingCounts;
  models: ModelBreakdownEntry[];
}

export interface MachineHealthMetrics {
  machine_id: string;
  serial_number: string;
  name?: string | null;
  model_code?: string | null;
  location?: string | null;
  status: string;
  window_days: number;
  window_start?: string | null;
  transactions_total: number;
  completed: number;
  declined: number;
  failed: number;
  incomplete: number;
  failure_rate: number;
  jam_transactions: number;
  jam_frequency: number;
  hardware_error_transactions: number;
  sensor_abnormalities: number;
  device_unavailable_events: number;
  recovery_reset_events: number;
  last_activity_at?: string | null;
  note: string;
}

// ---------------------------------------------------------------------------
// Phase 8 — AI explanation & vendor reporting
// ---------------------------------------------------------------------------

export type EpistemicLabel = "CONFIRMED" | "PROBABLE" | "POSSIBLE" | "UNKNOWN";

export interface ExplanationClaim {
  statement: string;
  label: EpistemicLabel;
  evidence_ids: string[];
}

export interface AIExplanationPayload {
  technical_summary: string;
  root_cause: ExplanationClaim & { basis?: string };
  confidence: { label: EpistemicLabel; rationale: string };
  possible_causes: ExplanationClaim[];
  recommended_actions: string[];
  vendor_questions: string[];
  evidence: { id: string; file: string; file_id?: string | null; line_number: number; raw_excerpt: string }[];
  caveats: string[];
  labels: {
    vocabulary: EpistemicLabel[];
    legend: Record<EpistemicLabel, string>;
  };
}

export interface AIExplanation {
  id: string;
  transaction_id: string;
  provider: string;
  generator: string;
  model_name?: string | null;
  digest_sha256: string;
  created_at?: string | null;
  payload: AIExplanationPayload;
  safety_notes?: string[] | null;
}

export const LABEL_TONE: Record<EpistemicLabel, string> = {
  CONFIRMED: "rose",
  PROBABLE: "amber",
  POSSIBLE: "sky",
  UNKNOWN: "slate",
};
