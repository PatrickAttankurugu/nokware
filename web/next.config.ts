import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  // Pin the workspace root to this app. Without this, Next.js searches
  // upward for lockfiles and can pick up an unrelated one (e.g. a stray
  // package-lock.json in the user's home directory), which otherwise
  // produces a spurious "inferred workspace root" warning on every build.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
