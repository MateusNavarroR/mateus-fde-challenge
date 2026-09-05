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


// ─── o histórico local: o que alimenta o seletor de conversas ────────────────

it("retomar uma conversa NÃO a move para o topo — a ordem é a de abertura", async () => {
  /*
   * A primeira versão punha a conversa retomada em primeiro. O efeito era que a lista
   * dançava a cada troca: qualquer conversa aberta virava "a mais recente" e as outras
   * trocavam de lugar. Com o rótulo também relativo ("mais recente"), nada
   * identificava nada — e a impressão de quem usava era a de que só dava para ver a
   * última, porque a que ele acabara de escolher passava a se chamar assim.
   */
  const { lembrarConversa, historicoLocal, retomarConversa } = await import(
    "../../../web/src/chat/sessao"
  );
  localStorage.clear();

  lembrarConversa("conv_a");
  lembrarConversa("conv_b");
  expect(historicoLocal().map((c) => c.id)).toEqual(["conv_b", "conv_a"]);

  retomarConversa("conv_a");

  expect(historicoLocal().map((c) => c.id)).toEqual(
    ["conv_b", "conv_a"],
    );
});

it("a primeira fala do lead vira o nome da conversa", async () => {
  // Um id hexadecimal não diz nada a ninguém: escolher entre dois deles é
  // adivinhação, não navegação.
  const { lembrarConversa, historicoLocal, rotuloDaConversa } = await import(
    "../../../web/src/chat/sessao"
  );
  localStorage.clear();

  lembrarConversa("conv_x");
  lembrarConversa("conv_x", "tenho 30 anos, carro 2012");

  const [c] = historicoLocal();
  expect(c.id).toBe("conv_x");
  expect(rotuloDaConversa(c)).toMatch(/tenho 30 anos, carro 2012/);
  // Sem resumo, cai no id curto — nunca num rótulo relativo que muda de dono.
  expect(rotuloDaConversa({ id: "conv_zzzzzz", aberta_em: c.aberta_em })).toMatch(/zzzzzz/);
});

it("lembrar a MESMA conversa duas vezes não a duplica", async () => {
  const { lembrarConversa, historicoLocal } = await import(
    "../../../web/src/chat/sessao"
  );
  localStorage.clear();

  lembrarConversa("conv_a");
  lembrarConversa("conv_a", "oi");
  lembrarConversa("conv_a");

  expect(historicoLocal()).toHaveLength(1);
  // E o resumo sobrevive a um `lembrar` posterior sem resumo.
  expect(historicoLocal()[0]?.resumo).toBe("oi");
});
