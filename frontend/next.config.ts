import type { NextConfig } from "next";

// /api/* requests are proxied to the backend by the catch-all route handler at
// src/app/api/[...path]/route.ts, which reads BACKEND_URL at request time.
// Do NOT add rewrites for /api/* here — next.config is evaluated at build time,
// so any URL baked in here ignores the runtime BACKEND_URL env var.

// `output: "standalone"` is required by frontend/Dockerfile, which copies
// .next/standalone. Vercel builds Next.js natively and does not want it, so it
// is enabled only when DOCKER_BUILD=1 (set in the Dockerfile builder stage).
const nextConfig: NextConfig = {
  transpilePackages: ['react-map-gl', 'mapbox-gl', 'maplibre-gl'],
  ...(process.env.DOCKER_BUILD === "1" ? { output: "standalone" as const } : {}),
};

export default nextConfig;
