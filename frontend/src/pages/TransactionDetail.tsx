// Phase 7 — transaction details: summary, cash/host/hardware summaries,
// interactive timeline, cash trace, errors, sensors, motors, analysis,
// evidence and recommendations — all from the universal endpoints.

import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type {
  DiagnosticReport,
  Finding,
  HardwareTimeline,
  TimelineEntry,
  TimelineOut,
  TransactionDetail as TxnDetail,
} from "../types";
import TransactionTimeline from "../components/TransactionTimeline";
import CashTrace from "../components/CashTrace";
import VendorReportSection from "../components/VendorReportSection";
import {
  Badge,
  CASH_CLASS_TONE,
  Card,
  ConfidenceBadge,
  Empty,
  ErrorBox,
  KV,
  RawLine,
  SeverityBadge,
  Spinner,
  classifyCashState,
  fmtAmount,
  fmtTime,
  statusTone,
} from "../components/ui";

const SECTIONS = [
  ["overview", "Transaction Summary"],
  ["cash", "Cash Summary"],
  ["host", "Host Summary"],
  ["hardware", "Hardware Summary"],
  ["timeline", "Timeline"],
  ["trace", "Cash Trace"],
  ["errors", "Errors"],
  ["sensors", "Sensors"],
  ["motors", "Motors"],
  ["analysis", "Analysis"],
  ["evidence", "Evidence"],
  ["recommendations", "Recommendations"],
  ["vendor", "Vendor Report"],
] as const;

interface AllData {
  detail: TxnDetail;
  timeline: TimelineOut;
  hw: HardwareTimeline;
  report: DiagnosticReport;
}

