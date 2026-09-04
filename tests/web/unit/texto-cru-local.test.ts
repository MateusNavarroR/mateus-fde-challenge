import { beforeEach, expect, it } from "vitest";
import { estadoInicial, reduzir } from "../../../web/src/chat/useConversa";
import { esquecerCru, gravarCru, lerCru } from "../../../web/src/chat/textoCruLocal";

const CPF = "111.222.333-44";
const DIGITADO = `meu cpf é ${CPF}`;
const MASCARADO = "meu cpf é [CPF]";

function ecoDoServidor(id: string, index: number) {
  return {
    type: "message" as const,
    message: {
      id,
      index,
      autor: "lead" as const,
      tipo: "text" as const,
      // O servidor SEMPRE devolve mascarado: não existe endpoint com a versão crua.
      conteudo: MASCARADO,
      status: "received" as const,
      quote_id: null,
      criado_em: new Date().toISOString(),
    },
  };
}

beforeEach(() => sessionStorage.clear());

it("o lead vê o que digitou, não a versão mascarada", () => {
  let e = estadoInicial();
  e = reduzir(e, { type: "envio-local", idTemp: "t1", texto: DIGITADO });
  e = reduzir(e, ecoDoServidor("m1", 0));
  expect(e.mensagens).toHaveLength(1);
  expect(e.mensagens[0]!.conteudo).toBe(DIGITADO);
});

it("o texto cru migra do id temporário para o canônico", () => {
  let e = estadoInicial();
  e = reduzir(e, { type: "envio-local", idTemp: "t1", texto: DIGITADO });
  e = reduzir(e, ecoDoServidor("m1", 0));
  expect(e.cruDoLead["m1"]).toBe(DIGITADO);
  expect(e.cruDoLead["t1"]).toBeUndefined();
});

it("só a fala do LEAD tem versão local", () => {
  // O que a empresa disse vem do servidor e não pode ter segunda fonte da verdade.
  let e = estadoInicial({ m2: "texto local indevido" });
  e = reduzir(e, {
    type: "message",
    message: {
      id: "m2", index: 0, autor: "agente", tipo: "text",
      conteudo: "Oi! Como posso ajudar?", status: "sent",
      quote_id: null, criado_em: new Date().toISOString(),
    },
  });
  expect(e.mensagens[0]!.conteudo).toBe("Oi! Como posso ajudar?");
});

it("sem versão local, cai na mascarada — degrada, não quebra", () => {
  let e = estadoInicial();
  e = reduzir(e, ecoDoServidor("m1", 0));
  expect(e.mensagens[0]!.conteudo).toBe(MASCARADO);
});

it("o histórico do servidor também usa a versão local quando existe", () => {
  // Depois de um F5: o histórico vem mascarado, o sessionStorage tem o cru.
  const e = reduzir(estadoInicial({ m1: DIGITADO }), {
    type: "historico",
    messages: [ecoDoServidor("m1", 0).message],
  });
  expect(e.mensagens[0]!.conteudo).toBe(DIGITADO);
});

it("sessionStorage: grava, lê e esquece", () => {
  gravarCru("c1", { m1: DIGITADO });
  expect(lerCru("c1")).toEqual({ m1: DIGITADO });
  esquecerCru("c1");
  expect(lerCru("c1")).toEqual({});
});

it("é por conversa — uma não vaza para a outra", () => {
  gravarCru("c1", { m1: DIGITADO });
  expect(lerCru("c2")).toEqual({});
});

it("storage bloqueado não quebra a tela", () => {
  const original = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("bloqueado");
  };
  expect(() => gravarCru("c1", { m1: DIGITADO })).not.toThrow();
  Storage.prototype.setItem = original;
});

it("JSON corrompido no storage não quebra a tela", () => {
  sessionStorage.setItem("autoseguro:cru:c1", "{isso não é json");
  expect(lerCru("c1")).toEqual({});
});
