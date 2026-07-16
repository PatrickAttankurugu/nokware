"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";
import Link from "next/link";

// Wraps every data page (/, /runs, /incidents, /systems/[slug]) that reads
// from lib/db.ts. Any failure to reach the ledger database -- not
// provisioned yet, a transient outage, a bad connection string -- throws at
// request time; without this boundary that surfaces as Next's bare
// framework 500 page. This renders a page that explains that in plain
// language instead. This boundary is intentionally kept even after Neon is
// provisioned: a database being briefly unreachable is a real failure mode,
// not just a pre-launch state, so there is nothing here to remove once
// NEON_DATABASE_URL is set.
export default function Error({
  error,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // reset is intentionally unused: retrying immediately would just repeat the
  // same failed connection attempt on a page that has no client-side state to lose
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-24">
      <h1 className="text-2xl font-semibold">The ledger database could not be reached.</h1>
      <p className="mt-4 text-neutral-600 dark:text-neutral-300">
        If this is a fresh deployment, the database may not be provisioned yet; see the{" "}
        <a
          href="https://github.com/PatrickAttankurugu/nokware#readme"
          className="underline"
        >
          README
        </a>
        .
      </p>
      <p className="mt-4 text-neutral-600 dark:text-neutral-300">
        The suites themselves already run against production APIs every night. See the{" "}
        <Link href="/methodology" className="underline">
          methodology page
        </Link>{" "}
        for exactly what each one checks and how scores publish once the database is reachable.
      </p>
    </main>
  );
}
