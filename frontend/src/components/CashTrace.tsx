// Phase 7 — cash trace: per-note state transitions with explicit final-state
// classification (STORED / RETURNED / REJECTED / UNKNOWN). States are shown
// verbatim from the logs; the class badge is a display grouping only.

import { Link } from "react-router-dom";
import type { CashMovement } from "../types";
import {
  Badge,
  CASH_CLASS_TONE,
  RawLine,
  classifyCashState,
  fmtTime,
  type CashClass,
} from "./ui";

export default function CashTrace({
  movements,
  finalCashState,
}: {
  movements: CashMovement[];
  finalCashState: string;
}) {
  if (movements.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No cash movements recorded for this transaction (final state:{" "}
        <span className="text-slate-300">{finalCashState}</span>).
      </p>
    );
  }

  const finalClass = classifyCashState(finalCashState);

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
        Final cash state:
        <Badge tone={CASH_CLASS_TONE[finalClass]}>{finalCashState || "UNKNOWN"}</Badge>
        <span className="text-slate-600">— class: {finalClass}</span>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[860px] text-sm">
          <thead>
            <tr className="text-left text-[11px] uppercase tracking-wide text-slate-500">
              <th className="pb-2">Note</th>
              <th className="pb-2">Denomination</th>
              <th className="pb-2">Transition</th>
              <th className="pb-2">State class</th>
              <th className="pb-2">Timestamp</th>
              <th className="pb-2">Device</th>
              <th className="pb-2">Destination</th>
              <th className="pb-2 text-right">Confidence</th>
              <th className="pb-2">Evidence</th>
            </tr>
          </thead>
          <tbody>
            {movements.map((m, i) => {
              const cls = classifyCashState(m.to_state);
              const info = (m.note_info ?? {}) as Record<string, unknown>;
              const denom = info.denomination ?? info.denom ?? info.value;
              const destination =
                (info.destination as string) ??
                (info.cassette as string) ??
                (info.position as string) ??
                m.to_state;
              return (
                <MovementRow key={i} m={m} cls={cls} denom={denom} destination={destination} />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function MovementRow({
  m,
  cls,
  denom,
  destination,
}: {
  m: CashMovement;
  cls: CashClass;
  denom: unknown;
  destination: string;
}) {
  return (
    <>
      <tr className="border-t border-slate-800/60 align-top">
        <td className="py-2 font-mono text-xs text-slate-300">{m.note_id ?? "—"}</td>
        <td className="py-2 text-slate-400">{denom != null ? String(denom) : "—"}</td>
        <td className="py-2 font-mono text-xs text-slate-400">
          {m.from_state} <span className="text-slate-600">→</span> {m.to_state}
        </td>
        <td className="py-2">
          <Badge tone={CASH_CLASS_TONE[cls]}>{cls}</Badge>
        </td>
        <td className="py-2 text-slate-400">{fmtTime(m.timestamp)}</td>
        <td className="py-2 text-slate-400">{m.device ?? "—"}</td>
        <td className="py-2 text-slate-400">{destination}</td>
        <td className="py-2 text-right font-mono text-xs text-slate-400">
          {(m.confidence * 100).toFixed(0)}%
        </td>
        <td className="py-2 text-[11px] text-indigo-400">
          {m.log_file_id && m.line_number != null ? (
            <Link className="hover:underline" to={`/logs/${m.log_file_id}?line=${m.line_number}`}>
              line {m.line_number} ↗
            </Link>
          ) : (
            "—"
          )}
        </td>
      </tr>
      <tr className="border-t-0">
        <td colSpan={9} className="pb-2 pt-0">
          <details>
            <summary className="cursor-pointer select-none text-[11px] text-slate-600 hover:text-slate-400">
              raw evidence
            </summary>
            <RawLine text={m.raw_text} />
          </details>
        </td>
      </tr>
    </>
  );
}
