import { beforeEach, expect, it, vi } from "vitest";
import { CHAVE, abrirOuRetomar, novaConversa } from "../../../web/src/chat/sessao";

beforeEach(() => localStorage.clear());

it("retoma a conversa gravada sem criar outra", async () => {
  localStorage.setItem(CHAVE, "c-antiga");
  const post = vi.fn();
  expect(await abrirOuRetomar({ post, getConversa: async () => ({ id: "c-antiga" }) })).toBe(
    "c-antiga",
  );
  expect(post).not.toHaveBeenCalled();
});

it("cria uma conversa quando não há nenhuma gravada", async () => {
  const post = vi.fn(async () => ({ id: "c-nova" }));
  expect(await abrirOuRetomar({ post, getConversa: async () => null })).toBe("c-nova");
  expect(post).toHaveBeenCalledWith("/api/conversations", {
    channel: "web",
    external_ref: expect.any(String),
  });
  expect(localStorage.getItem(CHAVE)).toBe("c-nova");
});

it("cria outra quando a gravada já não existe no backend (banco recriado)", async () => {
  localStorage.setItem(CHAVE, "c-fantasma");
  const post = vi.fn(async () => ({ id: "c-nova" }));
  expect(await abrirOuRetomar({ post, getConversa: async () => null })).toBe("c-nova");
});

it("o botão de nova conversa descarta a sessão e cria outra", async () => {
  localStorage.setItem(CHAVE, "c-antiga");
  const post = vi.fn(async () => ({ id: "c-nova" }));
  expect(await novaConversa({ post })).toBe("c-nova");
  expect(localStorage.getItem(CHAVE)).toBe("c-nova");
});

it("external_ref é um id de sessão aleatório, sem dado de pessoa", async () => {
  // openapi.yaml: "Nunca um telefone real (...) Repositório público."
  //
  // A versão anterior deste teste exigia que `external_ref` NÃO fosse enviado. O
  // instinto estava certo sobre o risco e errado sobre a solução: o backend caía
  // num literal fixo, e a UNIQUE (channel, external_ref) fazia a SEGUNDA conversa
  // daquele banco falhar com 500, para sempre. O bug só aparecia no segundo uso.
  //
  // Um id de sessão aleatório mantém a garantia — não há dado do lead aqui — e dá
  // semântica ao campo: mesma sessão, mesma conversa.
  const post = vi.fn(async (_url: string, _corpo: unknown) => ({ id: "c" }));
  await abrirOuRetomar({ post, getConversa: async () => null });
  const corpo = post.mock.calls[0]![1] as { external_ref: string };
  expect(corpo).toHaveProperty("external_ref");
  expect(corpo.external_ref.length).toBeGreaterThan(8);
  // aleatório: sem telefone, sem CPF, sem e-mail
  expect(corpo.external_ref).not.toMatch(/\d{3}\.\d{3}\.\d{3}-\d{2}/);
  expect(corpo.external_ref).not.toMatch(/\+?55\s?\d{2}\s?9\d{4}/);
  expect(corpo.external_ref).not.toMatch(/@/);
});

it("a mesma sessão manda o mesmo external_ref", async () => {
  const post = vi.fn(async (_url: string, _corpo: unknown) => ({ id: "c" }));
  await abrirOuRetomar({ post, getConversa: async () => null });
  localStorage.removeItem(CHAVE); // esquece a conversa, mantém a sessão
  await abrirOuRetomar({ post, getConversa: async () => null });
  const a = (post.mock.calls[0]![1] as { external_ref: string }).external_ref;
  const b = (post.mock.calls[1]![1] as { external_ref: string }).external_ref;
  expect(a).toBe(b);
});

it("nova conversa gera sessão nova, logo external_ref novo", async () => {
  const post = vi.fn(async (_url: string, _corpo: unknown) => ({ id: "c" }));
  await abrirOuRetomar({ post, getConversa: async () => null });
  await novaConversa({ post });
  const a = (post.mock.calls[0]![1] as { external_ref: string }).external_ref;
  const b = (post.mock.calls[1]![1] as { external_ref: string }).external_ref;
  expect(a).not.toBe(b);
});

it("localStorage indisponível não quebra a tela", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("bloqueado");
  });
  const post = vi.fn(async () => ({ id: "c-nova" }));
  await expect(abrirOuRetomar({ post, getConversa: async () => null })).resolves.toBe("c-nova");
});
