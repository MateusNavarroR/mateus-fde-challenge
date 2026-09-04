/**
 * O transporte: `hello`/replay, reconexão com backoff e nada mais.
 *
 * A reconexão não é robustez extra. Com uma janela de até 37 s de socket aberto,
 * uma troca de rede ou um proxy impaciente apagariam justamente o aviso de espera
 * e o reforço — as duas mensagens que provam o comportamento sob falha.
 *
 * O protocolo de retomada: ao abrir (inclusive na primeira vez) o cliente manda
 * `{"type":"hello","last_index":N}` com o maior `index` que ele já tem (`-1`
 * quando não tem nenhum). O servidor responde com replay **do banco**, em ordem
 * de `index`. Como o reducer é idempotente por `id`, repetir não duplica — e é
 * por isso que o `hello` pode ser reenviado sem medo em toda reabertura.
 */

import { ROTAS, lerToken } from "./cliente";
import { TIPOS_EVENTO_ADMIN, TIPOS_EVENTO_CHAT } from "./tipos";
import type { EventoAdmin, EventoChat } from "./tipos";

export type StatusConexao = "conectando" | "conectado" | "reconectando" | "fechado";

const BASE_MS = 500;
const TETO_MS = 10_000;

export type Sessao = {
  fechar: () => void;
  enviar: (dado: unknown) => boolean;
  /** Delay do próximo reconnect, em ms. Zero quando não há reconexão agendada. */
  readonly proximaEsperaMs: number;
};

type Opcoes<E> = {
  aoEvento: (evento: E) => void;
  aoStatus?: (status: StatusConexao) => void;
  /** Só o chat usa: o `last_index` do `hello`. */
  ultimoIndex?: () => number;
};

/**
 * A URL sai do `location` — nunca de host fixo, que quebraria atrás do proxy do
 * compose e em qualquer origem que não seja a de desenvolvimento.
 */
export function urlDoSocket(caminho: string): string {
  const esquema = globalThis.location?.protocol === "https:" ? "wss:" : "ws:";
  const host = globalThis.location?.host ?? "127.0.0.1:5173";
  /*
   * O navegador não deixa o cliente pôr cabeçalho no handshake do WebSocket, e
   * o `X-Admin-Token` das rotas REST não tem equivalente aqui. Por decisão do
   * Núcleo, o token vai por query string quando existe — e não vai nenhum
   * parâmetro quando não existe, para que um token opcional não vire um token
   * obrigatório mal configurado. O controle que de fato importa continua sendo
   * o bind em 127.0.0.1 (DECISOES-FECHADAS §8).
   */
  const token = lerToken();
  const query = token === null ? "" : `?token=${encodeURIComponent(token)}`;
  return `${esquema}//${host}${caminho}${query}`;
}

function esperaDe(tentativa: number): number {
  const cheio = Math.min(BASE_MS * 2 ** tentativa, TETO_MS);
  // Jitter determinístico em amplitude (±10%): espalha o rebanho sem quebrar o
  // crescimento, e sem impedir que o teste asserte o teto.
  const jitter = cheio * 0.1 * (Math.random() * 2 - 1);
  return Math.min(TETO_MS, Math.max(1, Math.round(cheio + jitter)));
}

function conectar<E>(caminho: string, opts: Opcoes<E>, tiposValidos: readonly string[]): Sessao {
  let socket: WebSocket | null = null;
  let tentativa = 0;
  let espera = 0;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let encerrado = false;

  const status = (s: StatusConexao) => opts.aoStatus?.(s);

  const abrir = (): void => {
    if (encerrado) return;
    status("conectando");
    const ws = new WebSocket(urlDoSocket(caminho));
    socket = ws;

    ws.onopen = () => {
      if (encerrado) return;
      tentativa = 0;
      espera = 0;
      if (opts.ultimoIndex) {
        ws.send(JSON.stringify({ type: "hello", last_index: opts.ultimoIndex() }));
      }
      status("conectado");
    };

    ws.onmessage = (ev: { data: unknown }) => {
      if (encerrado) return;
      let quadro: unknown;
      try {
        quadro = typeof ev.data === "string" ? JSON.parse(ev.data) : ev.data;
      } catch {
        // Frame ilegível não derruba a conexão: o socket é longevo por desenho.
        return;
      }
      const tipo = (quadro as { type?: unknown } | null)?.type;
      // Um `type` do futuro é ignorado — nunca motivo para fechar o socket.
      if (typeof tipo !== "string" || !tiposValidos.includes(tipo)) return;
      opts.aoEvento(quadro as E);
    };

    ws.onerror = () => {
      /* o `close` que vem em seguida é quem agenda a reconexão */
    };

    ws.onclose = () => {
      if (encerrado) return;
      socket = null;
      espera = esperaDe(tentativa);
      tentativa += 1;
      status("reconectando");
      timer = setTimeout(abrir, espera);
    };
  };

  abrir();

  return {
    fechar() {
      encerrado = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
      espera = 0;
      const s = socket;
      socket = null;
      s?.close();
      status("fechado");
    },
    enviar(dado: unknown) {
      const s = socket;
      if (!s || s.readyState !== 1) return false;
      s.send(JSON.stringify(dado));
      return true;
    },
    get proximaEsperaMs() {
      return espera;
    },
  };
}

/** O canal do lead. Manda `hello` em toda abertura. */
export function conectarChat(
  conversationId: string,
  opts: Opcoes<EventoChat> & { ultimoIndex: () => number },
): Sessao {
  return conectar<EventoChat>(ROTAS.wsChat(conversationId), opts, TIPOS_EVENTO_CHAT);
}

/**
 * O push do admin. Mesma mecânica de reconexão, **sem** `hello`: aqui não há
 * replay porque a tela recarrega do endpoint em vez de montar item a partir do
 * frame — um item montado no cliente diverge do banco na primeira mudança de
 * schema, e o admin existe para dizer a verdade sobre o banco.
 */
export function conectarEventos(opts: Opcoes<EventoAdmin>): Sessao {
  return conectar<EventoAdmin>(ROTAS.eventos(), opts, TIPOS_EVENTO_ADMIN);
}
