import { act } from "@testing-library/react";
import { vi } from "vitest";
import { WebSocketFalso } from "./websocket-falso";

/**
 * O backend do admin, dirigido pelo teste: `fetch` e o socket `/api/events`.
 *
 * O detalhe que ele existe para permitir: o push **invalida e recarrega**, então
 * o teste precisa poder mudar a resposta do endpoint e só então empurrar o
 * frame — se a tela montasse o item a partir do frame, esse fake não teria como
 * distinguir as duas coisas, e o teste não valeria nada.
 */

type Config = {
  handoffs?: { items: unknown[]; pendentes?: number };
  conversas?: { items: unknown[]; next_cursor?: string | null };
  conversa?: Record<string, unknown>;
  conversaErro?: number;
  /** `/api/conversations/{id}/traces`. Ausente = conversa sem execução registrada. */
  traces?: { items: unknown[] };
  status?: Record<string, unknown>;
  usage?: Record<string, unknown>;
  patchErro?: number;
  /**
   * O estado de autenticação que `/api/auth/estado` devolve.
   *
   * Ausente = instalação ABERTA, que é o caminho padrão e o que quase todo teste
   * desta suíte pressupõe. Presente, o fake passa a exigir o login de verdade:
   * `/api/auth/login` só aceita as credenciais aqui declaradas, e a sessão vira
   * um booleano do lado do fake — que é exatamente o papel do cookie `httpOnly`
   * no navegador, invisível para o JavaScript da página.
   */
  auth?: { usuario: string; senha: string; autenticado?: boolean };
  tudoVazio?: boolean;
  indisponivel?: boolean;
  status401?: boolean;
  populado?: boolean;
};

const STATUS_VAZIO = {
  upstream_health: { status: "ok", latency_ms: 3 },
  janela: { total: 0, sucesso: 0, taxa_sucesso: 0, p50_ms: 0, p95_ms: 0, por_outcome: {} },
  breaker: { estado: "fechado", falhas_consecutivas: 0, aberto_desde: null, reabre_em: null },
  ultimas_tentativas: [],
};

const USAGE_VAZIO = {
  total: {
    tokens_in: 0,
    tokens_out: 0,
    cache_read: null,
    cache_write: null,
    taxa_acerto_cache: null,
    custo_usd: null,
    pricing_vigencia: null,
    latency_p50_ms: null,
  },
  por_provider: [],
  por_conversa: [],
};

