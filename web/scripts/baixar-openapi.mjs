#!/usr/bin/env node
/**
 * Baixa o `openapi.json` que o backend **gera** e grava o snapshot que o teste de
 * deriva compara com o `docs/openapi.yaml` **congelado**.
 *
 * O arquivo gerado não é versionado: ele é derivado do processo no ar, e um
 * derivado no Git envelhece em silêncio. O teste de deriva confere isso.
 *
 * Uso, com o backend no ar:
 *   npm --prefix web run openapi:baixar
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const DESTINO = resolve(RAIZ, "tests/web/.openapi-gerado.json");
const URL_PADRAO = process.env.OPENAPI_URL ?? "http://127.0.0.1:8080/openapi.json";

try {
  const resposta = await fetch(URL_PADRAO);
  if (!resposta.ok) {
    console.error(`[openapi] ${URL_PADRAO} respondeu ${resposta.status}`);
    process.exit(1);
  }
  const spec = await resposta.json();
  mkdirSync(dirname(DESTINO), { recursive: true });
  writeFileSync(DESTINO, `${JSON.stringify(spec, null, 2)}\n`, "utf8");
  const rotas = Object.keys(spec.paths ?? {}).length;
  console.log(`[openapi] ${rotas} caminhos gravados em tests/web/.openapi-gerado.json`);
} catch (erro) {
  console.error(
    `[openapi] não consegui falar com ${URL_PADRAO}. Suba o backend (docker compose up -d) e tente de novo.`,
  );
  console.error(`[openapi] ${erro instanceof Error ? erro.message : String(erro)}`);
  process.exit(1);
}
