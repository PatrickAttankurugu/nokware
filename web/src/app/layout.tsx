import type { Metadata } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Nokware",
  description: "A public reliability ledger for production AI systems.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <header className="border-b">
          <nav className="mx-auto flex max-w-5xl items-center gap-6 px-6 py-4 text-sm">
            <Link href="/" className="font-mono font-semibold tracking-tight">
              Nokware
            </Link>
            <Link href="/incidents" className="text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100">
              Incidents
            </Link>
            <Link href="/runs" className="text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100">
              Runs
            </Link>
            <Link href="/methodology" className="text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100">
              Methodology
            </Link>
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
