import { act } from "@testing-library/react";
import { vi } from "vitest";
import type { Autor, EventoChat } from "../../../web/src/api/tipos";
import { WebSocketFalso } from "./websocket-falso";

/**
 * O lado servidor do WebSocket de chat, dirigido pelo teste.
 *
 * A tela é um cliente burro de um fluxo de eventos: quem produz as mensagens é o
 * backend. Aqui o teste ocupa esse lugar e decide a ordem exata de chegada — que
 * é a única coisa que importa para o comportamento sob falha.
 */
export function montarServidorFalso() {
  vi.stubGlobal("WebSocket", WebSocketFalso);

  const esperarSocket = async (aPartirDe = 0): Promise<WebSocketFalso> => {
    for (let i = 0; i < 200; i += 1) {
      const s = WebSocketFalso.ultima;
      if (s !== null && WebSocketFalso.criadas > aPartirDe) return s;
      await act(async () => {
        await new Promise((r) => setTimeout(r, 10));
      });
    }
    throw new Error("nenhum WebSocket foi aberto pela tela");
  };

  const garantirAberto = async (): Promise<WebSocketFalso> => {
    const s = await esperarSocket();
    if (s.readyState !== 1) {
      await act(async () => {
        s.abrir();
      });
    }
    return s;
  };

  return {
    async emitir(evento: EventoChat | Record<string, unknown>): Promise<void> {
      const s = await garantirAberto();
      await act(async () => {
        s.receber(evento);
      });
    },

    /** Atalho para a forma mais frequente: uma mensagem persistida. */
    async emitirMensagem(
      index: number,
      autor: Autor,
      conteudo: string,
      extra: Record<string, unknown> = {},
    ): Promise<void> {
      await this.emitir({
        type: "message",
        message: {
          id: `m${index}`,
          index,
          autor,
          tipo: "text",
          conteudo,
          status: "sent",
          quote_id: null,
          criado_em: new Date(0).toISOString(),
          ...extra,
        },
      } as unknown as EventoChat);
    },

    /** O socket cai do lado do servidor; o cliente entra em reconexão. */
    async derrubar(): Promise<void> {
      const s = await garantirAberto();
      await act(async () => {
        s.cair();
      });
    },

    /** Espera o cliente reabrir (backoff real) e abre o novo socket. */
    async reabrir(): Promise<void> {
      const antes = WebSocketFalso.criadas;
      const novo = await esperarSocket(antes);
      await act(async () => {
        novo.abrir();
      });
    },

    /** O `hello` que o cliente mandou na abertura corrente. */
    ultimoHello(): unknown {
      const bruto = WebSocketFalso.ultima?.enviados[0];
      return bruto === undefined ? null : JSON.parse(bruto);
    },

    get socket(): WebSocketFalso | null {
      return WebSocketFalso.ultima;
    },

    fechar(): void {
      WebSocketFalso.ultima?.close();
    },
  };
}
