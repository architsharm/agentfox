import { defineConfig } from "vitest/config";
import path from "node:path";

/**
 * Minimal, dependency-light setup — no @vitejs/plugin-react, no jsdom, no
 * @testing-library. What's tested here (lib/product/proxy.ts, lib/product/legacyRedirect.ts)
 * is server-side request/response logic, not rendered components, so plain
 * node environment + the @/ alias (mirroring tsconfig.json's own mapping) is
 * all that's needed. Add jsdom/RTL only if a future test actually renders a
 * component.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["**/*.test.ts"],
    exclude: ["node_modules/**", ".next/**"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "."),
    },
  },
});
