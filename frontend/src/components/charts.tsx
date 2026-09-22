// Dependency-free SVG charts for the analytics dashboard (Phase 9).

export interface Series {
  label: string;
  color: string;
  values: number[];
}

export function LineChart({
  labels,
  series,
  height = 180,
}: {
  labels: string[];
  series: Series[];
  height?: number;
}) {
  const width = 760;
  const padL = 34;
  const padR = 10;
  const padT = 10;
  const padB = 22;
  const innerW = width - padL - padR;
  const innerH = height - padT - padB;
  const maxV = Math.max(1, ...series.flatMap((s) => s.values));
  const n = Math.max(labels.length, 1);
  const x = (i: number) => padL + (n === 1 ? innerW / 2 : (i * innerW) / (n - 1));
  const y = (v: number) => padT + innerH - (v / maxV) * innerH;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img">
      {[0, 0.25, 0.5, 0.75, 1].map((f) => (
        <g key={f}>
          <line x1={padL} x2={width - padR} y1={y(maxV * f)} y2={y(maxV * f)} stroke="#1e293b" strokeWidth={1} />
          <text x={4} y={y(maxV * f) + 3} fill="#64748b" fontSize={9}>
            {Math.round(maxV * f)}
          </text>
        </g>
      ))}
      {series.map((s) => (
        <g key={s.label}>
          <polyline
            fill="none"
            stroke={s.color}
            strokeWidth={1.8}
            points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
          />
          {s.values.map((v, i) => (
            <circle key={i} cx={x(i)} cy={y(v)} r={2.2} fill={s.color}>
              <title>{`${s.label} · ${labels[i]}: ${v}`}</title>
            </circle>
          ))}
        </g>
      ))}
      {labels.map((l, i) =>
        i % Math.ceil(n / 8) === 0 ? (
          <text key={i} x={x(i)} y={height - 6} fill="#64748b" fontSize={9} textAnchor="middle">
            {l}
          </text>
        ) : null,
      )}
    </svg>
  );
}

export function BarChart({
  rows,
  formatValue,
}: {
  rows: { label: string; value: number; hint?: string }[];
  formatValue?: (v: number) => string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="space-y-1.5">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-xs" title={r.hint}>
          <span className="w-36 shrink-0 truncate text-slate-400" title={r.label}>
            {r.label}
          </span>
          <div className="h-3.5 flex-1 overflow-hidden rounded bg-slate-800/70">
            <div
              className="h-full rounded bg-indigo-500/70"
              style={{ width: `${(r.value / max) * 100}%` }}
            />
          </div>
          <span className="w-14 shrink-0 text-right font-mono text-slate-300">
            {formatValue ? formatValue(r.value) : r.value}
          </span>
        </div>
      ))}
    </div>
  );
}
