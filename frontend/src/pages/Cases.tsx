// Phase 10 — maintenance / investigation cases.

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { CaseItem } from "../types";
import { Badge, Card, Empty, ErrorBox, Spinner, fmtTime } from "../components/ui";
import { useAuth } from "../auth";

const STATUS_TONE: Record<CaseItem["status"], string> = {
  OPEN: "amber",
  IN_REVIEW: "sky",
  CLOSED: "emerald",
};
const PRIORITY_TONE: Record<CaseItem["priority"], string> = {
  HIGH: "rose",
  MEDIUM: "slate",
  LOW: "slate",
};

export default function Cases() {
  const { can } = useAuth();
  const [cases, setCases] = useState<CaseItem[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [title, setTitle] = useState("");
  const [priority, setPriority] = useState("MEDIUM");
  const [txnRef, setTxnRef] = useState("");
  const [description, setDescription] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setCases(await api.listCases());
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    try {
      await api.createCase({
        title: title.trim(),
        priority,
        description: description.trim() || undefined,
        transaction_ref: txnRef.trim() || undefined,
      });
      setTitle("");
      setDescription("");
      setTxnRef("");
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const transition = async (c: CaseItem, status: CaseItem["status"]) => {
    try {
      await api.updateCase(c.id, { status });
      await load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-5xl px-6 py-6">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-white">Cases</h1>
        <p className="mt-1 text-xs text-slate-500">
          Investigation cases tie evidence (machine, transaction) to human follow-up.
        </p>
      </header>
      {error && <div className="mb-4"><ErrorBox message={error} /></div>}

      {can("cases:create") && (
        <Card title="Open a case" subtitle="created in your name and written to the audit trail">
          <form onSubmit={create} className="grid gap-2 md:grid-cols-[1fr_auto_auto_auto]">
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Title (min 3 chars)"
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
            <select
              value={priority}
              onChange={(e) => setPriority(e.target.value)}
              className="rounded border border-slate-700 bg-slate-950 px-2 py-2 text-sm text-slate-200"
            >
              <option>LOW</option><option>MEDIUM</option><option>HIGH</option>
            </select>
            <input
              value={txnRef}
              onChange={(e) => setTxnRef(e.target.value)}
              placeholder="Transaction ref (optional)"
              className="rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
            <button
              type="submit"
              disabled={title.trim().length < 3}
              className="rounded bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
            >
              Create case
            </button>
            <input
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Short description (optional)"
              className="md:col-span-4 rounded border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-200"
            />
          </form>
        </Card>
      )}

      <div className="mt-4">
        {loading ? <Spinner /> : cases.length === 0 ? (
          <Empty>No cases yet.</Empty>
        ) : (
          <div className="space-y-2">
            {cases.map((c) => (
              <div key={c.id} className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3">
                <div className="flex flex-wrap items-center gap-2 text-sm">
                  <Badge tone={STATUS_TONE[c.status]}>{c.status.replaceAll("_", " ")}</Badge>
                  <Badge tone={PRIORITY_TONE[c.priority]}>{c.priority}</Badge>
                  <span className="font-medium text-slate-200">{c.title}</span>
                  {c.transaction_ref && (
                    <Link
                      to={`/transactions?transaction_id=${encodeURIComponent(c.transaction_ref)}`}
                      className="font-mono text-xs text-indigo-400 hover:underline"
                    >
                      {c.transaction_ref}
                    </Link>
                  )}
                  <span className="ml-auto text-[11px] text-slate-600">
                    by {c.created_by ?? "—"} · {fmtTime(c.created_at)}
                  </span>
                </div>
                {c.description && <p className="mt-1 text-xs text-slate-400">{c.description}</p>}
                {can("cases:update") && c.status !== "CLOSED" && (
                  <div className="mt-2 flex gap-2">
                    {c.status === "OPEN" && (
                      <button
                        onClick={() => void transition(c, "IN_REVIEW")}
                        className="rounded border border-sky-800 px-2 py-0.5 text-[11px] text-sky-300 hover:bg-sky-950"
                      >
                        Start review
                      </button>
                    )}
                    <button
                      onClick={() => void transition(c, "CLOSED")}
                      className="rounded border border-emerald-800 px-2 py-0.5 text-[11px] text-emerald-300 hover:bg-emerald-950"
                    >
                      Close case
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
