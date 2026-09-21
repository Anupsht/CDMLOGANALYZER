// Phase 7 — machine health: evidence-based counters per machine plus a
// CONFIGURABLE heuristic score. The score is a prioritisation aid for
// technicians — it is explicitly NOT a diagnosis (the backend never
// computes it; weights live client-side and are adjustable).

import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Machine, MachineHealthMetrics } from "../types";
import { Badge, Card, Empty, ErrorBox, Spinner, fmtTime, statusTone } from "../components/ui";

interface Weights {
  failure_rate: number;
  jam_frequency: number;
  hardware_errors: number;
  sensor_abnormalities: number;
  device_unavailable: number;
  recovery_reset: number;
}

const DEFAULT_WEIGHTS: Weights = {
  failure_rate: 4,
  jam_frequency: 5,
  hardware_errors: 4,
  sensor_abnormalities: 2,
  device_unavailable: 2,
  recovery_reset: 1,
};

const WEIGHT_LABELS: Record<keyof Weights, string> = {
  failure_rate: "Transaction failure rate",
  jam_frequency: "Jam frequency",
  hardware_errors: "Hardware errors",
  sensor_abnormalities: "Sensor abnormalities",
  device_unavailable: "Device unavailable events",
  recovery_reset: "Reset / recovery events",
};

const WINDOWS = [7, 30, 90, 365];

