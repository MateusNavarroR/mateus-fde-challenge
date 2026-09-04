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
  expect(post).toHaveBeenCalledWith("/api/conversations", { channel: "web" });
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

it("external_ref nunca carrega dado de pessoa", async () => {
  // openapi.yaml: "Nunca um telefone real (...) Repositório público."
  const post = vi.fn(async (_url: string, _corpo: unknown) => ({ id: "c" }));
  await abrirOuRetomar({ post, getConversa: async () => null });
  expect(post.mock.calls[0]![1]).not.toHaveProperty("external_ref");
});

it("localStorage indisponível não quebra a tela", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("bloqueado");
  });
  const post = vi.fn(async () => ({ id: "c-nova" }));
  await expect(abrirOuRetomar({ post, getConversa: async () => null })).resolves.toBe("c-nova");
});
