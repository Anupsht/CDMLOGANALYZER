// Phase 7 — transaction explorer: server-side filtering + pagination.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { Transaction } from "../types";
import { Badge, Card, Empty, ErrorBox, Pagination, Spinner, fmtAmount, fmtTime, statusTone } from "../components/ui";

const PAGE = 25;

const STATUSES = ["COMPLETED", "DECLINED", "FAILED", "INCOMPLETE"];
const HOST_RESULTS = ["approved", "declined", "no_response"];
const CASH_STATES = ["STORED", "RETURNED", "REJECTED", "NOT_STORED"];

interface FilterState {
  transaction_id: string;
  model_code: string;
  machine_id: string;
  status: string;
  date_from: string;
  date_to: string;
  time_from: string;
  time_to: string;
  amount_min: string;
  amount_max: string;
  currency: string;
  host_result: string;
  cash_state: string;
  event_code: string;
  device: string;
  error_code: string;
  sort: string;
  dir: string;
}

const EMPTY: FilterState = {
  transaction_id: "",
  model_code: "",
  machine_id: "",
  status: "",
  date_from: "",
  date_to: "",
  time_from: "",
  time_to: "",
  amount_min: "",
  amount_max: "",
  currency: "",
  host_result: "",
  cash_state: "",
  event_code: "",
  device: "",
  error_code: "",
  sort: "start_time",
  dir: "desc",
};

// URL ?params → filter state (shareable deep links, e.g. from the dashboard)
function fromSearchParams(sp: URLSearchParams): FilterState {
  const next = { ...EMPTY };
  for (const key of Object.keys(EMPTY) as (keyof FilterState)[]) {
    const v = sp.get(key);
    if (v !== null) (next[key] as string) = v;
  }
  return next;
}

function toQuery(f: FilterState) {
  const q: Record<string, string | number> = {};
  for (const [k, v] of Object.entries(f)) {
    if (v !== "" && !(k === "sort" && v === EMPTY.sort) && !(k === "dir" && v === EMPTY.dir)) {
      q[k] = v;
    }
  }
  q.limit = PAGE;
  return q;
}

