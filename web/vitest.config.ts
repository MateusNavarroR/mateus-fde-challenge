import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

/**
 * Duas raízes diferentes, de propósito, e as duas importam:
 *
 * - **`root` é `web/`** (o diretório deste arquivo). É de onde o Vite resolve as
 *   dependências, porque `node_modules` vive aqui.
 * - **`process.cwd()` é a raiz do repositório**, garantido pelo `cd ..` no script
 *   `test` do `package.json`. Os testes leem `docs/openapi.yaml` e
 *   `web/package.json` por caminho relativo à raiz, porque o contrato congelado
 *   vive fora de `web/` e o teste de deriva compara os dois lados.
 *
 * A suíte mora em `../tests/web`, que é **fora** de `web/` — decisão dos planos,
 * para que toda a árvore de testes do repositório fique num lugar só. O preço é
 * este: um import puro (`@testing-library/react`) feito de um arquivo fora de
 * `web/` não encontra `web/node_modules`, porque o Node procura subindo a partir
 * de quem importa. Os aliases abaixo apontam explicitamente as poucas
 * dependências que a suíte importa — declarado e reproduzível a partir de um
 * `npm install` limpo, ao contrário de um link simbólico que só existe na
 * máquina de quem o criou.
 */
const aqui = fileURLToPath(new URL(".", import.meta.url));
const testes = fileURLToPath(new URL("../tests/web/", import.meta.url));
const pacote = (nome: string) => `${aqui}node_modules/${nome}`;

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^@testing-library\/(.*)$/, replacement: pacote("@testing-library/$1") },
      { find: /^react$/, replacement: pacote("react") },
      { find: /^react\/(.*)$/, replacement: pacote("react/$1") },
      { find: /^react-dom$/, replacement: pacote("react-dom") },
      { find: /^react-dom\/(.*)$/, replacement: pacote("react-dom/$1") },
      { find: /^yaml$/, replacement: pacote("yaml") },
    ],
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: [`${testes}setup.ts`],
    include: [`${testes}unit/**/*.test.{ts,tsx}`],
    // O Playwright vive em tests/web/e2e e não é rodado pelo vitest.
    exclude: ["**/node_modules/**", `${testes}e2e/**`],
    restoreMocks: true,
  },
  server: {
    fs: { allow: [".."] },
  },
});
