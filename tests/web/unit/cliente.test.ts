import { beforeEach, expect, it, vi } from "vitest";
import { ROTAS, get, patch } from "../../../web/src/api/cliente";

beforeEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

it("sem token, nenhum cabeçalho de admin é enviado", async () => {
  // Cabeçalho vazio transformaria um token opcional em token obrigatório mal
  // configurado (CLAUDE.md 14c).
  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ items: [] }));
  await get(ROTAS.handoffs());
  expect([...new Headers(f.mock.calls[0]![1]!.headers).keys()]).not.toContain("x-admin-token");
});

it("com token gravado, o cabeçalho vai em toda chamada", async () => {
  sessionStorage.setItem("autoseguro.admin_token", "t-abc");
  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ items: [] }));
  await get(ROTAS.handoffs());
  expect(new Headers(f.mock.calls[0]![1]!.headers).get("x-admin-token")).toBe("t-abc");
});

it("401 vira um erro tipado, não um crash de parse", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
  await expect(get(ROTAS.status())).rejects.toMatchObject({ tipo: "nao_autorizado" });
});

it("409 na transição de handoff preserva a mensagem do backend", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    Response.json(
      { error: "transicao_invalida", message: "resolvido não volta para pendente" },
      { status: 409 },
    ),
  );
  await expect(patch(ROTAS.handoff("h1"), { status: "pendente" })).rejects.toMatchObject({
    tipo: "conflito",
    message: /resolvido não volta/,
  });
});

it("404 vira nao_encontrado, para a tela dizer o que aconteceu", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    Response.json({ error: "nao_encontrado", message: "some" }, { status: 404 }),
  );
  await expect(get(ROTAS.conversa("x"))).rejects.toMatchObject({ tipo: "nao_encontrado" });
});

it("backend fora do ar vira erro tipado, não uma tela em branco", async () => {
  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("failed to fetch"));
  await expect(get(ROTAS.status())).rejects.toMatchObject({ tipo: "indisponivel" });
});

it("nenhuma rota é montada por concatenação solta de string", () => {
  // ROTAS é a superfície inteira que a UI consome. É ela que o teste de deriva lê.
  expect(Object.keys(ROTAS).sort()).toEqual(
    [
      "conversa",
      "conversas",
      "eventos",
      "handoff",
      "handoffs",
      "health",
      "resumo",
      "status",
      "traces",
      "usage",
      "wsChat",
    ].sort(),
  );
});
