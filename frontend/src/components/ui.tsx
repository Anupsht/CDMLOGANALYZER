// Shared UI primitives for the technician dashboard (dark console theme).

import type { ReactNode } from "react";

export function Card({
  title,
  subtitle,
  right,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/60 ${className}`}>
      {(title || right) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-800 px-4 py-3">
          <div>
            {title && <h2 className="text-sm font-semibold text-slate-200">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

const TONES: Record<string, string> = {
  slate: "bg-slate-700/50 text-slate-300 ring-slate-600",
  emerald: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  amber: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
  rose: "bg-rose-500/15 text-rose-300 ring-rose-500/40",
  sky: "bg-sky-500/15 text-sky-300 ring-sky-500/40",
  violet: "bg-violet-500/15 text-violet-300 ring-violet-500/40",
  yellow: "bg-yellow-500/15 text-yellow-300 ring-yellow-500/40",
};

export function Badge({
  tone = "slate",
  children,
  title,
}: {
  tone?: keyof typeof TONES | string;
  children: ReactNode;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${
        TONES[tone] ?? TONES.slate
      }`}
    >
      {children}
    </span>
  );
}

export function statusTone(status: string): string {
  switch (status) {
    case "COMPLETED":
    case "STORED":
    case "OK":
      return "emerald";
    case "DECLINED":
    case "RETURNED":
      return "amber";
    case "FAILED":
    case "JAMMED":
    case "ERROR":
    case "CRITICAL":
      return "rose";
    case "INCOMPLETE":
    case "UNKNOWN":
    case "NOT_CONFIRMED":
      return "slate";
    default:
      if (status.includes("JAM") || status.includes("FAIL")) return "rose";
      if (status.includes("TIMEOUT") || status.includes("MISMATCH")) return "amber";
      return "sky";
  }
}

export const CONF_TONES: Record<string, string> = {
  LOW: "slate",
  MODERATE: "sky",
  HIGH: "amber",
  VERY_HIGH: "rose",
};

export function ConfidenceBadge({ level }: { level: string }) {
  return (
    <Badge tone={CONF_TONES[level] ?? "slate"} title="Evidence strength — never certainty">
      {level.replaceAll("_", " ")}
    </Badge>
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge tone={statusTone(severity)}>{severity}</Badge>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-700 border-t-indigo-400" />
      {label}
    </div>
  );
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="rounded-lg border border-rose-900/60 bg-rose-950/40 px-4 py-3 text-sm text-rose-300">
      {message}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center text-sm text-slate-500">{children}</div>;
}

export function Pagination({
  total,
  limit,
  offset,
  onPage,
}: {
  total: number;
  limit: number;
  offset: number;
  onPage: (offset: number) => void;
}) {
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.max(1, Math.ceil(total / limit));
  return (
    <div className="flex items-center justify-between gap-2 pt-3 text-xs text-slate-400">
      <span>
        {total === 0 ? "0" : offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-1">
        <button
          className="rounded border border-slate-700 px-2 py-1 disabled:opacity-40"
          disabled={offset <= 0}
          onClick={() => onPage(Math.max(0, offset - limit))}
        >
          ← Prev
        </button>
        <span className="px-2">
          Page {page} / {pages}
        </span>
        <button
          className="rounded border border-slate-700 px-2 py-1 disabled:opacity-40"
          disabled={offset + limit >= total}
          onClick={() => onPage(offset + limit)}
        >
          Next →
        </button>
      </div>
    </div>
  );
}

export function KV({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="mt-0.5 truncate text-sm text-slate-200" title={String(children)}>
        {children ?? <span className="text-slate-600">—</span>}
      </dd>
    </div>
  );
}

export function RawLine({ text }: { text?: string | null }) {
  if (!text) return null;
  return (
    <code className="mt-1 block break-all rounded bg-slate-950 px-2 py-1 font-mono text-[11px] text-slate-400">
      {text}
    </code>
  );
}

// ---- cash-state classification (display only — data stays verbatim) --------

export type CashClass = "STORED" | "RETURNED" | "REJECTED" | "UNKNOWN";

export function classifyCashState(state: string | null | undefined): CashClass {
  const s = (state ?? "").toUpperCase();
  if (s === "STORED") return "STORED";
  if (s === "RETURNED") return "RETURNED";
  if (s === "REJECTED" || s === "REJECT") return "REJECTED";
  return "UNKNOWN";
}

export const CASH_CLASS_TONE: Record<CashClass, string> = {
  STORED: "emerald",
  RETURNED: "amber",
  REJECTED: "rose",
  UNKNOWN: "slate",
};

export function fmtTime(ts?: string | null): string {
  if (!ts) return "—";
  return ts.replace("T", " ").slice(0, 19);
}

export function fmtAmount(amount?: number | null, currency?: string | null): string {
  if (amount === null || amount === undefined) return "—";
  return `${amount.toFixed(2)}${currency ? ` ${currency}` : ""}`;
}
