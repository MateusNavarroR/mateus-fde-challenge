// `web/package.json` declara `"type": "module"` e o `@playwright/test` é CJS:
// o import nomeado de `defineConfig` quebra na interop. Um objeto anotado com o
// tipo do próprio pacote dá a mesma checagem sem importar valor nenhum.
import type { PlaywrightTestConfig } from "@playwright/test";

/**
 * As evidências são gravadas a partir de **estado real**. Screenshot com dado de
 * exemplo não vale — é a diferença entre provar e ilustrar.
 *
 * `workers: 1` não é conservadorismo: as suítes que dependem de `QUOTE_SEED`
 * rodam em série, sempre. O RNG do legado é um fluxo global e contínuo do
 * processo, então paralelismo quebra o determinismo (CLAUDE.md, reprodutibilidade).
 *
 * `outputDir` fica **fora** de `docs/evidencia-ui/`: artefato de falha na pasta
 * de evidência polui exatamente o que o avaliador vai abrir.
 */
const config: PlaywrightTestConfig = {
  testDir: "../tests/web/e2e",
  outputDir: "../tests/web/.playwright",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.WEB_BASE_URL ?? "http://127.0.0.1:5173",
    trace: "retain-on-failure",
    video: "off",
    viewport: { width: 1440, height: 900 },
    locale: "pt-BR",
    timezoneId: "America/Sao_Paulo",
  },
};

export default config;
