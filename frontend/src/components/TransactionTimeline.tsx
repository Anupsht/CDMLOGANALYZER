// Phase 7 — interactive transaction timeline.
//
// Every entry is clickable: clicking expands the original log line (raw
// evidence) plus the normalized metadata, and offers a jump into the log
// viewer at that exact line. NOT_CONFIRMED stage markers are never styled
// as evidence — they explicitly carry no raw line.

import { useState } from "react";
import { Link } from "react-router-dom";
import type { TimelineEntry } from "../types";
import { Badge, RawLine, fmtTime, statusTone } from "./ui";

const KIND_ICON: Record<string, string> = {
  TRANSACTION_STARTED: "▶",
  TRANSACTION_COMPLETED: "✔",
  TRANSACTION_FAILED: "✖",
  CASH_INSERTED: "［",
  CASH_ACCEPTED: "⇥",
  CASH_STORED: "▣",
  CASH_RETURNED: "⇤",
  CASH_REJECTED: "⊘",
  CASH_ESCROWED: "▤",
  VALIDATION_PASSED: "✓",
  VALIDATION_FAILED: "✗",
  HOST_REQUEST: "⇡",
  HOST_RESPONSE: "⇣",
  HOST_DECLINED: "⇣",
  SENSOR_CHANGED: "⊸",
  MOTOR_STARTED: "⟳",
  MOTOR_STOPPED: "◎",
  GATE_COMMANDED: "⌷",
  GATE_POSITION: "⌷",
  TRANSPORT_STARTED: "→",
  TRANSPORT_STOPPED: "■",
  JAM_DETECTED: "⚠",
  JAM_CLEARED: "⟲",
  DEVICE_UNAVAILABLE: "⌫",
  ERROR: "✗",
};

function tone(entry: TimelineEntry): string {
  if (entry.not_confirmed) return "slate";
  return statusTone(entry.severity);
}

export default function TransactionTimeline({
  entries,
  stagesConfirmed,
  stagesNotConfirmed,
}: {
  entries: TimelineEntry[];
  stagesConfirmed: string[];
  stagesNotConfirmed: string[];
}) {
  const [openIdx, setOpenIdx] = useState<number | null>(null);

  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-1.5 text-[11px]">
        {stagesConfirmed.map((s) => (
          <Badge key={s} tone="emerald">{s}</Badge>
        ))}
        {stagesNotConfirmed.map((s) => (
          <Badge key={s} tone="slate" title="Stage without a confirming event — never invented">
            {s} · not confirmed
          </Badge>
        ))}
      </div>

      <ol className="relative space-y-1 border-l border-slate-800 pl-4">
        {entries.map((e, idx) => {
          const raw = e.raw;
          const clickable = !e.not_confirmed && !!raw?.raw_text;
          const open = openIdx === idx;
          return (
            <li key={idx} className="relative">
              <span
                className={`absolute -left-[21px] top-2 h-2 w-2 rounded-full ${
                  e.not_confirmed ? "bg-slate-700" : e.severity === "ERROR" || e.severity === "CRITICAL" ? "bg-rose-500" : e.severity === "WARNING" ? "bg-amber-500" : "bg-indigo-500"
                }`}
              />
              <button
                disabled={!clickable}
                onClick={() => setOpenIdx(open ? null : idx)}
                className={`flex w-full items-start gap-2 rounded px-2 py-1.5 text-left text-sm ${
                  clickable ? "cursor-pointer hover:bg-slate-800/50" : "cursor-default opacity-70"
                } ${open ? "bg-slate-800/50" : ""}`}
              >
                <span className="w-4 shrink-0 text-center text-xs text-slate-500">
                  {KIND_ICON[e.event] ?? "•"}
                </span>
                <span className="w-36 shrink-0 font-mono text-[11px] text-slate-500">
                  {fmtTime(e.timestamp)}
                </span>
                <span className="min-w-0 shrink-0">
                  <Badge tone={tone(e)}>
                    {e.event.replaceAll("_", " ")}
                    {e.not_confirmed ? " · not confirmed" : ""}
                  </Badge>
                </span>
                {e.device && <span className="shrink-0 text-xs text-slate-500">{e.device}</span>}
                {e.source && <span className="shrink-0 text-[11px] uppercase text-slate-600">{e.source}</span>}
                {clickable && (
                  <span className="ml-auto shrink-0 text-[11px] text-indigo-400/70">
                    {open ? "hide log line ▲" : "log line ▼"}
                  </span>
                )}
              </button>

              {open && clickable && (
                <div className="mb-2 ml-6 rounded-lg border border-slate-800 bg-slate-950/80 p-3">
                  <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
                    <span>
                      evidence: <span className="text-slate-300">{raw?.file_id?.slice(0, 8)}…</span>
                      {" · line "}
                      <span className="text-slate-300">{raw?.line_number}</span>
                    </span>
                    {raw?.file_id && raw?.line_number != null && (
                      <Link
                        className="text-indigo-400 hover:underline"
                        to={`/logs/${raw.file_id}?line=${raw.line_number}`}
                      >
                        open in log viewer ↗
                      </Link>
                    )}
                  </div>
                  <RawLine text={raw?.raw_text} />
                  {e.detail != null && (
                    <pre className="mt-2 overflow-x-auto font-mono text-[11px] text-slate-500">
                      {JSON.stringify(e.detail, null, 1)}
                    </pre>
                  )}
                </div>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
