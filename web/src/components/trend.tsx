export type TrendPoint = { value: number; created_at: string };

export type TrendProps = {
  points: TrendPoint[];
  baseline: number | null;
  /** True for checks where a higher value is worse (e.g. latency). Mirrors the
   * drift rule in nokware/drift.py, which inverts the 10%-relative comparison
   * for the same reason. */
  higherIsWorse?: boolean;
  /** Unit suffix for the aria-label, tooltip, and data-table values (e.g. "ms"). */
  unit?: string;
};

// A stat-tile-style trend sparkline: one de-emphasised line, one accent
// end-dot, per the dataviz skill's figure spec (marks-and-anatomy.md, "trend").
// Single series -> no legend box. The line stays neutral; only the end-dot
// (the current value) carries status color, so the reader's eye lands on
// "where are we now", not on a fully painted line.
export function Trend({ points, baseline, higherIsWorse = false, unit = "" }: TrendProps) {
  if (points.length < 2) {
    return <span className="text-xs text-neutral-400">not enough runs</span>;
  }

  const w = 220;
  const h = 48;
  const pad = 6;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const y = (v: number) =>
    max === min ? h / 2 : h - pad - ((v - min) / (max - min)) * (h - 2 * pad);
  const x = (i: number) => pad + (i / (points.length - 1)) * (w - 2 * pad);
  const d = vals.map((v, i) => `${i ? "L" : "M"}${x(i)},${y(v)}`).join(" ");

  const last = vals[vals.length - 1];
  const lastPoint = points[points.length - 1];
  const declining =
    baseline != null &&
    (higherIsWorse ? last > baseline * 1.1 : last < baseline * 0.9);

  const lineClass = declining
    ? "stroke-red-600 dark:stroke-red-400"
    : "stroke-neutral-400 dark:stroke-neutral-500";
  const dotClass = declining
    ? "fill-red-600 dark:fill-red-400"
    : "fill-emerald-600 dark:fill-emerald-500";

  const baselineNote =
    baseline != null ? `, 7-day baseline ${Math.round(baseline * 100) / 100}${unit}` : "";
  const label = `Trend over ${points.length} runs. Latest ${last}${unit}${baselineNote}${
    declining ? ". Declining beyond the drift threshold." : ""
  }`;

  return (
    <div className="inline-block align-top">
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full max-w-[220px]" role="img" aria-label={label}>
        <path
          d={d}
          fill="none"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={lineClass}
        />
        {/* surface ring: keeps the end-dot legible where it meets the line */}
        <circle cx={x(points.length - 1)} cy={y(last)} r="6" className="fill-white dark:fill-neutral-900" />
        <circle cx={x(points.length - 1)} cy={y(last)} r="4" className={dotClass}>
          <title>{`${lastPoint.created_at}: ${last}${unit}`}</title>
        </circle>
      </svg>
      <details className="mt-1">
        <summary className="cursor-pointer text-[11px] text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300">
          view values
        </summary>
        <table className="mt-1 w-full max-w-[220px] text-[11px] text-neutral-500">
          <tbody>
            {points.map((p, i) => (
              <tr key={i}>
                <td className="pr-2 tabular-nums">{p.created_at.slice(0, 10)}</td>
                <td className="text-right tabular-nums">
                  {p.value}
                  {unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}