export function montarBackendFalso(config: Config = {}) {
  vi.stubGlobal("WebSocket", WebSocketFalso);

  const chamadasPorUrl: string[] = [];
  let ultimaUrl = "";
  let ultimoPatch: [string, unknown] | null = null;

  let handoffs = config.handoffs ?? { items: [], pendentes: 0 };
  const conversas = config.populado
    ? {
        items: [
          {
            id: "c1",
            channel: "web",
            state: "encaminhado",
            criado_em: new Date(0).toISOString(),
            atualizado_em: new Date(0).toISOString(),
            total_mensagens: 7,
            ultima_mensagem: "A equipe assume daqui.",
            handoff_pendente: true,
            ultima_cotacao_status: "failed",
          },
        ],
        next_cursor: null,
      }
    : (config.conversas ?? { items: [], next_cursor: null });

  let autenticado = config.auth?.autenticado ?? false;

  const responder = (corpo: unknown, status = 200): Response =>
    new Response(JSON.stringify(corpo), {
      status,
      headers: { "content-type": "application/json" },
    });

  vi.spyOn(globalThis, "fetch").mockImplementation((async (
    entrada: RequestInfo | URL,
    init?: RequestInit,
  ) => {
    const url = String(entrada);
    ultimaUrl = url;
    chamadasPorUrl.push(url);

    if (config.indisponivel) throw new TypeError("failed to fetch");

    // A autenticação responde ANTES do 401 global: um teste que simula `/api/*`
    // recusado ainda precisa que `/api/auth/estado` diga a verdade sobre a sessão.
    if (url.startsWith("/api/auth/estado")) {
      return responder({ exigido: config.auth !== undefined, autenticado: config.auth === undefined || autenticado });
    }
    if (url.startsWith("/api/auth/login")) {
      const corpo = JSON.parse(String(init?.body ?? "{}")) as { usuario?: string; senha?: string };
      if (
        config.auth !== undefined &&
        corpo.usuario === config.auth.usuario &&
        corpo.senha === config.auth.senha
      ) {
        autenticado = true;
        return new Response(null, { status: 204 });
      }
      // A mesma recusa do backend, palavra por palavra: nome errado e senha errada
      // não se distinguem.
      return responder({ detail: "usuário ou senha inválidos" }, 401);
    }
    if (url.startsWith("/api/auth/logout")) {
      autenticado = false;
      return new Response(null, { status: 204 });
    }

    if (config.status401) return responder({ error: "nao_autorizado", message: "" }, 401);

    if (init?.method === "PATCH") {
      let corpo: unknown = null;
      try {
        corpo = JSON.parse(String(init.body));
      } catch {
        corpo = null;
      }
      ultimoPatch = [url.split("?")[0] ?? url, corpo];
      if (config.patchErro) {
        return responder(
          { error: "transicao_invalida", message: "resolvido não volta para pendente" },
          config.patchErro,
        );
      }
      const id = url.split("/").pop() ?? "";
      const alvo = (handoffs.items as Array<Record<string, unknown>>).find((h) => h.id === id);
      const atualizado = { ...(alvo ?? { id }), ...(corpo as Record<string, unknown>) };
      handoffs = {
        ...handoffs,
        items: (handoffs.items as Array<Record<string, unknown>>).map((h) =>
          h.id === id ? atualizado : h,
        ),
      };
      return responder(atualizado);
    }

    if (url.startsWith("/api/handoffs")) {
      return responder(
        config.tudoVazio ? { items: [], pendentes: 0 } : { pendentes: 0, ...handoffs },
      );
    }
    if (url.startsWith("/api/quote-health")) {
      return responder(config.tudoVazio ? STATUS_VAZIO : (config.status ?? STATUS_VAZIO));
    }
    if (url.startsWith("/api/usage")) {
      return responder(config.tudoVazio ? USAGE_VAZIO : (config.usage ?? USAGE_VAZIO));
    }
    // ANTES do detalhe: `/api/conversations/c1/traces` também casa o regex do
    // detalhe, e sem esta linha o trace receberia o corpo da conversa.
    if (/^\/api\/conversations\/[^/]+\/traces/.test(url)) {
      return responder(config.traces ?? { items: [] });
    }
    if (/^\/api\/conversations\/[^?]/.test(url)) {
      if (config.conversaErro) {
        return responder({ error: "nao_encontrado", message: "conversa não encontrada" }, 404);
      }
      return responder({
        id: "c1",
        channel: "web",
        state: "novo",
        criado_em: new Date(0).toISOString(),
        perfil: {},
        messages: [],
        quotes: [],
        handoffs: [],
        ...(config.conversa ?? {}),
      });
    }
    if (url.startsWith("/api/conversations")) {
      return responder(config.tudoVazio ? { items: [], next_cursor: null } : conversas);
    }

    return responder({});
  }) as typeof fetch);

  const esperarSocket = async (): Promise<WebSocketFalso> => {
    for (let i = 0; i < 200; i += 1) {
      const s = WebSocketFalso.ultima;
      if (s !== null) {
        if (s.readyState !== 1) {
          await act(async () => {
            s.abrir();
          });
        }
        return s;
      }
      await act(async () => {
        await new Promise((r) => setTimeout(r, 5));
      });
    }
    throw new Error("nenhum socket de eventos foi aberto");
  };

  return {
    get ultimaUrl() {
      return ultimaUrl;
    },
    get ultimoPatch() {
      return ultimoPatch;
    },
    get socketsAbertos() {
      return WebSocketFalso.criadas;
    },
    chamadas(prefixo: string): number {
      return chamadasPorUrl.filter((u) => u.startsWith(prefixo)).length;
    },
    /** Muda o que o endpoint responde ANTES de empurrar o frame. */
    responderComPendentes(n: number): void {
      handoffs = { ...handoffs, pendentes: n };
    },
    responderComHandoff(h: Record<string, unknown>): void {
      handoffs = {
        pendentes: (handoffs.pendentes ?? 0) + 1,
        items: [...(handoffs.items as unknown[]), h],
      };
    },
    async push(quadro: unknown): Promise<void> {
      const s = await esperarSocket();
      await act(async () => {
        s.receber(quadro);
      });
      // Deixa o refetch disparado pelo push completar.
      await act(async () => {
        await new Promise((r) => setTimeout(r, 0));
      });
    },
    get autenticado() {
      return autenticado;
    },
    fechar(): void {
      WebSocketFalso.ultima?.close();
    },
  };
}