export default function TransactionDetail() {
  const { txnId = "" } = useParams();
  const [data, setData] = useState<AllData | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<string>("overview");

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError("");
    Promise.all([
      api.getTransaction(txnId),
      api.getTransactionTimeline(txnId),
      api.getTransactionHardware(txnId),
      api.getTransactionDiagnostics(txnId),
    ])
      .then(([detail, timeline, hw, report]) => {
        if (!cancelled) setData({ detail, timeline, hw, report });
      })
      .catch((e) => !cancelled && setError(e.message ?? String(e)));
    return () => {
      cancelled = true;
    };
  }, [txnId]);

  if (error) return <div className="mx-auto max-w-[1200px] px-6 py-6"><ErrorBox message={error} /></div>;
  if (!data) return <Spinner label="Loading transaction analysis…" />;

  const { detail, timeline, hw, report } = data;

  const exportJson = () => {
    const blob = new Blob([JSON.stringify({ transaction: detail, timeline, hardware: hw, diagnostics: report }, null, 2)], {
      type: "application/json",
    });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `report_${detail.transaction_id}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-6">
      {/* Header */}
      <header className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-mono text-xl font-semibold text-white">{detail.transaction_id}</h1>
            <Badge tone={statusTone(detail.status)}>{detail.status}</Badge>
            <Badge tone="violet">{detail.model_code ?? "UNKNOWN MODEL"}</Badge>
            {report.classification !== "NORMAL_COMPLETION" && (
              <Badge tone={statusTone(report.classification)}>{report.classification}</Badge>
            )}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            {report.summary}{" "}
            <span className="text-slate-600">
              (class: {report.diagnosis_class}, confidence: {report.confidence} — evidence
              strength, not certainty)
            </span>
          </p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button onClick={exportJson} className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
            Export report (JSON)
          </button>
          <button onClick={() => window.print()} className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
            Print
          </button>
        </div>
      </header>

      {/* Section nav */}
      <nav className="sticky top-0 z-10 -mx-6 mb-4 flex gap-1 overflow-x-auto border-b border-slate-800 bg-slate-950/95 px-6 py-2 backdrop-blur print:hidden">
        {SECTIONS.map(([id, label]) => (
          <button
            key={id}
            onClick={() => {
              setTab(id);
              document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
            }}
            className={`whitespace-nowrap rounded px-2.5 py-1 text-xs ${
              tab === id ? "bg-indigo-600/20 text-indigo-300" : "text-slate-400 hover:bg-slate-800/60"
            }`}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="grid gap-4">
        {/* 1. Transaction Summary */}
        <section id="sec-overview" className="scroll-mt-14">
          <Card title="Transaction Summary">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4 xl:grid-cols-6">
              <KV label="Transaction ID">{detail.transaction_id}</KV>
              <KV label="Model">{detail.model_code ?? "—"}</KV>
              <KV label="Machine">
                {detail.machine_id ? (
                  <Link className="text-indigo-400 hover:underline" to="/health" title={detail.machine_id}>
                    machine
                  </Link>
                ) : (
                  "—"
                )}
              </KV>
              <KV label="Status">{detail.status}</KV>
              <KV label="Amount">{fmtAmount(detail.amount, detail.currency)}</KV>
              <KV label="Started">{fmtTime(detail.start_time)}</KV>
              <KV label="Ended">{fmtTime(detail.end_time)}</KV>
              <KV label="Correlation">
                {(detail.correlation_confidence * 100).toFixed(0)}% · {detail.correlation_method ?? "—"}
              </KV>
              <KV label="Lifecycle complete">{detail.complete ? "yes" : "no"}</KV>
              <KV label="Imported">{fmtTime(detail.created_at)}</KV>
            </dl>
          </Card>
        </section>

        <div className="grid gap-4 xl:grid-cols-2">
          {/* 2. Cash Summary */}
          <section id="sec-cash" className="scroll-mt-14">
            <Card title="Cash Summary">
              <div className="mb-3 flex items-center gap-2 text-sm text-slate-300">
                Final cash state:
                <Badge tone={CASH_CLASS_TONE[classifyCashState(hw.final_cash_state)]}>
                  {hw.final_cash_state || "UNKNOWN"}
                </Badge>
                <span className="text-xs text-slate-500">
                  {hw.cash_movements.length} movement{hw.cash_movements.length === 1 ? "" : "s"}
                </span>
              </div>
              {hw.cash_movements.length > 0 ? (
                <ol className="flex flex-wrap items-center gap-1.5 text-xs">
                  {hw.cash_movements.map((m, i) => (
                    <li key={i} className="flex items-center gap-1.5">
                      <span className="font-mono text-slate-400">{m.from_state}</span>
                      <span className="text-slate-600">→</span>
                      <Badge tone={CASH_CLASS_TONE[classifyCashState(m.to_state)]}>{m.to_state}</Badge>
                      {i < hw.cash_movements.length - 1 && <span className="ml-1 text-slate-700">·</span>}
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="text-xs text-slate-500">No cash movement events recorded.</p>
              )}
              <p className="mt-3 text-[11px] text-slate-600">
                States are verbatim from the logs; the colour class (STORED / RETURNED /
                REJECTED / UNKNOWN) is a display grouping in the Cash Trace below.
              </p>
            </Card>
          </section>

          {/* 3. Host Summary */}
          <section id="sec-host" className="scroll-mt-14">
            <Card title="Host Summary">
              <HostSummary timeline={timeline.entries} />
            </Card>
          </section>

          {/* 4. Hardware Summary */}
          <section id="sec-hardware" className="scroll-mt-14 xl:col-span-2">
            <Card
              title="Hardware Summary"
              subtitle="Fault classifications require multi-source evidence — a single error code never equals a confirmed jam"
            >
              {hw.faults.length === 0 ? (
                <Empty>No hardware faults assessed for this transaction.</Empty>
              ) : (
                <ul className="space-y-2">
                  {hw.faults.map((f, i) => (
                    <li key={i} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                      <div className="flex flex-wrap items-center gap-2 text-sm">
                        <Badge tone={statusTone(f.classification)}>{f.classification}</Badge>
                        <span className="text-xs text-slate-500">
                          {f.subject_kind}
                          {f.subject_name ? ` · ${f.subject_name}` : ""}
                        </span>
                      </div>
                      <p className="mt-1.5 text-sm text-slate-300">{f.statement}</p>
                      {f.evidence && f.evidence.length > 0 && (
                        <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-indigo-400">
                          {f.evidence.map((ev, j) =>
                            ev.file_id && ev.line_number != null ? (
                              <Link key={j} className="hover:underline" to={`/logs/${ev.file_id}?line=${ev.line_number}`}>
                                line {ev.line_number} ↗
                              </Link>
                            ) : null,
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-slate-400 md:grid-cols-4">
                <span>{hw.sensor_events.length} sensor events</span>
                <span>{hw.motor_events.length} motor events</span>
                <span>{hw.gate_events.length + hw.shutter_events.length} gate/shutter events</span>
                <span>{hw.transport_events.length} transport runs</span>
              </div>
            </Card>
          </section>
        </div>

        {/* 5. Timeline */}
        <section id="sec-timeline" className="scroll-mt-14">
          <Card
            title="Timeline"
            subtitle="Click an event to see the original log line — normalized entries never replace the raw evidence"
          >
            <TransactionTimeline
              entries={timeline.entries}
              stagesConfirmed={timeline.stages_confirmed}
              stagesNotConfirmed={timeline.stages_not_confirmed}
            />
          </Card>
        </section>

        {/* 6. Cash Trace */}
        <section id="sec-trace" className="scroll-mt-14">
          <Card title="Cash Trace" subtitle="Per-note movement with explicit final-state classification">
            <CashTrace movements={hw.cash_movements} finalCashState={hw.final_cash_state} />
          </Card>
        </section>

        <div className="grid gap-4 xl:grid-cols-2">
          {/* 7. Errors */}
          <section id="sec-errors" className="scroll-mt-14">
            <Card title="Errors">
              <ErrorList entries={timeline.entries} />
            </Card>
          </section>

          {/* 8. Sensors */}
          <section id="sec-sensors" className="scroll-mt-14">
            <Card title="Sensors">
              <SensorTable hw={hw} />
            </Card>
          </section>

          {/* 9. Motors */}
          <section id="sec-motors" className="scroll-mt-14">
            <Card title="Motors">
              <MotorTable hw={hw} />
            </Card>
          </section>

          {/* 10. Analysis */}
          <section id="sec-analysis" className="scroll-mt-14">
            <Card
              title="Analysis"
              subtitle="Data-driven rules on the evidence picture — findings are interpretations with confidence levels, never certainties"
            >
              <div className="mb-3 flex flex-wrap items-center gap-2 text-sm">
                <Badge tone={statusTone(report.classification)}>{report.classification}</Badge>
                <Badge tone="violet">{report.diagnosis_class}</Badge>
                <SeverityBadge severity={report.severity} />
                <ConfidenceBadge level={report.confidence} />
              </div>
              <p className="text-sm text-slate-300">{report.summary}</p>
              <div className="mt-3 space-y-3">
                {report.findings.map((f) => (
                  <FindingCard key={f.finding_id} f={f} />
                ))}
              </div>
            </Card>
          </section>
        </div>

        {/* 11. Evidence */}
        <section id="sec-evidence" className="scroll-mt-14">
          <Card
            title="Evidence"
            subtitle="Every raw log line this analysis rests on — each entry opens at the exact file + line"
          >
            <EvidenceList timeline={timeline.entries} hw={hw} report={report} />
          </Card>
        </section>

        {/* 12. Recommendations */}
        <section id="sec-recommendations" className="scroll-mt-14">
          <Card
            title="Recommendations"
            subtitle="Configured actions attached to triggered rules — operational hints, not prescriptions"
          >
            <Recommendations report={report} />
          </Card>
        </section>

        {/* 13. Vendor Report & Export (Phase 8) */}
        <section id="sec-vendor" className="scroll-mt-14">
          <VendorReportSection detail={detail} hw={hw} report={report} />
        </section>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- sub-blocks

function HostSummary({ timeline }: { timeline: TimelineEntry[] }) {
  const host = timeline.filter(
    (e) =>
      e.event.startsWith("HOST") ||
      (e.stage === "host_request" || e.stage === "host_response"),
  );
  if (host.length === 0) {
    return <Empty>No host communication events recorded.</Empty>;
  }
  return (
    <ul className="space-y-2">
      {host.map((e, i) => (
        <li key={i} className="rounded-lg border border-slate-800 bg-slate-950/50 p-2.5 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={statusTone(e.severity)}>{e.event.replaceAll("_", " ")}</Badge>
            <span className="font-mono text-[11px] text-slate-500">{fmtTime(e.timestamp)}</span>
          </div>
          <RawLine text={e.raw?.raw_text} />
        </li>
      ))}
    </ul>
  );
}

function ErrorList({ entries }: { entries: TimelineEntry[] }) {
  const errors = entries.filter(
    (e) => e.severity === "ERROR" || e.severity === "CRITICAL" || e.event === "ERROR" || e.event === "VALIDATION_FAILED",
  );
  if (errors.length === 0) return <Empty>No error-severity events in this transaction.</Empty>;
  return (
    <ul className="space-y-2">
      {errors.map((e, i) => {
        const detail = (e.detail ?? {}) as Record<string, unknown>;
        return (
          <li key={i} className="rounded-lg border border-slate-800 bg-slate-950/50 p-2.5">
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <SeverityBadge severity={e.severity} />
              <span className="text-slate-300">{e.event.replaceAll("_", " ")}</span>
              {typeof detail.error_code === "string" && (
                <Badge tone="rose">{detail.error_code}</Badge>
              )}
              <span className="font-mono text-[11px] text-slate-500">{fmtTime(e.timestamp)}</span>
            </div>
            {typeof detail.error_description === "string" && (
              <p className="mt-1 text-xs text-slate-500">{detail.error_description}</p>
            )}
            <RawLine text={e.raw?.raw_text} />
          </li>
        );
      })}
    </ul>
  );
}

function SensorTable({ hw }: { hw: HardwareTimeline }) {
  if (hw.sensor_events.length === 0) return <Empty>No sensor events recorded.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
            <th className="pb-2">Sensor</th>
            <th className="pb-2">Transition</th>
            <th className="pb-2">Expected</th>
            <th className="pb-2">Timestamp</th>
            <th className="pb-2">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {hw.sensor_events.map((s, i) => {
            const mismatch =
              s.expected_state != null && s.actual_state != null && s.expected_state !== s.actual_state;
            return (
              <tr key={i} className="border-t border-slate-800/60 align-top">
                <td className="py-2 font-mono text-xs text-slate-300">{s.sensor}</td>
                <td className="py-2 font-mono text-xs text-slate-400">
                  {s.previous_state ?? "?"} → {s.new_state ?? "?"}
                  {s.abnormal_duration_ms != null && (
                    <Badge tone="amber" title="abnormal duration flagged by the extractor">
                      {s.abnormal_duration_ms} ms
                    </Badge>
                  )}
                </td>
                <td className="py-2 text-xs">
                  {mismatch ? (
                    <Badge tone="rose">{s.expected_state} ≠ {s.actual_state}</Badge>
                  ) : (
                    <span className="text-slate-500">{s.expected_state ?? "—"}</span>
                  )}
                </td>
                <td className="py-2 text-xs text-slate-400">{fmtTime(s.timestamp)}</td>
                <td className="py-2 text-[11px] text-indigo-400">
                  {s.log_file_id && s.line_number != null && (
                    <Link className="hover:underline" to={`/logs/${s.log_file_id}?line=${s.line_number}`}>
                      line {s.line_number} ↗
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function MotorTable({ hw }: { hw: HardwareTimeline }) {
  if (hw.motor_events.length === 0) return <Empty>No motor events recorded.</Empty>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] text-sm">
        <thead>
          <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
            <th className="pb-2">Motor</th>
            <th className="pb-2">Started</th>
            <th className="pb-2">Duration</th>
            <th className="pb-2">Timeout</th>
            <th className="pb-2">Evidence</th>
          </tr>
        </thead>
        <tbody>
          {hw.motor_events.map((m, i) => (
            <tr key={i} className="border-t border-slate-800/60 align-top">
              <td className="py-2 font-mono text-xs text-slate-300">
                {m.motor}
                {m.timed_out && <Badge tone="rose">timed out</Badge>}
              </td>
              <td className="py-2 text-xs text-slate-400">{fmtTime(m.started_at)}</td>
              <td className="py-2 text-xs text-slate-400">
                {m.duration_ms != null ? `${m.duration_ms} ms` : "—"}
              </td>
              <td className="py-2 text-xs text-slate-500">{m.timeout_ms != null ? `${m.timeout_ms} ms` : "—"}</td>
              <td className="py-2 text-[11px] text-indigo-400">
                {m.log_file_id && m.line_number != null && (
                  <Link className="hover:underline" to={`/logs/${m.log_file_id}?line=${m.line_number}`}>
                    line {m.line_number} ↗
                  </Link>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FindingCard({ f }: { f: Finding }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-slate-200">{f.rule_id}</span>
        <Badge tone={statusTone(f.severity)}>{f.severity}</Badge>
        <ConfidenceBadge level={f.confidence} />
        <Badge tone="violet">{f.diagnosis_class}</Badge>
      </div>
      <p className="mt-1.5 text-sm text-slate-300">{f.summary}</p>
      <p className="mt-1 text-xs text-slate-500">{f.interpretation}</p>
      {Array.isArray(f.possible_causes) && f.possible_causes.length > 0 && (
        <div className="mt-2">
          <span className="text-[11px] uppercase tracking-wide text-slate-600">
            Possible causes (hypotheses — not root causes)
          </span>
          <ul className="mt-1 list-inside list-disc text-xs text-slate-400">
            {f.possible_causes.map((c, i) => (
              <li key={i}>
                {typeof c === "string"
                  ? c
                  : typeof c === "object" && c !== null && "summary" in (c as Record<string, unknown>)
                    ? String((c as Record<string, unknown>).summary)
                    : JSON.stringify(c)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function EvidenceList({
  timeline,
  hw,
  report,
}: {
  timeline: TimelineEntry[];
  hw: HardwareTimeline;
  report: DiagnosticReport;
}) {
  const items = useMemo(() => {
    const seen = new Set<string>();
    const out: { fileId: string; line: number; raw: string; origin: string }[] = [];
    const push = (fileId?: string | null, line?: number | null, raw?: string | null, origin = "") => {
      if (!fileId || line == null) return;
      const key = `${fileId}:${line}`;
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ fileId, line, raw: raw ?? "", origin });
    };
    for (const e of timeline) push(e.raw?.file_id, e.raw?.line_number, e.raw?.raw_text, "timeline");
    for (const m of hw.cash_movements) push(m.log_file_id, m.line_number, m.raw_text, "cash");
    for (const s of hw.sensor_events) push(s.log_file_id, s.line_number, s.raw_text, "sensor");
    for (const m of hw.motor_events) {
      push(m.log_file_id, m.line_number, m.raw_text, "motor");
      push(m.log_file_id, m.stop_line_number, m.stop_raw_text, "motor");
    }
    for (const g of [...hw.gate_events, ...hw.shutter_events]) push(g.log_file_id, g.line_number, g.raw_text, g.kind);
    for (const t of hw.transport_events) push(t.log_file_id, t.line_number, t.raw_text, "transport");
    for (const f of report.findings)
      for (const ev of f.evidence ?? []) push(ev.file_id, ev.line_number, ev.raw_text, `finding:${f.rule_id}`);
    return out.sort((a, b) => a.fileId.localeCompare(b.fileId) || a.line - b.line);
  }, [timeline, hw, report]);

  if (items.length === 0) return <Empty>No line-level evidence recorded.</Empty>;

  return (
    <ul className="space-y-1.5">
      {items.map((it, i) => (
        <li key={i} className="rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-1.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
            <Link className="text-indigo-400 hover:underline" to={`/logs/${it.fileId}?line=${it.line}`}>
              {it.fileId.slice(0, 8)}… : line {it.line} ↗
            </Link>
            <span className="uppercase text-slate-600">{it.origin}</span>
          </div>
          <RawLine text={it.raw} />
        </li>
      ))}
    </ul>
  );
}

function Recommendations({ report }: { report: DiagnosticReport }) {
  const withActions = report.findings.filter((f) => f.recommended_action);
  if (withActions.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No recommendations configured for the triggered rules
        {report.classification === "NORMAL_COMPLETION" ? " — transaction completed normally." : "."}
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {withActions.map((f) => (
        <li key={f.finding_id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-sm">
          <Badge tone={statusTone(f.severity)}>{f.rule_id}</Badge>
          <p className="mt-1.5 text-slate-300">{f.recommended_action}</p>
        </li>
      ))}
    </ul>
  );
}
