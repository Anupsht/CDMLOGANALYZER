// Phase 7 — technician dashboard (fleet + transaction KPIs, evidence-based).

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardSummary, Transaction } from "../types";
import StatCard from "../components/StatCard";
import { Badge, Card, Empty, ErrorBox, Pagination, Spinner, fmtAmount, fmtTime, statusTone } from "../components/ui";
import UploadDropzone from "../components/UploadDropzone";

const PAGE = 10;

export default function Dashboard() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [recent, setRecent] = useState<Transaction[]>([]);
  const [recentTotal, setRecentTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      api.dashboardSummary().catch(() => null),
      api.listTransactions({ limit: PAGE, offset, sort: "start_time", dir: "desc" }).catch(() => null),
    ])
      .then(([s, t]) => {
        if (cancelled) return;
        if (s) setSummary(s);
        else setError("Backend not reachable — is it running?");
        if (t) {
          setRecent(t.items);
          setRecentTotal(t.total);
        }
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [offset]);

  return (
    <div className="mx-auto max-w-[1500px] px-6 py-6">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Operations Dashboard</h1>
          <p className="mt-1 text-xs text-slate-500">
            Aggregated from stored log evidence — findings reuse the rules-engine
            classification. Counter semantics:{" "}
            <Link className="text-indigo-400 hover:underline" to="/transactions">
              browse transactions
            </Link>
          </p>
        </div>
        <span className="text-xs text-slate-500">
          {summary ? `generated ${fmtTime(summary.generated_at)}` : ""}
        </span>
      </header>

      {error && <ErrorBox message={error} />}

      {loading && !summary ? (
        <Spinner />
      ) : summary ? (
        <>
          {/* Fleet */}
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            <StatCard label="Total machines" value={summary.fleet.total} accent="indigo" />
            <StatCard
              label="Online"
              value={summary.fleet.online}
              accent="emerald"
              hint={`activity within ${summary.fleet.window_hours}h`}
            />
            <StatCard
              label="Offline"
              value={summary.fleet.offline}
              accent="slate"
              hint="no recent logged activity"
            />
            <StatCard label="Transactions" value={summary.transactions.total} accent="indigo" />
            <StatCard
              label="Successful"
              value={summary.transactions.completed}
              accent="emerald"
              hint="status COMPLETED"
            />
          </div>
          <div className="mt-4 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-5">
            <StatCard label="Failed" value={summary.transactions.failed} accent="rose" hint="status FAILED" />
            <StatCard
              label="Hardware errors"
              value={summary.findings.hardware_errors}
              accent="rose"
              hint="machines w/ HARDWARE_FAILURE findings"
            />
            <StatCard
              label="Possible jams"
              value={summary.findings.possible_jams}
              accent="amber"
              hint="POSSIBLE_CASH_JAM rules"
            />
            <StatCard
              label="Cash exceptions"
              value={summary.findings.cash_exceptions}
              accent="yellow"
              hint="CASH_EXCEPTION findings"
            />
            <StatCard
              label="Host failures"
              value={summary.findings.host_failures}
              accent="violet"
              hint="HOST_FAILURE findings"
            />
          </div>

          <div className="mt-5 grid gap-5 xl:grid-cols-3">
            {/* Model breakdown */}
            <Card title="By machine model" subtitle="All integrated models flow through the same engine" className="xl:col-span-1">
              {summary.models.length === 0 ? (
                <Empty>No transactions analysed yet — upload logs below.</Empty>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                      <th className="pb-2">Model</th>
                      <th className="pb-2 text-right">Txns</th>
                      <th className="pb-2 text-right text-emerald-400">OK</th>
                      <th className="pb-2 text-right text-rose-400">Fail</th>
                      <th className="pb-2 text-right text-amber-400">Decl.</th>
                      <th className="pb-2 text-right text-slate-400">Inc.</th>
                    </tr>
                  </thead>
                  <tbody>
                    {summary.models.map((m) => (
                      <tr key={m.model_code} className="border-t border-slate-800/60">
                        <td className="py-2">
                          <Link
                            className="font-medium text-indigo-300 hover:underline"
                            to={`/transactions?model_code=${m.model_code}`}
                          >
                            {m.model_code}
                          </Link>
                        </td>
                        <td className="py-2 text-right text-slate-300">{m.transactions}</td>
                        <td className="py-2 text-right text-emerald-300">{m.completed}</td>
                        <td className="py-2 text-right text-rose-300">{m.failed}</td>
                        <td className="py-2 text-right text-amber-300">{m.declined}</td>
                        <td className="py-2 text-right text-slate-400">{m.incomplete}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="mt-3 text-[11px] leading-relaxed text-slate-600">
                {summary.fleet.note}
              </p>
            </Card>

            {/* Recent transactions */}
            <Card
              title="Recent transactions"
              subtitle={`${recentTotal} total — click to open the full analysis`}
              className="xl:col-span-2"
            >
              {recent.length === 0 ? (
                <Empty>No transactions yet.</Empty>
              ) : (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[720px] text-sm">
                      <thead>
                        <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                          <th className="pb-2">Transaction</th>
                          <th className="pb-2">Model</th>
                          <th className="pb-2">Started</th>
                          <th className="pb-2 text-right">Amount</th>
                          <th className="pb-2">Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recent.map((t) => (
                          <tr key={t.id} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                            <td className="py-2">
                              <Link
                                className="font-mono text-indigo-300 hover:underline"
                                to={`/transactions/${t.id}`}
                              >
                                {t.transaction_id}
                              </Link>
                            </td>
                            <td className="py-2 text-slate-400">{t.model_code ?? "—"}</td>
                            <td className="py-2 text-slate-400">{fmtTime(t.start_time)}</td>
                            <td className="py-2 text-right text-slate-300">
                              {fmtAmount(t.amount, t.currency)}
                            </td>
                            <td className="py-2">
                              <Badge tone={statusTone(t.status)}>{t.status}</Badge>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  <Pagination total={recentTotal} limit={PAGE} offset={offset} onPage={setOffset} />
                </>
              )}
            </Card>
          </div>

          {/* Upload */}
          <div className="mt-5">
            <UploadDropzone onUploaded={() => setOffset(0)} />
          </div>
        </>
      ) : null}
    </div>
  );
}
