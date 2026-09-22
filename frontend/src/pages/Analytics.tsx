// Phase 9 — historical analytics, pattern detection, cross-machine analysis,
// maintenance insights and the human-in-the-loop rule-suggestion workflow.

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type {
  AnalyticsOverview,
  CrossMachineOut,
  ErrorStat,
  InsightsOut,
  MaintenanceFlag,
  MaintenanceOut,
  PatternDetection,
  RuleSuggestion,
  TrendsOut,
} from "../types";
import { BarChart, LineChart } from "../components/charts";
import { Badge, Card, Empty, ErrorBox, Spinner, fmtTime } from "../components/ui";

const WINDOWS = [30, 90, 180, 365];
const BUCKETS = ["daily", "weekly", "monthly"] as const;
const FLAG_ORDER: Record<MaintenanceFlag, string> = { HIGH_RISK: "rose", WARNING: "amber", WATCH: "sky" };

export default function Analytics() {
  const [windowDays, setWindowDays] = useState(90);
  const [bucket, setBucket] = useState<(typeof BUCKETS)[number]>("daily");

  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [trends, setTrends] = useState<TrendsOut | null>(null);
  const [errors, setErrors] = useState<ErrorStat[]>([]);
  const [patterns, setPatterns] = useState<PatternDetection[]>([]);
  const [cross, setCross] = useState<CrossMachineOut | null>(null);
  const [maint, setMaint] = useState<MaintenanceOut | null>(null);
  const [insights, setInsights] = useState<InsightsOut | null>(null);
  const [suggestions, setSuggestions] = useState<RuleSuggestion[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ov, tr, er, pa, cm, mt, ins, sg] = await Promise.all([
        api.analyticsOverview(windowDays),
        api.analyticsTrends(bucket, windowDays),
        api.analyticsErrors(windowDays),
        api.analyticsPatterns(windowDays),
        api.analyticsCrossMachine(windowDays),
        api.analyticsMaintenance(7, Math.max(30, windowDays)),
        api.analyticsInsights(windowDays),
        api.listRuleSuggestions(),
      ]);
      setOverview(ov);
      setTrends(tr);
      setErrors(er.errors);
      setPatterns(pa.patterns);
      setCross(cm);
      setMaint(mt);
      setInsights(ins);
      setSuggestions(sg);
    } catch (e) {
      setError((e as Error).message ?? String(e));
    } finally {
      setLoading(false);
    }
  }, [windowDays, bucket]);

  useEffect(() => {
    void load();
  }, [load]);

  const fileSuggestion = async (pattern: PatternDetection) => {
    try {
      await api.createRuleSuggestion({
        title: pattern.rule_suggestion_draft.draft_rule.id,
        pattern_type: pattern.pattern_type,
        rationale: pattern.description,
        pattern_stats: pattern.stats,
        draft_rule: pattern.rule_suggestion_draft.draft_rule,
      });
      await load();
    } catch (e) {
      setError((e as Error).message ?? String(e));
    }
  };

  const review = async (id: string, status: RuleSuggestion["status"]) => {
    const reviewer = window.prompt(`Reviewer name for "${status}":`);
    if (!reviewer) return;
    try {
      await api.reviewRuleSuggestion(id, { status, reviewed_by: reviewer });
      await load();
    } catch (e) {
      setError((e as Error).message ?? String(e));
    }
  };

  return (
    <div className="mx-auto max-w-[1500px] px-6 py-6">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Analytics & Insights</h1>
          <p className="mt-1 text-xs text-slate-500">
            Historical aggregation of the stored evidence picture. Patterns are advisory —
            they never become production rules without human review.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-200"
          >
            {WINDOWS.map((d) => (
              <option key={d} value={d}>last {d} days</option>
            ))}
          </select>
          <select
            value={bucket}
            onChange={(e) => setBucket(e.target.value as typeof bucket)}
            className="rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-slate-200"
          >
            {BUCKETS.map((b) => (
              <option key={b} value={b}>{b}</option>
            ))}
          </select>
          <button onClick={() => void load()} className="rounded border border-slate-700 px-3 py-1.5 text-slate-300 hover:bg-slate-800">
            Refresh
          </button>
        </div>
      </header>

      {error && <div className="mb-4"><ErrorBox message={error} /></div>}
      {loading && !overview ? <Spinner /> : (
        <div className="grid gap-4">
          {/* §9 answers */}
          {insights && (
            <Card title="Key questions" subtitle={`over the last ${insights.window_days} days — every answer traces to stored evidence`}>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                <InsightBlock title="Which machines have the most problems?">
                  {insights.machines_with_most_problems.length === 0 ? <span className="text-slate-500">no failures recorded</span> :
                    insights.machines_with_most_problems.map((m) => (
                      <div key={m.machine_id} className="flex justify-between gap-2">
                        <span className="truncate text-slate-300">{m.model_code ?? "—"} · {m.machine_id.slice(0, 8)}…</span>
                        <span className="font-mono text-rose-300">{m.failures}</span>
                      </div>
                    ))}
                </InsightBlock>
                <InsightBlock title="Which errors are increasing?">
                  {insights.errors_increasing.length === 0 ? <span className="text-slate-500">none increasing</span> :
                    insights.errors_increasing.map((e) => (
                      <div key={e.error_code} className="flex justify-between gap-2">
                        <span className="truncate font-mono text-slate-300">{e.error_code}</span>
                        <span className="font-mono text-slate-400">{e.first_half} → <span className="text-amber-300">{e.second_half}</span></span>
                      </div>
                    ))}
                </InsightBlock>
                <InsightBlock title="Highest failure rate by model?">
                  {insights.model_highest_failure_rate ? (
                    <div className="text-slate-300">
                      <span className="font-semibold text-amber-300">{insights.model_highest_failure_rate.model_code}</span>
                      {" "}· {(insights.model_highest_failure_rate.failure_rate * 100).toFixed(1)}% failure rate
                    </div>
                  ) : <span className="text-slate-500">no data</span>}
                </InsightBlock>
                <InsightBlock title="What precedes transaction failure?">
                  {insights.faults_preceding_failure.length === 0 ? <span className="text-slate-500">no pattern</span> :
                    insights.faults_preceding_failure.map((f) => (
                      <div key={f.event} className="flex justify-between gap-2">
                        <span className="truncate text-slate-300">{f.event.replaceAll("_", " ")}</span>
                        <span className="font-mono text-slate-400">{f.count}×</span>
                      </div>
                    ))}
                  <p className="mt-1 text-[10px] text-slate-600">correlation inside failed transactions — not causation</p>
                </InsightBlock>
                <InsightBlock title="Investigate first (HIGH_RISK / ranking)?">
                  {insights.machines_to_investigate_first.length === 0 ? <span className="text-slate-500">nothing flagged</span> :
                    insights.machines_to_investigate_first.map((id, i) => (
                      <div key={id} className="flex justify-between gap-2">
                        <span className="truncate font-mono text-slate-300">{i + 1}. {id.slice(0, 8)}…</span>
                        <Link to="/health" className="text-indigo-400 hover:underline">health →</Link>
                      </div>
                    ))}
                </InsightBlock>
              </div>
            </Card>
          )}

          {/* §5 trends + §8 jam trends */}
          {trends && (
            <Card
              title={`Trends (${trends.bucket})`}
              subtitle="transactions · failures · jams · errors per bucket — jam & error trends included"
              right={
                <div className="flex gap-3 text-[11px]">
                  <span className="text-indigo-300">■ transactions</span>
                  <span className="text-rose-300">■ failures</span>
                  <span className="text-amber-300">■ jams</span>
                  <span className="text-sky-300">■ errors</span>
                </div>
              }
            >
              {trends.points.length === 0 ? (
                <Empty>No transactions in this window.</Empty>
              ) : (
                <LineChart
                  labels={trends.points.map((p) => p.bucket)}
                  series={[
                    { label: "transactions", color: "#818cf8", values: trends.points.map((p) => p.transactions) },
                    { label: "failures", color: "#fb7185", values: trends.points.map((p) => p.failures) },
                    { label: "jams", color: "#fbbf24", values: trends.points.map((p) => p.jams) },
                    { label: "errors", color: "#38bdf8", values: trends.points.map((p) => p.errors) },
                  ]}
                />
              )}
            </Card>
          )}

          <div className="grid gap-4 xl:grid-cols-2">
            {/* §8 model comparison */}
            {cross && (
              <Card title="Model comparison" subtitle="failure rate per model (§3, §8)">
                {cross.by_model.length === 0 ? <Empty>No data.</Empty> : (
                  <BarChart
                    rows={cross.by_model.map((g) => ({
                      label: g.model_code,
                      value: Math.round(g.failure_rate * 1000) / 10,
                      hint: `${g.failures} failures / ${g.transactions} transactions`,
                    }))}
                    formatValue={(v) => `${v}%`}
                  />
                )}
              </Card>
            )}

            {/* §8 machine ranking */}
            {cross && (
              <Card title="Machine ranking" subtitle="worst failure rate first (§3, §8)">
                {cross.machines.length === 0 ? <Empty>No machines.</Empty> : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                          <th className="pb-2">Machine</th>
                          <th className="pb-2">Model</th>
                          <th className="pb-2">Versions</th>
                          <th className="pb-2 text-right">Txns</th>
                          <th className="pb-2 text-right">Fail %</th>
                          <th className="pb-2">Top rules</th>
                        </tr>
                      </thead>
                      <tbody>
                        {cross.machines.map((m) => (
                          <tr key={m.machine_id} className="border-t border-slate-800/60">
                            <td className="py-1.5">
                              <span className="font-mono text-slate-300">{m.serial_number ?? m.machine_id.slice(0, 8)}</span>
                              {m.location && <div className="text-[10px] text-slate-600">{m.location}</div>}
                            </td>
                            <td className="py-1.5 text-slate-400">{m.model_code ?? "—"}</td>
                            <td className="py-1.5 font-mono text-[10px] text-slate-500">{m.software_versions.join(", ")}</td>
                            <td className="py-1.5 text-right text-slate-300">{m.transactions}</td>
                            <td className="py-1.5 text-right text-rose-300">{(m.failure_rate * 100).toFixed(0)}%</td>
                            <td className="py-1.5 text-[10px] text-slate-500">
                              {m.top_rules.slice(0, 2).map((r) => `${r.rule_id}(${r.count})`).join(" · ") || "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Card>
            )}

            {/* §4 error analytics / §8 error frequency */}
            <Card title="Error frequency & analytics" subtitle="occurrences · machines · models · neighbours (§4)">
              {errors.length === 0 ? <Empty>No error events in this window.</Empty> : (
                <div className="space-y-2">
                  {errors.slice(0, 8).map((e) => (
                    <details key={e.error_code} className="rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-1.5">
                      <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-xs">
                        <span className="font-mono text-slate-200">{e.error_code}</span>
                        <Badge tone="rose">{e.occurrence_count}×</Badge>
                        <span className="text-slate-500">{e.machines_affected} machine(s) · {e.models_affected.join(", ")}</span>
                        {e.last_occurrence && (
                          <span className="ml-auto text-[10px] text-slate-600">last {fmtTime(e.last_occurrence)}</span>
                        )}
                      </summary>
                      <div className="mt-2 grid gap-2 text-[11px] md:grid-cols-2">
                        <div>
                          <div className="mb-1 uppercase tracking-wide text-slate-600">common preceding</div>
                          {e.common_preceding_events.map((p) => (
                            <div key={p.event} className="flex justify-between text-slate-400">
                              <span>{p.event.replaceAll("_", " ")}</span><span className="font-mono">{p.count}×</span>
                            </div>
                          )) || "—"}
                        </div>
                        <div>
                          <div className="mb-1 uppercase tracking-wide text-slate-600">common following</div>
                          {e.common_following_events.map((f) => (
                            <div key={f.event} className="flex justify-between text-slate-400">
                              <span>{f.event.replaceAll("_", " ")}</span><span className="font-mono">{f.count}×</span>
                            </div>
                          )) || "—"}
                        </div>
                      </div>
                      <p className="mt-1 text-[10px] text-slate-600">first seen {fmtTime(e.first_occurrence)} · adjacent-event correlation, not causation</p>
                    </details>
                  ))}
                </div>
              )}
            </Card>

            {/* §6 maintenance insights */}
            {maint && (
              <Card
                title="Maintenance insights"
                subtitle={`last ${maint.recent_days}d vs previous ${maint.baseline_days}d — triage flags, never a component-failure declaration`}
              >
                {maint.machines.length === 0 ? <Empty>No machines.</Empty> : (
                  <div className="space-y-2">
                    {maint.machines.map((m) => (
                      <div key={m.machine_id} className="rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-2">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <Badge tone={FLAG_ORDER[m.overall_flag]}>{m.overall_flag}</Badge>
                          <span className="font-mono text-slate-200">{m.serial_number}</span>
                          <span className="text-slate-500">{m.model_code ?? "—"}</span>
                          <span className="ml-auto text-[10px] text-slate-600">
                            baseline {m.baseline_transactions} txns · recent {m.recent_transactions} txns
                          </span>
                        </div>
                        <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] md:grid-cols-4">
                          {Object.entries(m.metrics).map(([name, v]) => (
                            <div key={name} className="flex items-center justify-between gap-1">
                              <span className="truncate text-slate-500">{name.replace(/_/g, " ")}</span>
                              <span className="font-mono text-slate-400">
                                {v.baseline}→{v.recent}
                              </span>
                              <Badge tone={FLAG_ORDER[v.flag]}>{v.flag}</Badge>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <p className="mt-2 text-[10px] text-slate-600">{maint.note}</p>
              </Card>
            )}
          </div>

          {/* §2 + §7 patterns & suggestions */}
          <Card
            title="Detected patterns → rule suggestions"
            subtitle="advisory only: Pattern → Suggested Rule → Human Review → Approval → (manual) Production"
          >
            {patterns.length === 0 ? (
              <Empty>No patterns crossed the detection thresholds in this window.</Empty>
            ) : (
              <div className="space-y-2">
                {patterns.map((p, i) => (
                  <div key={i} className="rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-2 text-xs">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone="violet">{p.pattern_type.replaceAll("_", " ")}</Badge>
                      <Badge tone={p.confidence === "CONFIRMED" ? "rose" : p.confidence === "POSSIBLE" ? "sky" : "slate"}>
                        {p.confidence}
                      </Badge>
                      <span className="text-slate-300">{p.description}</span>
                      <button
                        onClick={() => void fileSuggestion(p)}
                        className="ml-auto rounded border border-indigo-700 px-2 py-0.5 text-[11px] text-indigo-300 hover:bg-indigo-950"
                      >
                        File as rule suggestion
                      </button>
                    </div>
                    <pre className="mt-1.5 overflow-x-auto rounded bg-slate-950 p-2 font-mono text-[10px] text-slate-500">
                      {JSON.stringify(p.rule_suggestion_draft.draft_rule, null, 1)}
                    </pre>
                  </div>
                ))}
              </div>
            )}

            {/* suggestion workflow list */}
            <div className="mt-4">
              <div className="mb-2 text-[11px] uppercase tracking-wide text-slate-500">
                Rule suggestions ({suggestions.length}) — approving never loads them into
                the engine; a human copies approved drafts into the YAML package
              </div>
              {suggestions.length === 0 ? (
                <Empty>No suggestions filed yet.</Empty>
              ) : (
                <div className="space-y-1.5">
                  {suggestions.map((s) => (
                    <div key={s.id} className="flex flex-wrap items-center gap-2 rounded border border-slate-800/70 bg-slate-950/40 px-2.5 py-1.5 text-xs">
                      <Badge tone={
                        s.status === "APPROVED" ? "emerald" : s.status === "REJECTED" ? "rose" : s.status === "UNDER_REVIEW" ? "amber" : "slate"
                      }>{s.status.replaceAll("_", " ")}</Badge>
                      <span className="font-mono text-slate-300">{s.title}</span>
                      <span className="text-[10px] text-slate-600">{s.pattern_type}</span>
                      {s.reviewed_by && <span className="text-[10px] text-slate-600">by {s.reviewed_by}</span>}
                      <div className="ml-auto flex gap-1">
                        {s.status === "SUGGESTED" && (
                          <button onClick={() => void review(s.id, "UNDER_REVIEW")} className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800">
                            Review
                          </button>
                        )}
                        {(s.status === "SUGGESTED" || s.status === "UNDER_REVIEW") && (
                          <>
                            <button onClick={() => void review(s.id, "APPROVED")} className="rounded border border-emerald-800 px-2 py-0.5 text-[11px] text-emerald-300 hover:bg-emerald-950">
                              Approve
                            </button>
                            <button onClick={() => void review(s.id, "REJECTED")} className="rounded border border-rose-900 px-2 py-0.5 text-[11px] text-rose-300 hover:bg-rose-950">
                              Reject
                            </button>
                          </>
                        )}
                        {s.status === "APPROVED" && (
                          <button onClick={() => void review(s.id, "INCORPORATED")} className="rounded border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:bg-slate-800" title="a human copied the draft into the YAML package">
                            Mark incorporated
                          </button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Card>

          {/* §1 historical counters */}
          {overview && (
            <Card title="Historical counters" subtitle={`evidence-based aggregation over ${overview.window_days} days (§1)`}>
              <div className="grid grid-cols-2 gap-3 text-xs md:grid-cols-5 xl:grid-cols-10">
                {[
                  ["transactions", overview.transactions.total],
                  ["failures", overview.failures],
                  ["errors", overview.errors],
                  ["jams", overview.jams],
                  ["sensor faults", overview.sensor_faults],
                  ["cash exceptions", overview.cash_exceptions],
                  ["host failures", overview.host_failures],
                  ["hardware errors", overview.hardware_errors],
                  ["device unavail.", overview.device_unavailable_events],
                  ["auto resets", overview.automatic_resets],
                ].map(([label, value]) => (
                  <div key={String(label)} className="rounded border border-slate-800/70 bg-slate-950/40 p-2 text-center">
                    <div className="text-lg font-semibold text-slate-200">{value}</div>
                    <div className="text-[10px] uppercase tracking-wide text-slate-600">{label}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}

function InsightBlock({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
      <div className="mb-2 text-[11px] uppercase tracking-wide text-slate-500">{title}</div>
      <div className="space-y-1 text-xs">{children}</div>
    </div>
  );
}
