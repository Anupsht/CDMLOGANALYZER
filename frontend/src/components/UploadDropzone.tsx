import { useCallback, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { LogFileCreateResult } from "../types";

interface UploadJob {
  key: string;
  name: string;
  size: number;
  progress: number;
  state: "uploading" | "done" | "error";
  message?: string;
  result?: LogFileCreateResult;
}

const ALLOWED = [".txt", ".log", ".csv", ".json", ".zip"];

export default function UploadDropzone({ onUploaded }: { onUploaded: () => void }) {
  const [dragging, setDragging] = useState(false);
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  const startUpload = useCallback(
    (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
        const key = `${file.name}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
        if (!ALLOWED.includes(ext)) {
          setJobs((prev) => [
            { key, name: file.name, size: file.size, progress: 0, state: "error", message: `Unsupported type "${ext || "(none)"}"` },
            ...prev,
          ]);
          continue;
        }
        setJobs((prev) => [{ key, name: file.name, size: file.size, progress: 0, state: "uploading" }, ...prev]);
        api
          .uploadLog(file, {
            onProgress: (pct) =>
              setJobs((prev) => prev.map((j) => (j.key === key ? { ...j, progress: pct } : j))),
          })
          .then((result) => {
            setJobs((prev) =>
              prev.map((j) =>
                j.key === key
                  ? {
                      ...j,
                      state: "done",
                      progress: 100,
                      result,
                      message: result.is_duplicate ? "Duplicate of an earlier upload" : undefined,
                    }
                  : j,
              ),
            );
            onUploaded();
          })
          .catch((err: ApiError) => {
            setJobs((prev) =>
              prev.map((j) => (j.key === key ? { ...j, state: "error", message: err.message } : j)),
            );
          });
      }
    },
    [onUploaded],
  );

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) startUpload(e.dataTransfer.files);
        }}
        onClick={() => inputRef.current?.click()}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition ${
          dragging
            ? "border-indigo-400 bg-indigo-500/10"
            : "border-slate-700 bg-slate-900/40 hover:border-slate-500"
        }`}
      >
        <div className="text-3xl">⇪</div>
        <div className="mt-2 text-sm font-medium text-slate-200">
          Drop log files or ZIP archives here, or click to browse
        </div>
        <div className="mt-1 text-xs text-slate-500">
          Supported: .txt .log .csv .json .zip — originals are preserved and checksummed
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ALLOWED.join(",")}
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.length) startUpload(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {jobs.length > 0 && (
        <ul className="space-y-2">
          {jobs.map((job) => (
            <li
              key={job.key}
              className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-2.5 text-sm"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium text-slate-200">{job.name}</span>
                  <span className="shrink-0 text-xs text-slate-500">{formatSize(job.size)}</span>
                </div>
                {job.state === "uploading" && (
                  <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                    <div
                      className="h-full rounded-full bg-indigo-500 transition-all"
                      style={{ width: `${job.progress}%` }}
                    />
                  </div>
                )}
                {job.state === "done" && (
                  <div className="mt-0.5 text-xs text-emerald-400">
                    Uploaded · {job.result?.status}
                    {job.message && <span className="text-amber-400"> · {job.message}</span>}
                    {job.result?.checksum_sha256 && (
                      <span className="text-slate-500">
                        {" "}
                        · sha256 {job.result.checksum_sha256.slice(0, 12)}…
                      </span>
                    )}
                  </div>
                )}
                {job.state === "error" && (
                  <div className="mt-0.5 text-xs text-rose-400">{job.message}</div>
                )}
              </div>
              <button
                onClick={() => setJobs((prev) => prev.filter((j) => j.key !== job.key))}
                className="shrink-0 rounded p-1 text-slate-500 hover:bg-slate-800 hover:text-slate-300"
                aria-label="Dismiss"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
