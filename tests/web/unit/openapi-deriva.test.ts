import { existsSync, readFileSync } from "node:fs";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { ROTAS } from "../../../web/src/api/cliente";

/**
 * O teste que separa "construímos contra o contrato" de "construímos contra o
 * que a implementação faz". Ele tem três sentidos:
 *
 *   1. toda rota do congelado existe no gerado — o backend entrega o prometido;
 *   2. toda rota do gerado existe no congelado — **é este que pega superfície
 *      não documentada**, uma rota que apareceu no backend sem decisão escrita;
 *   3. toda rota que a UI consome está no congelado — o inventário.
 *
 * Se o segundo sentido falhar, a correção **não** é relaxar o teste nem editar o
 * congelado: é abrir a rota na spec por decisão escrita, ou removê-la do backend.
 */

const GERADO = "tests/web/.openapi-gerado.json";

const congelado = parse(readFileSync("docs/openapi.yaml", "utf8"));

const rotas = (spec: { paths: Record<string, object> }): string[] =>
  Object.entries(spec.paths)
    .flatMap(([p, ops]) => Object.keys(ops).map((m) => `${m.toUpperCase()} ${p}`))
    .sort();

describe.runIf(existsSync(GERADO))("deriva entre o congelado e o gerado", () => {
  const gerado = JSON.parse(readFileSync(GERADO, "utf8"));

  it("toda rota do congelado existe no gerado", () => {
    const faltando = rotas(congelado).filter((r) => !rotas(gerado).includes(r));
    expect(faltando, "o backend não entrega o que o contrato promete").toEqual([]);
  });

  it("toda rota do gerado existe no congelado", () => {
    const sobrando = rotas(gerado).filter((r) => !rotas(congelado).includes(r));
    expect(sobrando, "superfície não documentada — passa por decisão escrita antes").toEqual([]);
  });

  it("o arquivo gerado é ignorado pelo git", () => {
    expect(readFileSync(".gitignore", "utf8")).toContain("tests/web/.openapi-gerado.json");
  });
});

/**
 * O guarda do guarda.
 *
 * `describe.runIf` faria a suíte de deriva sumir em silêncio quando ninguém
 * rodou o backend — e um teste que some passando é pior que um teste ausente.
 * Enquanto a API não existe, este caso avisa em voz alta e verifica a máquina
 * que produz o snapshot; assim que o backend subir, a comparação acima passa a
 * valer sem que ninguém precise lembrar de habilitá-la.
 */
it("o mecanismo que produz o snapshot do openapi gerado existe e está declarado", () => {
  if (!existsSync(GERADO)) {
    console.warn(
      `[deriva] ${GERADO} não existe: a comparação com o openapi GERADO não rodou. ` +
        "Suba o backend e rode `npm --prefix web run openapi:baixar`.",
    );
  }
  expect(existsSync("web/scripts/baixar-openapi.mjs")).toBe(true);
  const pkg = JSON.parse(readFileSync("web/package.json", "utf8"));
  expect(pkg.scripts["openapi:baixar"]).toContain("baixar-openapi.mjs");
});

/**
 * O inventário: `ROTAS` é a superfície inteira que a UI consome, e é ela que
 * este teste lê. Nenhum componente escreve `"/api/..."` no meio do JSX — é assim
 * que uma rota escaparia daqui.
 *
 * Cada rota é chamada com o sentinela `"{id}"`, que devolve o caminho já no
 * formato do OpenAPI. (O plano previa `f("id")` mais um `template()` por regex;
 * a regex procurava `${...}` numa string **já interpolada**, então nunca casaria.
 * O sentinela faz o mesmo trabalho sem depender disso.)
 */
it("toda rota que a UI consome está no contrato congelado", () => {
  const doContrato = Object.keys(congelado.paths).map((p: string) =>
    p.replace(/\{[^}]+\}/g, "{id}"),
  );
  for (const [nome, fn] of Object.entries(ROTAS)) {
    const usada = String((fn as (a: string) => string)("{id}")).split("?")[0];
    expect(doContrato, `${nome} → ${usada} não existe no openapi congelado`).toContain(usada);
  }
});

it("ROTAS cobre exatamente a superfície declarada — nada montado por string solta", () => {
  expect(Object.keys(ROTAS).sort()).toEqual(
    [
      "conversa",
      "conversas",
      "eventos",
      "handoff",
      "handoffs",
      "health",
      "status",
      "usage",
      "wsChat",
    ].sort(),
  );
});
