"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";
import Link from "next/link";

// Wraps every data page (/, /runs, /incidents, /systems/[slug]) that reads
// from lib/db.ts. NEON_DATABASE_URL is not provisioned yet, so those pages
// throw at request time; without this boundary that surfaces as Next's bare
// framework 500 page. This renders a page that explains why in plain
// language instead. Once Neon is provisioned this boundary stops firing on
// its own -- there is nothing here to remove.
export default function Error({
  error,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  // reset is intentionally unused: missing NEON_DATABASE_URL is not a transient condition
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto max-w-2xl px-6 py-24">
      <h1 className="text-2xl font-semibold">Database not configured yet</h1>
      <p className="mt-4 text-neutral-600 dark:text-neutral-300">
        This page reads live scores from Nokware&apos;s database, which is not provisioned yet.
        The nightly loop currently runs in dry-run mode and does not persist results, so there is
        nothing to show here until that lands.
      </p>
      <p className="mt-4 text-neutral-600 dark:text-neutral-300">
        The suites themselves already run against production APIs every night. See the{" "}
        <Link href="/methodology" className="underline">
          methodology page
        </Link>{" "}
        for exactly what each one checks and how scores will be published once the database is
        live.
      </p>
    </main>
  );
}
