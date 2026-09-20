import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { LogFile, LogFileStatus, LogLine } from "../types";
import StatusBadge from "./StatusBadge";
import { formatSize } from "./UploadDropzone";

const LEVEL_COLORS: Record<string, string> = {
  ERROR: "text-rose-400",
  CRITICAL: "text-rose-400",
  FATAL: "text-rose-400",
  WARNING: "text-amber-400",
  INFO: "text-emerald-400",
  DEBUG: "text-slate-500",
  TRACE: "text-slate-600",
};

export default function FileDetailDrawer({
  file,
  onClose,
  onChanged,
}: {
  file: LogFile;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [status, setStatus] = useState<LogFileStatus | null>(null);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [linesTotal, setLinesTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [refreshTick, setRefreshTick] = useState(0);
  const PAGE_SIZE = 100;

  useEffect(() => {
    setPage(0);
  }, [file.id]);

  useEffect(() => {
    let cancelled = false;
    api.getLogStatus(file.id).then((s) => !cancelled && setStatus(s)).catch(() => {});
    api
      .getLogLines(file.id, PAGE_SIZE, page * PAGE_SIZE)
      .then((res) => {
        if (cancelled) return;
        setLines(res.items);
        setLinesTotal(res.total);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [file.id, page, refreshTick]);

  // Poll while the file is still processing.
  const processing = ["UPLOADED", "VALIDATING", "EXTRACTING", "IDENTIFYING", "PARSING"].includes(
    file.status,
  );
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(() => {
      onChanged();
      setRefreshTick((t) => t + 1);
    }, 2000);
    return () => clearInterval(timer);
  }, [processing, onChanged]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-2xl flex-col overflow-y-auto border-l border-slate-800 bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="sticky top-0 flex items-start justify-between gap-4 border-b border-slate-800 bg-slate-900 px-6 py-4">
          <div className="min-w-0">
            <h2 className="truncate text-lg font-semibold text-white">{file.original_filename}</h2>
            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-slate-400">
              <StatusBadge status={file.status} />
              {file.log_source && (
                <span className="rounded bg-indigo-500/15 px-1.5 py-0.5 font-mono text-indigo-300">
                  {file.log_source.code}
                  {file.log_source.confidence != null && ` · ${Math.round(file.log_source.confidence * 100)}%`}
                </span>
              )}
              {file.machine_model_code && (
                <span className="rounded bg-slate-800 px-1.5 py-0.5">{file.machine_model_code}</span>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white"
            aria-label="Close"
          >
            ✕
          </button>
        </div>

        <div className="space-y-6 px-6 py-5 text-sm">
          {file.status_message && (
            <div
              className={`rounded-lg border px-4 py-2.5 ${
                file.status === "FAILED"
                  ? "border-rose-500/30 bg-rose-500/10 text-rose-300"
                  : "border-slate-700 bg-slate-800/50 text-slate-300"
              }`}
            >
              {file.status_message}
            </div>
          )}

          <section>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Metadata</h3>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5">
              <Meta label="File ID" value={file.id} mono />
              <Meta label="Type / role" value={`${file.file_type} · ${file.file_role}`} />
              <Meta label="Size" value={formatSize(file.size_bytes)} />
              <Meta label="Lines" value={file.line_count != null ? String(file.line_count) : "—"} />
              <Meta label="Parser" value={file.parser_code ? `${file.parser_code}@${file.parser_version}` : "—"} />
              <Meta label="Duplicate of" value={file.duplicate_of_id ? file.duplicate_of_id.slice(0, 8) : "—"} mono />
              <Meta label="Checksum" value={file.checksum_sha256} mono wide />
              {file.original_path && <Meta label="Path in ZIP" value={file.original_path} mono wide />}
              {file.parent_file_id && <Meta label="Source ZIP" value={file.parent_file_id} mono wide />}
            </dl>
          </section>

          {status && status.files.length > 0 && (
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Extracted files ({status.files.length})
              </h3>
              <ul className="space-y-1.5">
                {status.files.map((child) => (
                  <li
                    key={child.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-800/40 px-3 py-2"
                  >
                    <span className="min-w-0 flex-1 truncate text-slate-300">{child.original_filename}</span>
                    <span className="shrink-0 text-xs text-slate-500">
                      {child.line_count != null ? `${child.line_count} ln` : ""}
                    </span>
                    <StatusBadge status={child.status} />
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                Raw lines {linesTotal > 0 && <span className="text-slate-600">({linesTotal})</span>}
              </h3>
              {linesTotal > PAGE_SIZE && (
                <div className="flex items-center gap-2 text-xs">
                  <button
                    disabled={page === 0}
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800 disabled:opacity-30"
                  >
                    ← Prev
                  </button>
                  <span className="text-slate-500">
                    {page + 1} / {Math.ceil(linesTotal / PAGE_SIZE)}
                  </span>
                  <button
                    disabled={(page + 1) * PAGE_SIZE >= linesTotal}
                    onClick={() => setPage((p) => p + 1)}
                    className="rounded px-2 py-1 text-slate-400 hover:bg-slate-800 disabled:opacity-30"
                  >
                    Next →
                  </button>
                </div>
              )}
            </div>
            {lines.length === 0 ? (
              <p className="rounded-lg border border-slate-800 bg-slate-800/30 px-4 py-6 text-center text-xs text-slate-500">
                {processing ? "Lines will appear once parsing completes…" : "No stored lines for this file."}
              </p>
            ) : (
              <div className="overflow-hidden rounded-lg border border-slate-800">
                <table className="w-full text-left font-mono text-[11px]">
                  <tbody>
                    {lines.map((line) => (
                      <tr key={line.id} className="border-b border-slate-800/60 last:border-0">
                        <td className="w-10 px-2 py-1 text-right text-slate-600">{line.line_number}</td>
                        <td className="w-36 px-2 py-1 text-slate-500">
                          {line.timestamp ? new Date(line.timestamp).toISOString().replace("T", " ").slice(0, 19) : ""}
                        </td>
                        <td className={`w-14 px-2 py-1 ${LEVEL_COLORS[line.level ?? ""] ?? "text-slate-600"}`}>
                          {line.level ?? ""}
                        </td>
                        <td className="px-2 py-1 text-slate-300 break-all">{line.raw_text}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function Meta({ label, value, mono, wide }: { label: string; value: string; mono?: boolean; wide?: boolean }) {
  return (
    <div className={wide ? "col-span-2 flex justify-between gap-4" : "flex justify-between gap-4"}>
      <dt className="shrink-0 text-slate-500">{label}</dt>
      <dd className={`truncate text-right text-slate-300 ${mono ? "font-mono text-xs" : ""}`} title={value}>
        {value}
      </dd>
    </div>
  );
}
