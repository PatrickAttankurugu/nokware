import type { ScoreRow } from "@/lib/db";

export type ScoreTileProps = {
  slug: string;
  title: string;
  blurb: string;
  rows: ScoreRow[];
};

// Renders whatever check rows a suite currently has -- the suite's check
// count is not fixed here (africapep, lexaura, and sentinel each carry a
// different number of checks and that number can change), so this always
// iterates `rows` rather than assuming a fixed set of check ids.
export function ScoreTile({ slug, title, blurb, rows }: ScoreTileProps) {
  const failing = rows.filter((r) => !r.passed).length;

  return (
    <a
      href={`/systems/${slug}`}
      className="rounded-lg border p-5 hover:border-neutral-400"
    >
      <h2 className="font-medium">{title}</h2>
      <p className="text-sm text-neutral-500">{blurb}</p>
      <ul className="mt-4 space-y-1 text-sm">
        {rows.map((r) => (
          <li key={r.check_id} className="flex justify-between">
            <span>{r.check_id}</span>
            <span className={r.passed ? "text-emerald-600" : "text-red-600"}>
              {r.value}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 text-xs text-neutral-400">
        {rows.length === 0
          ? "no results yet"
          : failing === 0
            ? "all checks passing"
            : `${failing} failing`}
      </p>
    </a>
  );
}
