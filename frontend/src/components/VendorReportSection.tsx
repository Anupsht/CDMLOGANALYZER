// Phase 8 — vendor escalation & export section (spec §8 flow):
// Analyze (rule engine, Analysis section) → Review (AI explanation below) →
// Generate Vendor Report → Export PDF → Export Excel.
//
// The AI explanation is a layer on top of the deterministic analysis: every
// claim carries an epistemic label (CONFIRMED/PROBABLE/POSSIBLE/UNKNOWN)
// and cites evidence ids. The section never presents the explanation as
// certain or as a replacement for the rules-engine findings.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  AIExplanation,
  DiagnosticReport,
  EpistemicLabel,
  HardwareTimeline,
  TransactionDetail as TxnDetail,
} from "../types";
import { LABEL_TONE } from "../types";
import { Badge, Card, ConfidenceBadge, Empty, ErrorBox, RawLine, Spinner } from "./ui";

const LABEL_TONES: Record<EpistemicLabel, string> = LABEL_TONE;

export default function VendorReportSection({
  detail,
  hw,
  report,
}: {
  detail: TxnDetail;
  hw: HardwareTimeline;
  report: DiagnosticReport;
}) {
  const [explanation, setExplanation] = useState<AIExplanation | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api
      .getAIExplanation(detail.id)
      .then((e) => !cancelled && setExplanation(e))
      .catch(() => !cancelled && setExplanation(null))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [detail.id]);

  const generate = async () => {
    setGenerating(true);
    setError("");
    try {
      setExplanation(await api.generateAIExplanation(detail.id));
    } catch (e) {
      setError((e as Error).message ?? String(e));
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Card
      title="Vendor Report & Export"
      subtitle="AI explanation layer on top of the deterministic analysis — review, then export for vendor escalation"
      right={
        <div className="flex flex-wrap gap-2">
          <button
            onClick={generate}
            disabled={generating}
            className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500 disabled:opacity-50"
          >
            {generating ? "Analyzing…" : explanation ? "Regenerate explanation" : "Generate explanation"}
          </button>
          <a
            href={api.reportPdfUrl(detail.id)}
            className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            Export PDF
          </a>
          <a
            href={api.reportXlsxUrl(detail.id)}
            className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
          >
            Export Excel
          </a>
        </div>
      }
    >
      {error && <div className="mb-3"><ErrorBox message={error} /></div>}

      {loading ? (
        <Spinner label="Checking for a stored explanation…" />
      ) : !explanation ? (
        <Empty>
          No explanation generated yet. Click <strong>Generate explanation</strong> — the
          deterministic rules-engine picture (Analysis section) is composed into a
          reviewable explanation with evidence references. No external AI is required.
        </Empty>
      ) : (
        <ExplanationView e={explanation} />
      )}

      {/* Escalation checklist — deterministic facts the vendor will ask for */}
      <div className="mt-4 grid gap-3 rounded-lg border border-slate-800 bg-slate-950/50 p-3 text-xs text-slate-400 md:grid-cols-3">
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Report contains</div>
          machine · model · location · transaction · timestamps · amount · problem ·
          timeline · errors · hardware / cash / host state · evidence · analysis ·
          vendor questions
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Hardware state</div>
          {hw.faults.length > 0
            ? hw.faults.map((f, i) => (
                <div key={i}>
                  {f.classification}
                  {f.subject_name ? ` · ${f.subject_name}` : ""}
                </div>
              ))
            : "no faults assessed"}
        </div>
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Problem</div>
          <Badge tone="violet">{report.classification}</Badge>{" "}
          <Badge tone="violet">{report.diagnosis_class}</Badge>
          <div className="mt-1">
            <ConfidenceBadge level={report.confidence} />
          </div>
        </div>
      </div>
    </Card>
  );
}

