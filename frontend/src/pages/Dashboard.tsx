import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Health, LogFile, Machine, MachineModel } from "../types";
import StatCard from "../components/StatCard";
import StatusBadge from "../components/StatusBadge";
import { formatSize } from "../components/UploadDropzone";

export default function Dashboard() {
  const [health, setHealth] = useState<Health | null>(null);
  const [logs, setLogs] = useState<LogFile[]>([]);
  const [models, setModels] = useState<MachineModel[]>([]);
  const [machines, setMachines] = useState<Machine[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const load = () => {
      Promise.all([
        api.health().catch(() => null),
        api.listLogs({ limit: 200 }).catch(() => null),
        api.listModels().catch(() => null),
        api.listMachines().catch(() => null),
      ])
        .then(([h, l, m, f]) => {
          if (h) setHealth(h);
          if (l) setLogs(l.items);
          if (m) setModels(m);
          if (f) setMachines(f.items);
          if (!l) setError("Backend not reachable — is it running?");
          else setError("");
        });
    };
    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  const completed = logs.filter((l) => l.status === "COMPLETED").length;
  const processing = logs.filter((l) =>
    ["UPLOADED", "VALIDATING", "EXTRACTING", "IDENTIFYING", "PARSING"].includes(l.status),
  ).length;
  const failed = logs.filter((l) => l.status === "FAILED" || l.status === "PARTIAL").length;
  const totalBytes = logs.reduce((acc, l) => acc + l.size_bytes, 0);

  const bySource = new Map<string, number>();
  for (const log of logs) {
    const code = log.log_source?.code ?? "unknown";
    bySource.set(code, (bySource.get(code) ?? 0) + 1);
  }

  return (
    <div className="mx-auto max-w-6xl space-y-6 px-8 py-8">
      <header>
        <h1 className="text-2xl font-semibold text-white">Dashboard</h1>
        <p className="mt-1 text-sm text-slate-400">
          Foundation status — uploads, safe extraction, raw storage, parser & model registry.
        </p>
      </header>

      {error && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatCard label="Uploads" value={logs.length} hint={`${formatSize(totalBytes)} stored`} />
        <StatCard label="Completed" value={completed} accent="emerald" />
        <StatCard label="Processing" value={processing} accent="amber" />
        <StatCard label="Failed / partial" value={failed} accent="rose" />
        <StatCard
          label="Fleet"
          value={machines.length}
          hint={`${models.filter((m) => m.is_active).length}/${models.length} models active`}
          accent="slate"
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <section className="lg:col-span-2 rounded-xl border border-slate-800 bg-slate-900/60">
          <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
            <h2 className="text-sm font-semibold text-slate-200">Recent uploads</h2>
            <Link to="/logs" className="text-xs text-indigo-400 hover:text-indigo-300">
              View all →
            </Link>
          </div>
          {logs.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-slate-500">
              No uploads yet — head to <Link to="/logs" className="text-indigo-400">Logs</Link> to upload your first log file.
            </p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {logs.slice(0, 8).map((log) => (
                  <tr key={log.id} className="border-b border-slate-800/60 last:border-0">
                    <td className="max-w-0 px-5 py-2.5">
                      <div className="truncate text-slate-200">{log.original_filename}</div>
                      <div className="text-xs text-slate-500">
                        {log.file_role === "extracted" ? `from ZIP · ${log.original_path}` : log.file_type}
                        {log.line_count != null && ` · ${log.line_count} lines`}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 text-right text-xs text-slate-400">
                      {new Date(log.created_at).toLocaleString()}
                    </td>
                    <td className="px-5 py-2.5 text-right">
                      <StatusBadge status={log.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="space-y-6">
          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <h2 className="text-sm font-semibold text-slate-200">Detected sources</h2>
            {bySource.size === 0 ? (
              <p className="mt-3 text-xs text-slate-500">No sources detected yet.</p>
            ) : (
              <ul className="mt-3 space-y-2">
                {[...bySource.entries()]
                  .sort((a, b) => b[1] - a[1])
                  .map(([code, count]) => (
                    <li key={code} className="flex items-center justify-between text-sm">
                      <span className="rounded bg-slate-800 px-2 py-0.5 font-mono text-xs text-slate-300">
                        {code}
                      </span>
                      <span className="text-slate-400">{count}</span>
                    </li>
                  ))}
              </ul>
            )}
          </div>

          <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-5">
            <h2 className="text-sm font-semibold text-slate-200">System</h2>
            <dl className="mt-3 space-y-1.5 text-sm">
              <Row label="Backend" value={health ? health.status : "unreachable"} />
              <Row label="Database" value={health?.database ? "connected" : "unknown"} />
              <Row label="Queue" value={health?.queue ?? "—"} />
              <Row label="Version" value={health?.version ?? "—"} />
            </dl>
          </div>
        </section>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-slate-300">{value}</dd>
    </div>
  );
}
