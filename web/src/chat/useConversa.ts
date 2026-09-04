/**
 * O coração da tela `/chat` é uma **função pura**.
 *
 * A tela não decide nada sobre a conversa: recebe frames e os reduz. Não existe
 * `setTimeout(6000)` no navegador — se existisse, a política de degradação teria
 * duas cópias, e elas divergiriam na primeira mudança de limiar.
 *
 * Testar o reducer sem navegador é o que permite exercitar a janela de 37 s em
 * milissegundos: uma suíte que dorme 37 s ninguém roda.
 */

import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
import { gravarCru, lerCru } from "./textoCruLocal";
import { conectarChat, type StatusConexao } from "../api/ws";
import type { EstadoConversa, EventoChat, Message } from "../api/tipos";

export type Mensagem = Message & {
  /** Bolha otimista: existe na tela e ainda não no banco. */
  pendente: boolean;
  /**
   * Texto com valor monetário e `quote_id` nulo é **bug** (openapi.yaml,
   * invariante 1). A tela **exibe** o bug; quem o impede é o backend.
   */
  suspeitaDeBug: boolean;
};

export type Estado = {
  porId: Map<string, Mensagem>;
  /**
   * `id da mensagem → texto que o LEAD digitou`, antes do mascaramento.
   *
   * Só existe no navegador dele (`textoCruLocal.ts`). O servidor continua sem nunca
   * ter a versão crua persistida — o que muda é que o lead deixa de ver a própria
   * mensagem alterada, que parecia defeito.
   */
  cruDoLead: Record<string, string>;
  /** Ids temporários na ordem de envio. A reconciliação é FIFO. */
  pendentesDoLead: string[];
  mensagens: Mensagem[];
  digitando: boolean;
  state: EstadoConversa;
  entradaBloqueada: boolean;
  ultimoIndex: number;
  conexao: StatusConexao;
};

export type Acao =
  | EventoChat
  | { type: "envio-local"; idTemp: string; texto: string }
  | { type: "historico"; messages: Message[]; state?: EstadoConversa }
  | { type: "conexao"; status: StatusConexao };

/**
 * O mesmo regex de dinheiro do guardrail do Núcleo, transcrito. Um marcador que
 * dispara em "35 anos" viraria paranoia e ninguém olharia mais para ele.
 */
const DINHEIRO = /(R\$\s*[\d.,]+)|([\d.,]+\s*reais\b)/i;

function pareceCotacaoSemLastro(m: Message): boolean {
  // A fala do lead não é nossa: ele pode citar um valor sem que isso seja bug.
  if (m.autor === "lead") return false;
  const temQuote = m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "";
  return DINHEIRO.test(m.conteudo) && !temQuote;
}

function enriquecer(
  m: Message,
  pendente: boolean,
  cruDoLead: Record<string, string> = {},
): Mensagem {
  const cru = m.autor === "lead" ? cruDoLead[m.id] : undefined;
  return {
    ...m,
    // Só a fala do LEAD tem versão local. O que a empresa disse vem do servidor e
    // não pode ter uma segunda fonte da verdade.
    conteudo: cru ?? m.conteudo,
    pendente,
    suspeitaDeBug: pareceCotacaoSemLastro(m),
  };
}

export function estadoInicial(cruDoLead: Record<string, string> = {}): Estado {
  return {
    porId: new Map(),
    cruDoLead,
    pendentesDoLead: [],
    mensagens: [],
    digitando: false,
    state: "novo",
    entradaBloqueada: false,
    ultimoIndex: -1,
    conexao: "conectando",
  };
}

/**
 * A ordem é `index`, nunca chegada nem `criado_em`: os timestamps do dataset
 * estão 99,8 % fora de ordem, e sob replay de reconexão a chegada é arbitrária
 * por construção. As bolhas otimistas ficam no fim, porque ainda não têm índice.
 */
function derivar(porId: Map<string, Mensagem>, pendentes: string[]): Mensagem[] {
  const persistidas: Mensagem[] = [];
  for (const m of porId.values()) if (!m.pendente) persistidas.push(m);
  persistidas.sort((a, b) => a.index - b.index);
  const otimistas = pendentes
    .map((id) => porId.get(id))
    .filter((m): m is Mensagem => m !== undefined);
  return [...persistidas, ...otimistas];
}

function fechar(porId: Map<string, Mensagem>, pendentes: string[], base: Estado): Estado {
  const mensagens = derivar(porId, pendentes);
  let ultimo = -1;
  for (const m of mensagens) if (!m.pendente && m.index > ultimo) ultimo = m.index;
  return { ...base, porId, pendentesDoLead: pendentes, mensagens, ultimoIndex: ultimo };
}