export default function Transactions() {
  const [sp, setSp] = useSearchParams();
  const [filters, setFilters] = useState<FilterState>(() => fromSearchParams(sp));
  const [draft, setDraft] = useState<FilterState>(() => fromSearchParams(sp));
  const [rows, setRows] = useState<Transaction[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [machines, setMachines] = useState<{ id: string; label: string }[]>([]);
  const [models, setModels] = useState<string[]>([]);

  useEffect(() => {
    api.listModels().then((ms) => setModels(ms.filter((m) => m.is_active).map((m) => m.code))).catch(() => {});
    api.listMachines(500).then((resp) =>
      setMachines(resp.items.map((m) => ({ id: m.id, label: `${m.serial_number}${m.name ? ` — ${m.name}` : ""}` }))),
    ).catch(() => {});
  }, []);

  // Known event codes a technician can filter by (universal vocabulary subset).
  const eventCodes = useMemo(
    () => [
      "JAM_DETECTED", "JAM_CLEARED", "DEVICE_UNAVAILABLE", "SENSOR_CHANGED",
      "VALIDATION_FAILED", "CASH_REJECTED", "HOST_DECLINED", "TRANSPORT_TIMEOUT",
      "MOTOR_STOPPED", "UNMAPPED",
    ],
    [],
  );

  const load = useCallback(
    (f: FilterState, off: number) => {
      setLoading(true);
      setError("");
      api
        .listTransactions({ ...toQuery(f), offset: off } as never)
        .then((r) => {
          setRows(r.items);
          setTotal(r.total);
          setLoading(false);
        })
        .catch((e) => {
          setError(e.message ?? String(e));
          setLoading(false);
        });
    },
    [],
  );

  useEffect(() => {
    load(filters, offset);
  }, [filters, offset, load]);

  const apply = (next: FilterState) => {
    setFilters(next);
    setDraft(next);
    setOffset(0);
    const usp = new URLSearchParams();
    for (const [k, v] of Object.entries(next)) if (v && !(k === "sort" && v === EMPTY.sort) && !(k === "dir" && v === EMPTY.dir)) usp.set(k, v);
    setSp(usp, { replace: true });
  };

  const set = (patch: Partial<FilterState>) => setDraft((d) => ({ ...d, ...patch }));

  const dirty = JSON.stringify(draft) !== JSON.stringify(filters);

  return (
    <div className="mx-auto max-w-[1500px] px-6 py-6">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-white">Transaction Explorer</h1>
        <p className="mt-1 text-xs text-slate-500">
          Server-side filtering across every integrated model. Open a transaction for
          timeline, cash trace, hardware and evidence.
        </p>
      </header>

      <Card
        title="Filters"
        subtitle={dirty ? "Press Apply to run the search" : "All filters run server-side"}
        right={
          <div className="flex gap-2">
            <button
              onClick={() => apply(EMPTY)}
              className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
            >
              Reset
            </button>
            <button
              onClick={() => apply(draft)}
              className={`rounded px-3 py-1.5 text-xs font-medium ${
                dirty ? "bg-indigo-600 text-white hover:bg-indigo-500" : "bg-slate-800 text-slate-500"
              }`}
            >
              Apply
            </button>
          </div>
        }
      >
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
          <Field label="Transaction ID">
            <input className={inputCls} placeholder="substring…" value={draft.transaction_id} onChange={(e) => set({ transaction_id: e.target.value })} />
          </Field>
          <Field label="Model">
            <select className={inputCls} value={draft.model_code} onChange={(e) => set({ model_code: e.target.value })}>
              <option value="">All models</option>
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>
          <Field label="Machine">
            <select className={inputCls} value={draft.machine_id} onChange={(e) => set({ machine_id: e.target.value })}>
              <option value="">All machines</option>
              {machines.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          </Field>
          <Field label="Status">
            <select className={inputCls} value={draft.status} onChange={(e) => set({ status: e.target.value })}>
              <option value="">All</option>
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
          <Field label="Host result">
            <select className={inputCls} value={draft.host_result} onChange={(e) => set({ host_result: e.target.value })}>
              <option value="">Any</option>
              {HOST_RESULTS.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
            </select>
          </Field>
          <Field label="Cash state">
            <select className={inputCls} value={draft.cash_state} onChange={(e) => set({ cash_state: e.target.value })}>
              <option value="">Any</option>
              {CASH_STATES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
            </select>
          </Field>
          <Field label="Date from">
            <input type="date" className={inputCls} value={draft.date_from} onChange={(e) => set({ date_from: e.target.value })} />
          </Field>
          <Field label="Date to">
            <input type="date" className={inputCls} value={draft.date_to} onChange={(e) => set({ date_to: e.target.value })} />
          </Field>
          <Field label="Time from">
            <input type="time" className={inputCls} value={draft.time_from} onChange={(e) => set({ time_from: e.target.value })} />
          </Field>
          <Field label="Time to">
            <input type="time" className={inputCls} value={draft.time_to} onChange={(e) => set({ time_to: e.target.value })} />
          </Field>
          <Field label="Amount min">
            <input type="number" step="0.01" className={inputCls} value={draft.amount_min} onChange={(e) => set({ amount_min: e.target.value })} />
          </Field>
          <Field label="Amount max">
            <input type="number" step="0.01" className={inputCls} value={draft.amount_max} onChange={(e) => set({ amount_max: e.target.value })} />
          </Field>
          <Field label="Currency">
            <input className={inputCls} placeholder="CNY" maxLength={8} value={draft.currency} onChange={(e) => set({ currency: e.target.value })} />
          </Field>
          <Field label="Error (code in raw line)">
            <input className={inputCls} placeholder="e.g. E-402 / EC-0142" value={draft.error_code} onChange={(e) => set({ error_code: e.target.value })} />
          </Field>
          <Field label="Event code">
            <select className={inputCls} value={draft.event_code} onChange={(e) => set({ event_code: e.target.value })}>
              <option value="">Any</option>
              {eventCodes.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          </Field>
          <Field label="Device (exact)">
            <input className={inputCls} placeholder="e.g. Motor-1" value={draft.device} onChange={(e) => set({ device: e.target.value })} />
          </Field>
          <Field label="Sort by">
            <select className={inputCls} value={draft.sort} onChange={(e) => set({ sort: e.target.value })}>
              <option value="start_time">Start time</option>
              <option value="amount">Amount</option>
              <option value="created_at">Imported</option>
              <option value="transaction_id">Transaction ID</option>
            </select>
          </Field>
          <Field label="Direction">
            <select className={inputCls} value={draft.dir} onChange={(e) => set({ dir: e.target.value })}>
              <option value="desc">Descending</option>
              <option value="asc">Ascending</option>
            </select>
          </Field>
        </div>
      </Card>

      {error && <div className="mt-4"><ErrorBox message={error} /></div>}

      <Card title={`Transactions${total ? ` (${total})` : ""}`} className="mt-4">
        {loading ? (
          <Spinner />
        ) : rows.length === 0 ? (
          <Empty>No transactions match these filters.</Empty>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="pb-2">Transaction</th>
                    <th className="pb-2">Model</th>
                    <th className="pb-2">Started</th>
                    <th className="pb-2 text-right">Amount</th>
                    <th className="pb-2">Status</th>
                    <th className="pb-2 text-right">Confidence</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((t) => (
                    <tr key={t.id} className="border-t border-slate-800/60 hover:bg-slate-800/30">
                      <td className="py-2">
                        <Link className="font-mono text-indigo-300 hover:underline" to={`/transactions/${t.id}`}>
                          {t.transaction_id}
                        </Link>
                      </td>
                      <td className="py-2 text-slate-400">{t.model_code ?? "—"}</td>
                      <td className="py-2 text-slate-400">{fmtTime(t.start_time)}</td>
                      <td className="py-2 text-right text-slate-300">{fmtAmount(t.amount, t.currency)}</td>
                      <td className="py-2"><Badge tone={statusTone(t.status)}>{t.status}</Badge></td>
                      <td className="py-2 text-right font-mono text-xs text-slate-400">
                        {(t.correlation_confidence * 100).toFixed(0)}%
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={total} limit={PAGE} offset={offset} onPage={setOffset} />
          </>
        )}
      </Card>
    </div>
  );
}

const inputCls =
  "w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-indigo-500";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  );
}