function loadWeights(): Weights {
  try {
    const raw = localStorage.getItem("cdm-health-weights");
    if (raw) return { ...DEFAULT_WEIGHTS, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return DEFAULT_WEIGHTS;
}

/** Normalised 0..1 stress per component (per-transaction rates, capped). */
function components(m: MachineHealthMetrics) {
  const rate = (n: number) => (m.transactions_total > 0 ? Math.min(1, n / m.transactions_total) : 0);
  return {
    failure_rate: Math.min(1, m.failure_rate),
    jam_frequency: Math.min(1, m.jam_frequency),
    hardware_errors: rate(m.hardware_error_transactions),
    sensor_abnormalities: rate(m.sensor_abnormalities),
    device_unavailable: rate(m.device_unavailable_events),
    recovery_reset: rate(m.recovery_reset_events),
  };
}

function computeScore(m: MachineHealthMetrics, w: Weights): number {
  const c = components(m);
  const totalW = Object.values(w).reduce((a, b) => a + b, 0);
  if (totalW === 0) return 100;
  const stress = (Object.keys(c) as (keyof Weights)[]).reduce((acc, k) => acc + c[k] * w[k], 0) / totalW;
  return Math.round(100 * (1 - stress));
}

const scoreTone = (s: number) => (s >= 80 ? "emerald" : s >= 60 ? "amber" : "rose");

export default function MachineHealth() {
  const [machines, setMachines] = useState<Machine[] | null>(null);
  const [metrics, setMetrics] = useState<Record<string, MachineHealthMetrics>>({});
  const [windowDays, setWindowDays] = useState(30);
  const [weights, setWeights] = useState<Weights>(loadWeights);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listMachines(500)
      .then((r) => setMachines(r.items))
      .catch((e) => setError(e.message ?? String(e)));
  }, []);

  useEffect(() => {
    if (!machines) return;
    let cancelled = false;
    Promise.all(
      machines.map((m) =>
        api
          .machineHealth(m.id, windowDays)
          .then((h) => [m.id, h] as const)
          .catch(() => [m.id, null] as const),
      ),
    ).then((entries) => {
      if (cancelled) return;
      const next: Record<string, MachineHealthMetrics> = {};
      for (const [id, h] of entries) if (h) next[id] = h;
      setMetrics(next);
    });
    return () => {
      cancelled = true;
    };
  }, [machines, windowDays]);

  useEffect(() => {
    localStorage.setItem("cdm-health-weights", JSON.stringify(weights));
  }, [weights]);

  const ranked = useMemo(() => {
    if (!machines) return [];
    return machines
      .map((m) => ({ machine: m, health: metrics[m.id] ?? null }))
      .sort((a, b) => {
        const sa = a.health ? computeScore(a.health, weights) : -1;
        const sb = b.health ? computeScore(b.health, weights) : -1;
        return sa - sb; // worst first — technician triage order
      });
  }, [machines, metrics, weights]);

  if (error) return <div className="mx-auto max-w-[1300px] px-6 py-6"><ErrorBox message={error} /></div>;
  if (!machines) return <Spinner />;

  return (
    <div className="mx-auto max-w-[1300px] px-6 py-6">
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-white">Machine Health</h1>
        <p className="mt-1 text-xs text-slate-500">
          Counters are evidence-based (log-derived). The score below is a{" "}
          <strong className="text-amber-300">configurable heuristic</strong> for triage
          prioritisation — <strong className="text-amber-300">not a definitive diagnosis</strong>.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-4">
        {/* Score configuration */}
        <Card title="Score configuration" className="lg:col-span-1">
          <label className="mb-3 block">
            <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Window</span>
            <select
              value={windowDays}
              onChange={(e) => setWindowDays(Number(e.target.value))}
              className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm"
            >
              {WINDOWS.map((d) => (
                <option key={d} value={d}>last {d} days</option>
              ))}
            </select>
          </label>
          <span className="mb-2 block text-[11px] uppercase tracking-wide text-slate-500">
            Component weights
          </span>
          <div className="space-y-3">
            {(Object.keys(weights) as (keyof Weights)[]).map((k) => (
              <label key={k} className="block">
                <span className="flex justify-between text-xs text-slate-400">
                  {WEIGHT_LABELS[k]}
                  <span className="font-mono text-slate-500">{weights[k]}</span>
                </span>
                <input
                  type="range"
                  min={0}
                  max={5}
                  step={1}
                  value={weights[k]}
                  onChange={(e) => setWeights((w) => ({ ...w, [k]: Number(e.target.value) }))}
                  className="mt-1 w-full accent-indigo-500"
                />
              </label>
            ))}
          </div>
          <button
            onClick={() => setWeights(DEFAULT_WEIGHTS)}
            className="mt-3 w-full rounded border border-slate-700 px-2 py-1.5 text-xs text-slate-400 hover:bg-slate-800"
          >
            Reset to defaults
          </button>
        </Card>

        {/* Fleet table */}
        <Card title={`Fleet (${machines.length})`} subtitle="Sorted worst-score-first for triage" className="lg:col-span-3">
          {ranked.length === 0 ? (
            <Empty>No machines registered — add machines in the Machines page.</Empty>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[900px] text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
                    <th className="pb-2">Score</th>
                    <th className="pb-2">Machine</th>
                    <th className="pb-2">Model</th>
                    <th className="pb-2 text-right">Txns</th>
                    <th className="pb-2 text-right">Fail %</th>
                    <th className="pb-2 text-right">Jams</th>
                    <th className="pb-2 text-right">HW err</th>
                    <th className="pb-2 text-right">Sensor</th>
                    <th className="pb-2 text-right">Unavail</th>
                    <th className="pb-2">Last activity</th>
                  </tr>
                </thead>
                <tbody>
                  {ranked.map(({ machine, health }) => {
                    const score = health ? computeScore(health, weights) : null;
                    return (
                      <tr key={machine.id} className="border-t border-slate-800/60">
                        <td className="py-2">
                          {score != null ? (
                            <Badge tone={scoreTone(score)} title="heuristic prioritisation aid — not a diagnosis">
                              {score}
                            </Badge>
                          ) : (
                            <span className="text-slate-600">—</span>
                          )}
                        </td>
                        <td className="py-2">
                          <span className="font-mono text-xs text-slate-200">{machine.serial_number}</span>
                          {machine.name && <div className="text-[11px] text-slate-500">{machine.name}</div>}
                        </td>
                        <td className="py-2 text-xs text-slate-400">
                          {health?.model_code ?? machine.machine_model?.code ?? "—"}
                        </td>
                        <td className="py-2 text-right text-xs text-slate-300">{health?.transactions_total ?? "—"}</td>
                        <td className="py-2 text-right text-xs">
                          {health ? (
                            <Badge tone={statusTone(health.failure_rate > 0.3 ? "FAILED" : "COMPLETED")}>
                              {(health.failure_rate * 100).toFixed(0)}%
                            </Badge>
                          ) : (
                            "—"
                          )}
                        </td>
                        <td className="py-2 text-right text-xs text-slate-300">{health?.jam_transactions ?? "—"}</td>
                        <td className="py-2 text-right text-xs text-slate-300">{health?.hardware_error_transactions ?? "—"}</td>
                        <td className="py-2 text-right text-xs text-slate-300">{health?.sensor_abnormalities ?? "—"}</td>
                        <td className="py-2 text-right text-xs text-slate-300">{health?.device_unavailable_events ?? "—"}</td>
                        <td className="py-2 text-xs text-slate-500">{fmtTime(health?.last_activity_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="mt-3 text-[11px] text-slate-600">
            Score = 100 × (1 − weighted mean of normalised stress components). Components are
            per-transaction rates derived from the same evidence as the counters shown. Adjust the
            weights to match your service priorities; the ranking updates live.{" "}
            <Link to="/machines" className="text-indigo-400 hover:underline">Manage machines →</Link>
          </p>
        </Card>
      </div>
    </div>
  );
}
