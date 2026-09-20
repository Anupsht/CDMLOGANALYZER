import type { ProcessingStatus } from "../types";

const STYLES: Record<ProcessingStatus, string> = {
  UPLOADED: "bg-slate-700/50 text-slate-300 ring-slate-600",
  VALIDATING: "bg-sky-500/15 text-sky-300 ring-sky-500/40",
  EXTRACTING: "bg-sky-500/15 text-sky-300 ring-sky-500/40",
  IDENTIFYING: "bg-sky-500/15 text-sky-300 ring-sky-500/40",
  PARSING: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
  COMPLETED: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  PARTIAL: "bg-yellow-500/15 text-yellow-300 ring-yellow-500/40",
  FAILED: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
};

export function isProcessing(status: ProcessingStatus): boolean {
  return ["UPLOADED", "VALIDATING", "EXTRACTING", "IDENTIFYING", "PARSING"].includes(status);
}

export default function StatusBadge({ status }: { status: ProcessingStatus }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${STYLES[status]}`}
    >
      {isProcessing(status) && (
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
      )}
      {status}
    </span>
  );
}
