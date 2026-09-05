import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { conectarChat } from "../../../web/src/api/ws";
import { WebSocketFalso } from "../fakes/websocket-falso";

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("WebSocket", WebSocketFalso);
});

afterEach(() => {
  vi.useRealTimers();
});

it("envia hello com last_index -1 na primeira abertura", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  WebSocketFalso.ultima!.abrir();
  expect(JSON.parse(WebSocketFalso.ultima!.enviados[0]!)).toEqual({
    type: "hello",
    last_index: -1,
  });
  s.fechar();
});

it("reabre e repete o hello com o último index que a tela tem", () => {
  let indice = -1;
  const s = conectarChat("c1", {
    ultimoIndex: () => indice,
    aoEvento: () => {
      indice = 2;
    },
  });
  WebSocketFalso.ultima!.abrir();
  WebSocketFalso.ultima!.receber({
    type: "message",
    message: { id: "m2", index: 2, autor: "agente", conteudo: "", tipo: "text", status: "sent" },
  });
  WebSocketFalso.ultima!.cair();
  vi.advanceTimersByTime(1_000);
  WebSocketFalso.ultima!.abrir();
  expect(JSON.parse(WebSocketFalso.ultima!.enviados[0]!)).toEqual({
    type: "hello",
    last_index: 2,
  });
  s.fechar();
});

/**
 * O backoff é exposto pela própria sessão (`s.proximaEsperaMs`). O plano previa
 * lê-lo do fake, mas o fake não tem como saber o delay que o cliente agendou —
 * quem o conhece é quem o agenda.
 */
it("o backoff cresce e tem teto — não martela o backend caído", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  const esperas: number[] = [];
  for (let i = 0; i < 8; i += 1) {
    WebSocketFalso.ultima!.cair();
    esperas.push(s.proximaEsperaMs);
    vi.advanceTimersByTime(s.proximaEsperaMs);
  }
  expect(esperas[0]!).toBeLessThan(esperas[3]!);
  expect(Math.max(...esperas)).toBeLessThanOrEqual(10_000);
  s.fechar();
});

it("expõe o estado da conexão para a tela avisar o lead", () => {
  const estados: string[] = [];
  const s = conectarChat("c1", {
    ultimoIndex: () => -1,
    aoEvento: vi.fn(),
    aoStatus: (e) => estados.push(e),
  });
  WebSocketFalso.ultima!.abrir();
  WebSocketFalso.ultima!.cair();
  expect(estados).toEqual(["conectando", "conectado", "reconectando"]);
  s.fechar();
});

it("um fechamento pedido pela tela não reconecta", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  WebSocketFalso.ultima!.abrir();
  s.fechar();
  vi.advanceTimersByTime(60_000);
  expect(WebSocketFalso.criadas).toBe(1);
});

it("ignora frame desconhecido sem derrubar a conexão", () => {
  const aoEvento = vi.fn();
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento });
  WebSocketFalso.ultima!.abrir();
  WebSocketFalso.ultima!.receber({ type: "coisa_do_futuro" });
  expect(aoEvento).not.toHaveBeenCalled();
  expect(WebSocketFalso.ultima!.fechada).toBe(false);
  s.fechar();
});

it("a URL sai do location, nunca de host fixo", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  expect(WebSocketFalso.ultima!.url).toBe(`ws://${location.host}/api/chat/c1`);
  s.fechar();
});

/**
 * O navegador não põe cabeçalho no handshake do WebSocket. Quando existe token,
 * ele vai por query string — decisão do Núcleo. Quando não existe, **nenhum
 * parâmetro é enviado**: um token opcional não pode virar um token obrigatório
 * mal configurado.
 */
it("sem token gravado, nenhum parâmetro entra na URL do socket", () => {
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  expect(WebSocketFalso.ultima!.url).not.toContain("?");
  s.fechar();
});

it("com token gravado, ele vai por query string no handshake", () => {
  sessionStorage.setItem("autoseguro.admin_token", "t-abc");
  const s = conectarChat("c1", { ultimoIndex: () => -1, aoEvento: vi.fn() });
  expect(WebSocketFalso.ultima!.url).toBe(`ws://${location.host}/api/chat/c1?token=t-abc`);
  s.fechar();
  localStorage.clear();
});
