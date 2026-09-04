import { describe, expect, it } from "vitest";
import { estadoInicial, reduzir, type Acao, type Estado } from "../../../web/src/chat/useConversa";
import { fraseDoLead } from "../fixtures/pii";

const msg = (index: number, autor: string, conteudo: string, extra = {}) =>
  ({
    type: "message" as const,
    message: {
      id: `m${index}`,
      index,
      autor,
      tipo: "text",
      conteudo,
      status: "sent",
      quote_id: null,
      criado_em: "2026-01-01T00:00:00Z",
      ...extra,
    },
  }) as unknown as Acao;

const aplicar = (eventos: unknown[], de: Estado = estadoInicial()) =>
  eventos.reduce<Estado>((e, ev) => reduzir(e, ev as Acao), de);

describe("ordenação", () => {
  it("ordena por index, não por ordem de chegada", () => {
    const e = aplicar([
      msg(2, "agente", "terceira"),
      msg(0, "lead", "primeira"),
      msg(1, "sistema", "segunda"),
    ]);
    expect(e.mensagens.map((m) => m.conteudo)).toEqual(["primeira", "segunda", "terceira"]);
  });

  it("ordena por index mesmo quando criado_em está fora de ordem", () => {
    // 99,8 % das conversas do dataset têm timestamp fora de ordem (CLAUDE.md).
    const e = aplicar([
      msg(0, "lead", "primeira", { criado_em: "2026-01-01T00:00:09Z" }),
      msg(1, "agente", "segunda", { criado_em: "2026-01-01T00:00:03Z" }),
    ]);
    expect(e.mensagens.map((m) => m.index)).toEqual([0, 1]);
  });

  it("é idempotente por id — o replay da reconexão não duplica", () => {
    const e = aplicar([
      msg(0, "lead", "oi"),
      msg(1, "agente", "olá"),
      msg(0, "lead", "oi"),
      msg(1, "agente", "olá"),
    ]);
    expect(e.mensagens).toHaveLength(2);
  });
});

describe("bolha otimista", () => {
  it("aparece antes de qualquer resposta do servidor", () => {
    const e = reduzir(estadoInicial(), {
      type: "envio-local",
      idTemp: "tmp-1",
      texto: "quero cotar",
    });
    expect(e.mensagens.at(-1)).toMatchObject({ id: "tmp-1", autor: "lead", pendente: true });
  });

  it("reconcilia por id — nunca por texto, porque o eco vem mascarado", () => {
    // Reconciliar por texto seria bug: não existe endpoint que devolva a versão
    // crua (openapi.yaml, invariante 2). Aqui o digitado e o ecoado diferem por
    // construção, porque a frase carrega PII.
    const [frase, pii] = fraseDoLead(11);
    let e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: frase });
    e = reduzir(e, msg(0, "lead", frase.replace(pii.cpf, "[CPF]")));
    expect(e.mensagens).toHaveLength(1);
    expect(e.mensagens[0]!.id).toBe("m0");
    expect(e.mensagens[0]!.pendente).toBe(false);
  });

  it("o lead continua vendo o que digitou — o servidor é que não guarda", () => {
    // Este teste substitui um que exigia o oposto. A versão anterior assertava que
    // a bolha do lead passava a exibir o texto MASCARADO depois do eco, e o efeito
    // era o lead ver a própria mensagem alterada — o que parece defeito, porque ele
    // sabe o que escreveu.
    //
    // O invariante do backend não mudou nem um pouco: o eco vem mascarado, o banco
    // guarda mascarado, e não existe endpoint com a versão crua. O que mudou é que
    // o NAVEGADOR DELE lembra o que ele digitou, em sessionStorage, e nada disso
    // sai da aba.
    const [frase, pii] = fraseDoLead(11);
    let e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: frase });
    e = reduzir(e, msg(0, "lead", frase.replace(pii.cpf, "[CPF]")));
    expect(e.mensagens[0]!.conteudo).toBe(frase);
    expect(e.mensagens[0]!.conteudo).toContain(pii.cpf);
  });

  it("reconcilia FIFO quando o lead envia duas antes do eco (a conversa enfileira)", () => {
    let e = reduzir(estadoInicial(), { type: "envio-local", idTemp: "tmp-1", texto: "primeira" });
    e = reduzir(e, { type: "envio-local", idTemp: "tmp-2", texto: "segunda" });
    e = aplicar([msg(0, "lead", "primeira"), msg(2, "lead", "segunda")], e);
    expect(e.mensagens.map((m) => m.id)).toEqual(["m0", "m2"]);
    expect(e.pendentesDoLead).toEqual([]);
  });
});

describe("o turno bloqueado de 37 s", () => {
  it("mantém o digitando aceso entre as três mensagens de sistema", () => {
    let e = aplicar([{ type: "typing", ativo: true }, msg(0, "lead", "quero cotar")]);
    for (const [i, texto] of ["aviso", "reforço", "indisponibilidade"].entries()) {
      e = reduzir(e, msg(i + 1, "sistema", texto));
      expect(e.digitando, `apagou no ${texto}`).toBe(true);
    }
    e = reduzir(e, { type: "typing", ativo: false });
    expect(e.digitando).toBe(false);
  });

  it("mensagem do agente também não apaga o digitando — só o typing false apaga", () => {
    const e = aplicar([{ type: "typing", ativo: true }, msg(0, "agente", "oi")]);
    expect(e.digitando).toBe(true);
  });

  it("o StateEvent encaminhado trava a entrada", () => {
    const e = reduzir(estadoInicial(), { type: "state", state: "encaminhado" });
    expect(e.entradaBloqueada).toBe(true);
  });
});

describe("hello e replay", () => {
  it("last_index é o maior index conhecido, -1 quando vazio", () => {
    expect(estadoInicial().ultimoIndex).toBe(-1);
    expect(aplicar([msg(0, "lead", "a"), msg(7, "agente", "b")]).ultimoIndex).toBe(7);
  });

  it("o replay parcial preserva o que já havia e não reordena nada", () => {
    let e = aplicar([msg(0, "lead", "a"), msg(1, "sistema", "aviso")]);
    e = aplicar([msg(1, "sistema", "aviso"), msg(2, "sistema", "reforço")], e);
    expect(e.mensagens.map((m) => m.index)).toEqual([0, 1, 2]);
  });
});

describe("o guardrail visível", () => {
  it("marca como bug uma mensagem com valor monetário e quote_id nulo", () => {
    const e = aplicar([msg(0, "agente", "fica R$ 392,25/mês", { quote_id: null })]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(true);
  });

  it("não marca a mesma mensagem quando o quote_id existe", () => {
    const e = aplicar([msg(0, "agente", "fica R$ 392,25/mês", { quote_id: "q1" })]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(false);
  });

  it("não marca texto sem dinheiro — o marcador não pode virar paranoia", () => {
    const e = aplicar([msg(0, "agente", "tenho 35 anos de estrada, carro 2019")]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(false);
  });

  it("não marca a fala do lead: o valor citado por ele não é promessa nossa", () => {
    const e = aplicar([msg(0, "lead", "meu seguro atual é R$ 300 por mês")]);
    expect(e.mensagens[0]!.suspeitaDeBug).toBe(false);
  });
});
