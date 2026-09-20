import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { Machine, MachineModel } from "../types";

const STATUSES = ["unknown", "active", "inactive", "maintenance", "retired"];

export default function Machines() {
  const [machines, setMachines] = useState<Machine[]>([]);
  const [models, setModels] = useState<MachineModel[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ serial_number: "", model_code: "", location: "", status: "active" });
  const [saving, setSaving] = useState(false);

  const load = useCallback(() => {
    Promise.all([api.listMachines(), api.listModels()])
      .then(([m, mm]) => {
        setMachines(m.items);
        setModels(mm);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load machines"));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.serial_number.trim()) return;
    setSaving(true);
    try {
      await api.createMachine({
        serial_number: form.serial_number.trim(),
        model_code: form.model_code || undefined,
        location: form.location || undefined,
        status: form.status,
      });
      setForm({ serial_number: "", model_code: "", location: "", status: "active" });
      setError("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create machine");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-8">
      <header>
        <h1 className="text-2xl font-semibold text-white">Machines</h1>
        <p className="mt-1 text-sm text-slate-400">Physical CDM fleet linked to machine models.</p>
      </header>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-5 lg:col-span-1">
          <h2 className="text-sm font-semibold text-slate-200">Register machine</h2>
          <form onSubmit={submit} className="mt-4 space-y-3">
            <Field label="Serial number">
              <input
                value={form.serial_number}
                onChange={(e) => setForm({ ...form, serial_number: e.target.value })}
                placeholder="GRG-P2600N-000123"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
                required
              />
            </Field>
            <Field label="Model">
              <select
                value={form.model_code}
                onChange={(e) => setForm({ ...form, model_code: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
              >
                <option value="">— unknown —</option>
                {models
                  .filter((m) => m.is_active && !m.is_placeholder)
                  .map((m) => (
                    <option key={m.code} value={m.code}>
                      {m.code}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Location">
              <input
                value={form.location}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
                placeholder="Mall A, Floor 2"
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200 placeholder:text-slate-600"
              />
            </Field>
            <Field label="Status">
              <select
                value={form.status}
                onChange={(e) => setForm({ ...form, status: e.target.value })}
                className="w-full rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-sm text-slate-200"
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            </Field>
            <button
              type="submit"
              disabled={saving || !form.serial_number.trim()}
              className="w-full rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 disabled:opacity-50"
            >
              {saving ? "Saving…" : "Add machine"}
            </button>
          </form>
        </section>

        <section className="rounded-xl border border-slate-800 bg-slate-900/60 lg:col-span-2">
          <div className="border-b border-slate-800 px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-200">
              Fleet <span className="ml-1 text-slate-500">({machines.length})</span>
            </h2>
          </div>
          {machines.length === 0 ? (
            <p className="px-5 py-10 text-center text-sm text-slate-500">
              No machines registered yet.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-left text-[11px] uppercase tracking-wide text-slate-500">
                  <th className="px-5 py-2.5 font-medium">Serial</th>
                  <th className="px-3 py-2.5 font-medium">Model</th>
                  <th className="px-3 py-2.5 font-medium">Location</th>
                  <th className="px-3 py-2.5 font-medium">Status</th>
                  <th className="px-5 py-2.5 font-medium">Registered</th>
                </tr>
              </thead>
              <tbody>
                {machines.map((machine) => (
                  <tr key={machine.id} className="border-b border-slate-800/60 last:border-0">
                    <td className="px-5 py-2.5 font-mono text-xs text-slate-200">{machine.serial_number}</td>
                    <td className="px-3 py-2.5 text-slate-400">{machine.machine_model?.code ?? "—"}</td>
                    <td className="px-3 py-2.5 text-slate-400">{machine.location ?? "—"}</td>
                    <td className="px-3 py-2.5">
                      <span
                        className={`rounded-full px-2 py-0.5 text-[11px] ring-1 ring-inset ${
                          machine.status === "active"
                            ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40"
                            : "bg-slate-700/40 text-slate-300 ring-slate-600"
                        }`}
                      >
                        {machine.status}
                      </span>
                    </td>
                    <td className="px-5 py-2.5 text-xs text-slate-500">
                      {new Date(machine.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs text-slate-400">{label}</span>
      {children}
    </label>
  );
}
