import { existsSync, readFileSync } from "node:fs";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { ROTAS, ROTAS_AUTENTICACAO } from "../../../web/src/api/cliente";

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

/**
 * As duas rotas de WebSocket **não aparecem** no `openapi.json` gerado.
 *
 * O plano supunha que o FastAPI as documentasse como `GET` (o upgrade HTTP); ele
 * não documenta — `APIRouter.websocket()` não entra no schema OpenAPI, por
 * desenho do framework. Não é omissão do backend nem deriva: é uma propriedade
 * do gerador.
 *
 * A exceção é **fechada e nominal**, e o último caso deste bloco impede que ela
 * cresça. Quem existe de verdade nessas duas rotas é provado pelo handshake, nos
 * testes de ponta a ponta — não por um documento que não fala de WebSocket.
 */
const SO_WEBSOCKET = ["GET /api/chat/{conversation_id}", "GET /api/events"];

describe.runIf(existsSync(GERADO))("deriva entre o congelado e o gerado", () => {
  // O corpo de um `describe.runIf` roda na coleta mesmo quando os casos são
  // pulados, então a leitura precisa ser tolerante à ausência do arquivo.
  const gerado = existsSync(GERADO)
    ? JSON.parse(readFileSync(GERADO, "utf8"))
    : { paths: {} };

  it("toda rota REST do congelado existe no gerado", () => {
    const faltando = rotas(congelado)
      .filter((r) => !SO_WEBSOCKET.includes(r))
      .filter((r) => !rotas(gerado).includes(r));
    expect(faltando, "o backend não entrega o que o contrato promete").toEqual([]);
  });

  it("a exceção do WebSocket não cresce — são exatamente estas duas rotas", () => {
    const ausentes = rotas(congelado).filter((r) => !rotas(gerado).includes(r));
    expect(ausentes.sort()).toEqual([...SO_WEBSOCKET].sort());
  });

  it("toda rota do gerado existe no congelado", () => {
    const sobrando = rotas(gerado).filter((r) => !rotas(congelado).includes(r));
    expect(sobrando, "superfície não documentada — passa por decisão escrita antes").toEqual([]);
  });

  it("o arquivo gerado é ignorado pelo git", () => {
    // A regra vive no `.gitignore` de `tests/web/`, não no da raiz: o derivado é
    // desta pasta, e o plano não pode escrever fora do escopo desta frente.
    expect(readFileSync("tests/web/.gitignore", "utf8")).toContain(".openapi-gerado.json");
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

/**
 * As rotas de login moram num objeto SEPARADO, e a separação é o conteúdo desta
 * decisão.
 *
 * O `openapi.yaml` foi congelado na Fase 0 como o contrato do **produto**, e os dois
 * testes acima existem para que ninguém acrescente superfície sem decisão escrita.
 * Login não é produto: é o mecanismo pelo qual um humano alcança o produto — a mesma
 * natureza de `GET /`, que já ficava fora. O backend as monta com
 * `include_in_schema=False`, e `tests/nucleo/test_auth.py` mantém um inventário
 * fechado das rotas escondidas do schema: se aparecer uma quarta, ele reprova.
 *
 * Misturá-las em `ROTAS` obrigaria a relaxar "toda rota que a UI consome está no
 * contrato" — e é justamente essa afirmação que pega uma rota inventada no JSX.
 */
it("as rotas de autenticação ficam fora do contrato, e são exatamente três", () => {
  const auth = Object.values(ROTAS_AUTENTICACAO).map((f) => f());
  expect(auth.sort()).toEqual(
    ["/api/auth/estado", "/api/auth/login", "/api/auth/logout"].sort(),
  );
  const doContrato = Object.keys(congelado.paths);
  for (const rota of auth) expect(doContrato).not.toContain(rota);
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
