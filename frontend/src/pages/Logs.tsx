import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { ListResponse, LogFile, LogFileStatus, LogLine, ProcessingStatus } from "../types";
import StatusBadge, { isProcessing } from "../components/StatusBadge";
import { formatSize } from "../components/UploadDropzone";
import UploadDropzone from "../components/UploadDropzone";
import FileDetailDrawer from "../components/FileDetailDrawer";
import { PROCESSING_STATUSES } from "../types";

export default function Logs() {
  const [listing, setListing] = useState<ListResponse<LogFile> | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [selected, setSelected] = useState<LogFile | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const result = await api.listLogs({
        status: statusFilter || undefined,
        file_role: roleFilter || undefined,
        limit: 100,
      });
      setListing(result);
      setError("");
      // Keep the drawer content fresh while processing.
      if (selected) {
        const fresh = result.items.find((i) => i.id === selected.id);
        if (fresh) setSelected(fresh);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load logs");
    }
  }, [statusFilter, roleFilter, selected]);

  const anyProcessing = useMemo(
    () => (listing?.items ?? []).some((l) => isProcessing(l.status)),
    [listing],
  );

  useEffect(() => {
    load();
    const interval = anyProcessing ? 2000 : 10000;
    const timer = setInterval(load, interval);
    return () => clearInterval(timer);
  }, [load, anyProcessing]);

  return (
    <div className="mx-auto max-w-7xl space-y-6 px-8 py-8">
      <header>
        <h1 className="text-2xl font-semibold text-white">Logs</h1>
        <p className="mt-1 text-sm text-slate-400">
          Upload, extraction and processing status. Originals are immutable; raw lines are kept for evidence.
        </p>
      </header>

      <UploadDropzone onUploaded={load} />

      <section className="rounded-xl border border-slate-800 bg-slate-900/60">
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-5 py-3">
          <h2 className="text-sm font-semibold text-slate-200">
            Files <span className="ml-1 text-slate-500">({listing?.total ?? 0})</span>
          </h2>
          <div className="ml-auto flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200"
            >
              <option value="">All statuses</option>
              {PROCESSING_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              value={roleFilter}
              onChange={(e) => setRoleFilter(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1.5 text-xs text-slate-200"
            >
              <option value="">Uploads + extracted</option>
              <option value="upload">Uploads only</option>
              <option value="extracted">Extracted only</option>
            </select>
          </div>
        </div>

        {error && <div className="px-5 py-3 text-sm text-rose-400">{error}</div>}

        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-left text-[11px] uppercase tracking-wide text-slate-500">
                <th className="px-5 py-2.5 font-medium">File</th>
                <th className="px-3 py-2.5 font-medium">Type</th>
                <th className="px-3 py-2.5 font-medium">Size</th>
                <th className="px-3 py-2.5 font-medium">Checksum</th>
                <th className="px-3 py-2.5 font-medium">Source</th>
                <th className="px-3 py-2.5 font-medium">Model</th>
                <th className="px-3 py-2.5 font-medium">Status</th>
                <th className="px-5 py-2.5 font-medium">Uploaded</th>
              </tr>
            </thead>
            <tbody>
              {(listing?.items ?? []).map((log) => (
                <tr
                  key={log.id}
                  onClick={() => setSelected(log)}
                  className="cursor-pointer border-b border-slate-800/60 transition hover:bg-slate-800/40"
                >
                  <td className="max-w-64 px-5 py-2.5">
                    <div className="truncate font-medium text-slate-200">{log.original_filename}</div>
                    {log.original_path && (
                      <div className="truncate text-[11px] text-slate-500">zip:{log.original_path}</div>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[11px] text-slate-300">
                      {log.file_type}
                    </span>
                    {log.file_role === "extracted" && (
                      <span className="ml-1 text-[10px] text-slate-500">extracted</span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 text-slate-400">{formatSize(log.size_bytes)}</td>
                  <td className="px-3 py-2.5">
                    <span
                      className="font-mono text-[11px] text-slate-500"
                      title={`${log.checksum_sha256} (click to copy)`}
                      onClick={(e) => {
                        navigator.clipboard?.writeText(log.checksum_sha256);
                        e.stopPropagation();
                      }}
                    >
                      {log.checksum_sha256.slice(0, 10)}…
                    </span>
                  </td>
                  <td className="px-3 py-2.5">
                    {log.log_source ? (
                      <span className="inline-flex items-center gap-1">
                        <span className="rounded bg-indigo-500/15 px-1.5 py-0.5 font-mono text-[11px] text-indigo-300">
                          {log.log_source.code}
                        </span>
                        {log.log_source.confidence != null && (
                          <span className="text-[10px] text-slate-500">
                            {Math.round(log.log_source.confidence * 100)}%
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-slate-600">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-slate-400">
                    {log.machine_model_code ?? <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={log.status} />
                  </td>
                  <td className="whitespace-nowrap px-5 py-2.5 text-xs text-slate-500">
                    {new Date(log.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
              {listing && listing.items.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-5 py-10 text-center text-sm text-slate-500">
                    No log files match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {selected && (
        <FileDetailDrawer
          file={selected}
          onClose={() => setSelected(null)}
          onChanged={load}
        />
      )}
    </div>
  );
}

export type { LogFileStatus, LogLine, ProcessingStatus };
