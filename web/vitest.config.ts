import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * A raiz é a **raiz do repositório**, não `web/`: os testes leem `docs/openapi.yaml`
 * e `web/package.json` por caminho relativo à raiz, porque o contrato congelado vive
 * fora de `web/` e o teste de deriva compara os dois lados.
 *
 * O script `test` do package.json faz `cd ..` antes de chamar o vitest, para que o
 * `process.cwd()` dos workers também seja a raiz.
 */
const raiz = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  plugins: [react()],
  root: raiz,
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["tests/web/setup.ts"],
    include: ["tests/web/unit/**/*.test.{ts,tsx}"],
    // O Playwright vive em tests/web/e2e e não é rodado pelo vitest.
    exclude: ["**/node_modules/**", "tests/web/e2e/**"],
    restoreMocks: true,
  },
});
