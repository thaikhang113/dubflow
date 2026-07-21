import { defineConfig } from "vitest/config";

// Separate from the default suite: the perf simulations build large in-memory fixtures
// and print timing/op-count tables, so they're opt-in (`npm run test:perf`) and stay out
// of `npm test` + CI. The default config only matches `*.test.ts`, so `*.perf.ts` never
// runs there; this config matches them explicitly.
export default defineConfig({
  test: {
    include: ["test/**/*.perf.ts"],
    environment: "node",
    // A 5000-session sweep with simulated per-op latency can take a few seconds.
    testTimeout: 60000,
  },
});