function ExplanationView({ e }: { e: AIExplanation }) {
  const p = e.payload;
  return (
    <div className="space-y-4">
      {/* provenance */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
        <span>
          provider <span className="text-slate-300">{e.provider}</span>
        </span>
        <span>
          generator <Badge tone={e.generator === "external-llm" ? "violet" : "slate"}>{e.generator}</Badge>
        </span>
        <span className="font-mono">digest {e.digest_sha256.slice(0, 12)}…</span>
        {e.created_at && <span>{e.created_at.replace("T", " ").slice(0, 19)}</span>}
      </div>

      {/* technical summary */}
      <div>
        <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Technical summary</div>
        <p className="text-sm text-slate-300">{p.technical_summary}</p>
      </div>

      {/* root cause */}
      <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] uppercase tracking-wide text-slate-500">Root cause</span>
          <Badge tone={LABEL_TONES[p.root_cause.label] ?? "slate"} title={p.labels?.legend?.[p.root_cause.label]}>
            {p.root_cause.label}
          </Badge>
        </div>
        <p className="mt-1.5 text-sm text-slate-200">{p.root_cause.statement}</p>
        {p.root_cause.basis && <p className="mt-1 text-xs text-slate-500">{p.root_cause.basis}</p>}
        {p.root_cause.evidence_ids.length > 0 && (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {p.root_cause.evidence_ids.map((id) => (
              <EvidenceChip key={id} id={id} evidence={p.evidence} />
            ))}
          </div>
        )}
        <div className="mt-2 text-xs text-slate-500">
          Confidence: <span className="text-slate-300">{p.confidence.label}</span>
          {p.confidence.rationale ? ` — ${p.confidence.rationale}` : ""}
        </div>
      </div>

      {/* possible causes */}
      {p.possible_causes.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">
            Possible causes (hypotheses)
          </div>
          <ul className="space-y-1.5">
            {p.possible_causes.map((c, i) => (
              <li key={i} className="rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-1.5 text-sm">
                <Badge tone={LABEL_TONES[c.label] ?? "slate"}>{c.label}</Badge>{" "}
                <span className="text-slate-300">{c.statement}</span>
                {c.evidence_ids.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {c.evidence_ids.map((id) => (
                      <EvidenceChip key={id} id={id} evidence={p.evidence} />
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* recommended actions */}
      {p.recommended_actions.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Recommended actions</div>
          <ul className="list-inside list-disc space-y-1 text-sm text-slate-300">
            {p.recommended_actions.map((a, i) => (
              <li key={i}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {/* vendor questions */}
      {p.vendor_questions.length > 0 && (
        <div>
          <div className="mb-1 text-[11px] uppercase tracking-wide text-slate-500">Vendor questions</div>
          <ul className="space-y-1 text-sm text-slate-300">
            {p.vendor_questions.map((q, i) => (
              <li key={i} className="rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-1.5">
                <span className="text-amber-300">?</span> {q}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* safety notes + legend */}
      {(e.safety_notes?.length || p.caveats?.length) && (
        <details className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
          <summary className="cursor-pointer text-xs text-slate-400">
            Safety & provenance notes
            {e.safety_notes?.length ? ` (${e.safety_notes.length})` : ""}
          </summary>
          <ul className="mt-2 space-y-1 text-[11px] text-slate-500">
            {(e.safety_notes ?? []).map((n, i) => (
              <li key={i}>• {n}</li>
            ))}
            {(p.caveats ?? []).map((c, i) => (
              <li key={`c${i}`}>• {c}</li>
            ))}
          </ul>
          <div className="mt-2 grid gap-1 text-[11px] text-slate-500 md:grid-cols-2">
            {Object.entries(p.labels?.legend ?? {}).map(([k, v]) => (
              <div key={k}>
                <Badge tone={LABEL_TONES[k as EpistemicLabel] ?? "slate"}>{k}</Badge> {v}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function EvidenceChip({
  id,
  evidence,
}: {
  id: string;
  evidence: { id: string; file: string; file_id?: string | null; line_number: number; raw_excerpt: string }[];
}) {
  const item = evidence.find((x) => x.id === id);
  if (!item) return <Badge tone="slate">{id}</Badge>;
  return (
    <span
      className="group relative"
      title={item.raw_excerpt}
    >
      {item.file_id ? (
        <Link
          to={`/logs/${item.file_id}?line=${item.line_number}`}
          className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-indigo-300 hover:bg-slate-700"
        >
          {id} · {item.file}:{item.line_number}
        </Link>
      ) : (
        <span className="rounded bg-slate-800/80 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
          {id} · {item.file}:{item.line_number}
        </span>
      )}
      <span className="pointer-events-none absolute left-0 top-6 z-20 hidden w-96 rounded border border-slate-700 bg-slate-950 p-2 font-mono text-[10px] text-slate-300 shadow-xl group-hover:block">
        <RawLine text={item.raw_excerpt} />
      </span>
    </span>
  );
}