export function reduzir(estado: Estado, acao: Acao): Estado {
  switch (acao.type) {
    case "message": {
      const porId = new Map(estado.porId);
      let pendentes = estado.pendentesDoLead;
      let cruDoLead = estado.cruDoLead;
      const chegando = acao.message;

      /*
       * Reconciliação da bolha otimista: **por id, nunca por texto**. O conteúdo
       * que volta já passou pelo mascaramento, e não existe endpoint que devolva
       * a versão crua — casar por texto duplicaria a bolha exatamente na conversa
       * que exercita PII. A fila é FIFO porque a camada de conversa enfileira em
       * vez de recusar, então o lead pode mandar duas antes do primeiro eco.
       */
      if (
        chegando.autor === "lead" &&
        chegando.index > estado.ultimoIndex &&
        pendentes.length > 0 &&
        !porId.has(chegando.id)
      ) {
        const [primeiro, ...resto] = pendentes;
        if (primeiro !== undefined) {
          // O texto cru migra do id temporário para o canônico junto com a bolha.
          const cru = estado.cruDoLead[primeiro];
          if (cru !== undefined) {
            cruDoLead = { ...cruDoLead, [chegando.id]: cru };
            delete cruDoLead[primeiro];
          }
          porId.delete(primeiro);
          pendentes = resto;
        }
      }

      porId.set(chegando.id, enriquecer(chegando, false, cruDoLead));
      return fechar(porId, pendentes, { ...estado, cruDoLead });
    }

    case "historico": {
      const porId = new Map(estado.porId);
      for (const m of acao.messages) porId.set(m.id, enriquecer(m, false, estado.cruDoLead));
      const base = acao.state
        ? { ...estado, state: acao.state, entradaBloqueada: acao.state === "encaminhado" }
        : estado;
      return fechar(porId, base.pendentesDoLead, base);
    }

    case "envio-local": {
      const porId = new Map(estado.porId);
      const otimista: Mensagem = {
        id: acao.idTemp,
        // Índice provisório: as pendentes são posicionadas no fim, não por ele.
        index: Number.MAX_SAFE_INTEGER,
        autor: "lead",
        tipo: "text",
        conteudo: acao.texto,
        status: "pending",
        quote_id: null,
        criado_em: new Date().toISOString(),
        pendente: true,
        suspeitaDeBug: false,
      };
      porId.set(acao.idTemp, otimista);
      return fechar(porId, [...estado.pendentesDoLead, acao.idTemp], {
        ...estado,
        cruDoLead: { ...estado.cruDoLead, [acao.idTemp]: acao.texto },
      });
    }

    /*
     * O digitando é por TURNO, não por mensagem. Um cliente ingênuo o apagaria
     * ao receber a primeira mensagem — e o lead veria o aviso de espera seguido
     * de 31 s de silêncio morto, que é exatamente o buraco que a política existe
     * para tapar.
     */
    case "typing":
      return { ...estado, digitando: acao.ativo };

    case "state":
      return {
        ...estado,
        state: acao.state,
        entradaBloqueada: acao.state === "encaminhado",
      };

    case "conexao":
      return { ...estado, conexao: acao.status };

    default:
      return estado;
  }
}

// ---------------------------------------------------------------------------

let contador = 0;
export function novoIdTemporario(): string {
  contador += 1;
  return `tmp-${contador}-${Date.now().toString(36)}`;
}

/** Liga o reducer ao socket. O componente não conhece o protocolo. */
export function useConversa(conversationId: string | null, historico?: Message[] | null) {
  // O texto cru do lead é lido do `sessionStorage` na montagem: um F5 no meio da
  // conversa mantém o que ele digitou, e fechar a aba o descarta.
  const [estado, despachar] = useReducer(reduzir, conversationId, (id) =>
    estadoInicial(id !== null ? lerCru(id) : {}),
  );
  const enviarRef = useRef<(texto: string) => boolean>(() => false);
  const ultimoIndexRef = useRef(-1);
  ultimoIndexRef.current = estado.ultimoIndex;

  useEffect(() => {
    if (!historico || historico.length === 0) return;
    despachar({ type: "historico", messages: historico });
  }, [historico]);

  // Persiste o cru do lead na sessão do NAVEGADOR. Nada disto é enviado, e o
  // servidor continua sem nunca ter a versão crua persistida.
  useEffect(() => {
    if (conversationId === null) return;
    gravarCru(conversationId, estado.cruDoLead);
  }, [conversationId, estado.cruDoLead]);

  useEffect(() => {
    if (conversationId === null) return;
    const sessao = conectarChat(conversationId, {
      ultimoIndex: () => ultimoIndexRef.current,
      aoEvento: (evento) => despachar(evento),
      aoStatus: (status) => despachar({ type: "conexao", status }),
    });
    enviarRef.current = (texto: string) => sessao.enviar({ type: "message", text: texto });
    return () => {
      enviarRef.current = () => false;
      sessao.fechar();
    };
  }, [conversationId]);

  const enviar = useCallback((texto: string) => {
    const idTemp = novoIdTemporario();
    despachar({ type: "envio-local", idTemp, texto });
    enviarRef.current(texto);
    return idTemp;
  }, []);

  return useMemo(() => ({ estado, enviar }), [estado, enviar]);
}
