// Phase 7 — log viewer: virtualized raw-line display over the server-side
// lines endpoint. Browsing is windowed by absolute line number (only the
// visible chunk is fetched); search/filter/level run server-side and
// produce a match list; every jump lands on exact line numbers so evidence
// links from the transaction view land in context.

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { LogFile, LogLine } from "../types";
import { Badge, Card, ErrorBox, Spinner, fmtTime } from "../components/ui";

const ROW_H = 22; // px per rendered line
const CHUNK = 400; // lines fetched per chunk
const OVERSCAN = 30; // extra rows rendered above/below
const SEARCH_CAP = 5000; // max matches collected in search mode

export default function LogViewer() {
  const { fileId = "" } = useParams();
  const [sp, setSp] = useSearchParams();
  const focusLine = Number(sp.get("line") ?? 0) || null;

  const [file, setFile] = useState<LogFile | null>(null);
  const [totalLines, setTotalLines] = useState(0);
  const [chunks, setChunks] = useState<Map<number, LogLine[]>>(new Map());
  const [error, setError] = useState("");
  const [loadingFile, setLoadingFile] = useState(true);

  // toolbar state
  const [qDraft, setQDraft] = useState(sp.get("q") ?? "");
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [level, setLevel] = useState(sp.get("level") ?? "");
  const [txnDraft, setTxnDraft] = useState(sp.get("txn") ?? "");
  const [source, setSource] = useState("");
  const [sources, setSources] = useState<string[]>([]);
  const [jumpLine, setJumpLine] = useState("");
  const [jumpTs, setJumpTs] = useState("");
  const [context, setContext] = useState(25);

  // search mode
  const [matches, setMatches] = useState<LogLine[] | null>(null);
  const [searching, setSearching] = useState(false);

  // virtual scroll
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewH, setViewH] = useState(640);
  const pendingFocus = useRef<number | null>(focusLine);

  // ---- load file metadata -------------------------------------------------
  useEffect(() => {
    let cancelled = false;
    setLoadingFile(true);
    setChunks(new Map());
    setMatches(null);
    api
      .getLog(fileId)
      .then((f) => {
        if (cancelled) return;
        setFile(f);
        setLoadingFile(false);
        return api.getLogLines(fileId, { limit: 1 }).then((r) => {
          if (!cancelled) setTotalLines(r.total);
        });
      })
      .catch((e) => !cancelled && (setError(e.message ?? String(e)), setLoadingFile(false)));
    return () => {
      cancelled = true;
    };
  }, [fileId]);

  // discover source codes from the first chunk
  useEffect(() => {
    if (!file) return;
    api.getLogLines(fileId, { limit: CHUNK }).then((r) => {
      const codes = Array.from(new Set(r.items.map((l) => l.source).filter(Boolean))) as string[];
      setSources(codes);
    }).catch(() => {});
  }, [file, fileId]);

  const searchMode = Boolean(q || level || source);

  // ---- chunk fetching (browse mode) ---------------------------------------
  const ensureChunks = useCallback(
    (first: number, last: number) => {
      if (!file) return;
      const cFirst = Math.floor(Math.max(0, first - 1 - OVERSCAN) / CHUNK);
      const cLast = Math.floor(Math.min(totalLines - 1, last - 1 + OVERSCAN) / CHUNK);
      for (let c = cFirst; c <= cLast; c++) {
        if (chunks.has(c)) continue;
        const idx = c;
        chunks.set(idx, []); // reserve — prevents duplicate fetches
        api
          .getLogLines(fileId, { line_from: idx * CHUNK + 1, line_to: (idx + 1) * CHUNK, limit: CHUNK })
          .then((r) =>
            setChunks((prev) => {
              const next = new Map(prev);
              next.set(idx, r.items);
              return next;
            }),
          )
          .catch(() =>
            setChunks((prev) => {
              const next = new Map(prev);
              next.delete(idx);
              return next;
            }),
          );
      }
    },
    [file, fileId, chunks, totalLines],
  );

  const lineAt = useCallback(
    (n: number): LogLine | undefined => {
      const c = Math.floor((n - 1) / CHUNK);
      const arr = chunks.get(c);
      if (!arr || arr.length === 0) return undefined;
      return arr.find((l) => l.line_number === n);
    },
    [chunks],
  );

  // ---- virtual window ------------------------------------------------------
  const firstVisible = Math.max(1, Math.floor(scrollTop / ROW_H) + 1);
  const lastVisible = Math.min(totalLines, Math.ceil((scrollTop + viewH) / ROW_H) + 1);

  useEffect(() => {
    if (!searchMode && totalLines > 0) ensureChunks(firstVisible, lastVisible);
  }, [searchMode, totalLines, firstVisible, lastVisible, ensureChunks]);

  // centre on the focus line once the container exists
  useEffect(() => {
    if (pendingFocus.current && scrollRef.current && totalLines > 0) {
      const target = pendingFocus.current;
      pendingFocus.current = null;
      scrollRef.current.scrollTop = Math.max(0, (target - 1) * ROW_H - viewH / 2 + ROW_H / 2);
    }
  }, [totalLines, viewH]);

  // ---- search --------------------------------------------------------------
  const runSearch = useCallback(
    async (overrides?: { q?: string; level?: string; source?: string }) => {
      const qq = overrides?.q ?? q;
      const lv = overrides?.level ?? level;
      const so = overrides?.source ?? source;
      if (!qq && !lv && !so) {
        setMatches(null);
        return;
      }
      setSearching(true);
      const collected: LogLine[] = [];
      let offset = 0;
      try {
        while (offset < SEARCH_CAP) {
          const r = await api.getLogLines(fileId, {
            q: qq || undefined,
            level: lv || undefined,
            limit: 500,
            offset,
          });
          collected.push(...r.items.filter((l) => !so || l.source === so));
          if (collected.length >= SEARCH_CAP || offset + r.items.length >= r.total) break;
          offset += 500;
        }
      } catch (e) {
        setError((e as Error).message ?? String(e));
      }
      setMatches(collected);
      setSearching(false);
    },
    [fileId, q, level, source],
  );

  useEffect(() => {
    if (searchMode && file) void runSearch();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, level, source, file]);

  const jumpTo = (line: number, newContext?: Record<string, string>) => {
    const next = new URLSearchParams(newContext ?? sp);
    next.set("line", String(line));
    setSp(next, { replace: true });
    pendingFocus.current = line;
    setMatches(null);
    setQ(""); setQDraft(""); setLevel(""); setSource("");
    if (scrollRef.current) {
      scrollRef.current.scrollTop = Math.max(0, (line - 1) * ROW_H - viewH / 2 + ROW_H / 2);
      pendingFocus.current = null;
    }
  };

  const jumpTimestamp = async () => {
    if (!jumpTs) return;
    const r = await api.getLogLines(fileId, { ts_from: new Date(jumpTs).toISOString(), limit: 1 });
    if (r.items.length > 0) jumpTo(r.items[0].line_number);
  };

  const hl = (text: string): (string | JSX.Element)[] => {
    if (!q || q.length < 2) return [text];
    const parts: (string | JSX.Element)[] = [];
    const lower = text.toLowerCase();
    const needle = q.toLowerCase();
    let i = 0;
    while (i < text.length) {
      const at = lower.indexOf(needle, i);
      if (at === -1) {
        parts.push(text.slice(i));
        break;
      }
      if (at > i) parts.push(text.slice(i, at));
      parts.push(
        <mark key={at} className="rounded bg-amber-500/30 px-0.5 text-amber-200">
          {text.slice(at, at + needle.length)}
        </mark>,
      );
      i = at + needle.length;
    }
    return parts;
  };

  if (loadingFile) return <Spinner label="Loading log file…" />;
  if (error || !file) {
    return <div className="mx-auto max-w-[1300px] px-6 py-6"><ErrorBox message={error || "Log file not found"} /></div>;
  }

  const rows: ReactNode[] = [];
  if (!searchMode && totalLines > 0) {
    const start = Math.max(1, firstVisible - OVERSCAN);
    const end = Math.min(totalLines, lastVisible + OVERSCAN);
    for (let n = start; n <= end; n++) {
      const line = lineAt(n);
      const focused = focusLine === n;
      rows.push(
        <div
          key={n}
          className={`flex items-baseline gap-3 px-3 font-mono text-[12px] leading-[22px] ${
            focused ? "bg-indigo-600/20 ring-1 ring-inset ring-indigo-500/40" : "hover:bg-slate-900/60"
          }`}
          style={{ height: ROW_H }}
        >
          <span className="w-14 shrink-0 select-none text-right text-slate-600">{n}</span>
          <span className="whitespace-pre break-all text-slate-300">
            {line ? hl(line.raw_text) : <span className="text-slate-700">…</span>}
          </span>
        </div>,
      );
    }
  }

  return (
    <div className="mx-auto max-w-[1500px] px-6 py-6">
      <header className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <h1 className="truncate text-lg font-semibold text-white">{file.original_filename}</h1>
          <p className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
            {file.machine_model_code && <Badge tone="violet">{file.machine_model_code}</Badge>}
            {file.log_source?.code && <Badge tone="sky">{file.log_source.code}</Badge>}
            <Badge tone={file.status === "COMPLETED" ? "emerald" : file.status === "PARTIAL" ? "yellow" : statusToneSafe(file.status)}>
              {file.status}
            </Badge>
            <span>{totalLines.toLocaleString()} lines</span>
            <span>{(file.size_bytes / 1024).toFixed(1)} KB</span>
            <span>imported {fmtTime(file.created_at)}</span>
            {file.parent_file_id && (
              <Link className="text-indigo-400 hover:underline" to="/logs">
                ← upload bundle
              </Link>
            )}
          </p>
        </div>
        <Link to="/logs" className="text-xs text-indigo-400 hover:underline">all logs →</Link>
      </header>

      {/* Toolbar */}
      <div className="mb-3 flex flex-wrap items-end gap-2 rounded-xl border border-slate-800 bg-slate-900/60 p-3">
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Search (server-side)</span>
          <input
            value={qDraft}
            onChange={(e) => setQDraft(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && (setQ(qDraft), setMatches(null))}
            placeholder="text in raw lines…"
            className={inputCls + " w-64"}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Level</span>
          <select value={level} onChange={(e) => setLevel(e.target.value)} className={inputCls + " w-28"}>
            <option value="">any</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Source</span>
          <select value={source} onChange={(e) => setSource(e.target.value)} className={inputCls + " w-32"}>
            <option value="">any</option>
            {sources.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Transaction</span>
          <input
            value={txnDraft}
            onChange={(e) => setTxnDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && txnDraft) {
                setQDraft(txnDraft);
                setQ(txnDraft);
              }
            }}
            placeholder="e.g. T-8803 → search"
            className={inputCls + " w-40"}
          />
        </label>
        <button
          onClick={() => { setQ(qDraft); setMatches(null); }}
          className="rounded bg-indigo-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-indigo-500"
        >
          Search
        </button>
        <button
          onClick={() => { setQ(""); setQDraft(""); setLevel(""); setSource(""); setMatches(null); setSp({}, { replace: true }); }}
          className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
        >
          Clear
        </button>

        <span className="mx-1 h-8 w-px bg-slate-800" />

        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Jump to line</span>
          <input
            type="number"
            min={1}
            value={jumpLine}
            onChange={(e) => setJumpLine(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && jumpLine && jumpTo(Number(jumpLine))}
            className={inputCls + " w-28"}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Jump to timestamp</span>
          <input
            type="datetime-local"
            value={jumpTs}
            onChange={(e) => setJumpTs(e.target.value)}
            className={inputCls + " w-56"}
          />
        </label>
        <button onClick={jumpTimestamp} className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
          Go
        </button>
        <label className="block">
          <span className="mb-1 block text-[11px] uppercase tracking-wide text-slate-500">Context ± lines</span>
          <input
            type="number" min={5} max={200}
            value={context}
            onChange={(e) => setContext(Number(e.target.value) || 25)}
            className={inputCls + " w-20"}
          />
        </label>
        {focusLine && (
          <button
            onClick={() => jumpTo(Math.max(1, focusLine - context))}
            className="rounded border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800"
            title={`show lines ${Math.max(1, focusLine - context)}–${focusLine + context}`}
          >
            ± {context} around line {focusLine}
          </button>
        )}
      </div>

      {error && <div className="mb-3"><ErrorBox message={error} /></div>}

      {/* Content: search results OR virtualized browse */}
      {searchMode ? (
        <Card title={searching ? "Searching…" : `Matches (${matches?.length ?? 0}${matches && matches.length >= SEARCH_CAP ? "+" : ""})`}>
          {searching ? (
            <Spinner label="Searching server-side…" />
          ) : matches && matches.length > 0 ? (
            <ul className="divide-y divide-slate-800/60">
              {matches.map((m) => (
                <li key={m.id} className="flex items-start gap-3 py-1.5">
                  <button
                    onClick={() => jumpTo(m.line_number)}
                    className="shrink-0 rounded border border-slate-700 px-2 py-0.5 font-mono text-[11px] text-indigo-300 hover:bg-slate-800"
                    title="open in browse view with context"
                  >
                    L{m.line_number}
                  </button>
                  <span className="whitespace-pre break-all font-mono text-[12px] text-slate-300">
                    {hl(m.raw_text)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-6 text-center text-sm text-slate-500">No lines match.</p>
          )}
        </Card>
      ) : (
        <div
          ref={(el) => {
            scrollRef.current = el;
            if (el && Math.abs(el.clientHeight - viewH) > 4) setViewH(el.clientHeight);
          }}
          onScroll={(e) => setScrollTop((e.target as HTMLDivElement).scrollTop)}
          className="h-[calc(100vh-280px)] min-h-[420px] overflow-auto rounded-xl border border-slate-800 bg-slate-950"
        >
          <div style={{ height: totalLines * ROW_H, position: "relative" }}>
            <div style={{ position: "absolute", top: (firstVisible - 1 - Math.min(OVERSCAN, firstVisible - 1)) * ROW_H }}>
              {rows}
            </div>
          </div>
        </div>
      )}
      <p className="mt-2 text-[11px] text-slate-600">
        Raw lines are immutable evidence — the viewer never modifies them. Browsing fetches only
        the visible window (virtualized); search runs entirely server-side.
      </p>
    </div>
  );
}

const inputCls =
  "rounded border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-200 outline-none focus:border-indigo-500";

function statusToneSafe(status: string): string {
  if (status === "FAILED") return "rose";
  if (["UPLOADED", "VALIDATING", "EXTRACTING", "IDENTIFYING", "PARSING"].includes(status)) return "sky";
  return "slate";
}
