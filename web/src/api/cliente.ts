/**
 * O cliente HTTP e a **origem única de URL** do projeto.
 *
 * Nenhum componente escreve `"/api/..."` no meio do JSX: é assim que uma rota
 * escapa do inventário, e o inventário (`tests/web/unit/openapi-deriva.test.ts`)
 * é o que garante que a UI só consome superfície que passou por decisão escrita.
 *
 * `ADMIN_TOKEN` é **opcional e exigido quando definido** (CLAUDE.md 14c). Sem
 * token gravado, nenhum cabeçalho é enviado — mandar um cabeçalho vazio
 * transformaria um token opcional em token obrigatório mal configurado.
 *
 * A **sessão de login não passa por aqui**, e isso é o ponto: ela vive num cookie
 * `httpOnly` que este código não consegue ler nem escrever. `credentials:
 * "same-origin"` é o que o navegador precisa para anexá-lo — e é o único
 * envolvimento do JavaScript com a credencial da operação. Nada de sessão em
 * `localStorage`: se este arquivo pudesse ler o segredo, um XSS também poderia.
 */

import type {
  ConversationDetail,
  Conversation,
  FilaHandoffs,
  Handoff,
  ListaDeTraces,
  PaginaConversas,
  QuoteHealth,
  Resumo,
  Saude,
  StatusHandoff,
  Usage,
} from "./tipos";

export const CHAVE_TOKEN = "autoseguro.admin_token";

/**
 * ⚠️ **`sessionStorage`, e o risco que sobra está declarado.**
 *
 * O `ADMIN_TOKEN` colado na tela de 401 é uma credencial de MÁQUINA que, no backend,
 * vale mais que a sessão: `exigir_admin` a aceita mesmo com `ADMIN_USER`/
 * `ADMIN_PASSWORD` configurados. Guardá-la no navegador significa que qualquer XSS na
 * página a lê — e isso continua verdade aqui.
 *
 * O que muda com `sessionStorage` em vez de `localStorage`: o token morre com a aba,
 * em vez de ficar em disco indefinidamente. Não protege contra XSS; protege contra a
 * próxima pessoa que abrir o navegador da operação.
 *
 * **A saída de verdade seria trocar o token por um cookie `httpOnly`** — como a
 * sessão de login já faz. Não foi feito porque a sessão é assinada com chave derivada
 * da credencial, e no modo só-token não existe credencial de onde derivá-la. Está
 * declarado no README como risco aceito, com a recomendação de preferir
 * `ADMIN_USER`/`ADMIN_PASSWORD` em qualquer instalação que use o navegador.
 */
function cofre(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    // Bloqueado (modo privado, política de site) não pode derrubar a tela.
    return null;
  }
}

/**
 * A superfície inteira que a UI consome, uma função por rota.
 *
 * Chamar com o sentinela `"{id}"` devolve o caminho no formato do OpenAPI, que é
 * como o teste de inventário casa cada rota com o contrato congelado.
 */
export const ROTAS = {
  health: () => "/api/health",
  conversas: (params?: { state?: string; limit?: number; cursor?: string }) => {
    const q = new URLSearchParams();
    if (params?.state) q.set("state", params.state);
    if (params?.limit !== undefined) q.set("limit", String(params.limit));
    if (params?.cursor) q.set("cursor", params.cursor);
    const s = q.toString();
    return s ? `/api/conversations?${s}` : "/api/conversations";
  },
  conversa: (id: string) => `/api/conversations/${id}`,
  resumo: () => "/api/resumo",
  status: (janela?: number) =>
    janela === undefined ? "/api/quote-health" : `/api/quote-health?janela=${janela}`,
  traces: (id: string) => `/api/conversations/${id}/traces`,
  usage: (conversationId?: string) =>
    conversationId === undefined ? "/api/usage" : `/api/usage?conversation_id=${conversationId}`,
  handoffs: (params?: { status?: StatusHandoff; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.status) q.set("status", params.status);
    if (params?.limit !== undefined) q.set("limit", String(params.limit));
    const s = q.toString();
    return s ? `/api/handoffs?${s}` : "/api/handoffs";
  },
  handoff: (id: string) => `/api/handoffs/${id}`,
  /** Caminho do WebSocket. O esquema e o host saem do `location`, em `ws.ts`. */
  wsChat: (id: string) => `/api/chat/${id}`,
  eventos: () => "/api/events",
} as const;

/**
 * As três rotas de autenticação, **fora do `openapi.yaml` congelado de propósito**.
 *
 * Elas ficam num objeto separado de `ROTAS` porque `ROTAS` é o inventário do
 * contrato: `tests/web/unit/openapi-deriva.test.ts` afirma que toda rota ali existe
 * na spec, e misturar as duas coisas obrigaria a relaxar essa afirmação — que é
 * justamente o teste que pega superfície não documentada.
 *
 * O `openapi.yaml` foi congelado na Fase 0 como o contrato do produto. Login não é
 * produto: é o mecanismo pelo qual um humano alcança o produto, e o backend as monta
 * com `include_in_schema=False`, com inventário fechado em `tests/nucleo/test_auth.py`.
 */
export const ROTAS_AUTENTICACAO = {
  estado: () => "/api/auth/estado",
  entrar: () => "/api/auth/login",
  sair: () => "/api/auth/logout",
} as const;

/** O que a UI precisa saber antes de decidir se mostra o login. */
export type EstadoAuth = {
  /** `false` quando a instalação não configurou ADMIN_USER/ADMIN_PASSWORD. */
  exigido: boolean;
  autenticado: boolean;
};

export type TipoErro =
  | "nao_autorizado"
  | "nao_encontrado"
  | "conflito"
  | "indisponivel"
  | "erro";

export class ErroApi extends Error {
  readonly tipo: TipoErro;
  readonly status: number | null;
  readonly error: string | null;

  constructor(tipo: TipoErro, message: string, status: number | null, error: string | null) {
    super(message);
    this.name = "ErroApi";
    this.tipo = tipo;
    this.status = status;
    this.error = error;
  }
}

export function lerToken(): string | null {
  try {
    const t = cofre()?.getItem(CHAVE_TOKEN);
    return t && t.length > 0 ? t : null;
  } catch {
    return null;
  }
}

export function gravarToken(token: string): void {
  try {
    const c = cofre();
    if (c === null) return;
    if (token.length > 0) c.setItem(CHAVE_TOKEN, token);
    else c.removeItem(CHAVE_TOKEN);
  } catch {
    /* idem */
  }
}

function cabecalhos(comCorpo: boolean): Headers {
  const h = new Headers();
  if (comCorpo) h.set("content-type", "application/json");
  const token = lerToken();
  // Só existe cabeçalho quando existe token. Nunca um cabeçalho vazio.
  if (token !== null) h.set("x-admin-token", token);
  return h;
}

function tipoDoStatus(status: number): TipoErro {
  if (status === 401 || status === 403) return "nao_autorizado";
  if (status === 404) return "nao_encontrado";
  if (status === 409) return "conflito";
  if (status >= 500) return "indisponivel";
  return "erro";
}

const TEXTO_PADRAO: Record<TipoErro, string> = {
  nao_autorizado: "Esta instalação exige um ADMIN_TOKEN.",
  nao_encontrado: "Recurso não encontrado.",
  conflito: "Transição inválida.",
  indisponivel: "O backend não respondeu.",
  erro: "A chamada falhou.",
};

async function executar<T>(url: string, init: RequestInit): Promise<T> {
  let resposta: Response;
  try {
    // `same-origin` anexa o cookie de sessão. É o default do `fetch` moderno, mas
    // explícito porque a autenticação inteira depende dele: um dia alguém troca o
    // `fetch` por outro cliente e o default some junto.
    resposta = await fetch(url, { credentials: "same-origin", ...init });
  } catch {
    // Backend fora do ar vira erro tipado, nunca uma tela em branco.
    throw new ErroApi("indisponivel", TEXTO_PADRAO.indisponivel, null, null);
  }

  if (!resposta.ok) {
    const tipo = tipoDoStatus(resposta.status);
    let message = TEXTO_PADRAO[tipo];
    let error: string | null = null;
    try {
      const corpo = (await resposta.json()) as Partial<{
        error: string;
        message: string;
        // As rotas do contrato devolvem `{error, message}`; o `HTTPException` do
        // FastAPI devolve `{detail}`. Ler só o primeiro fazia toda recusa de login
        // virar o texto genérico — e o texto genérico ainda falava de ADMIN_TOKEN.
        detail: string;
      }>;
      if (typeof corpo?.message === "string" && corpo.message.length > 0) message = corpo.message;
      else if (typeof corpo?.detail === "string" && corpo.detail.length > 0) message = corpo.detail;
      if (typeof corpo?.error === "string") error = corpo.error;
    } catch {
      // 401 sem corpo é comum: um erro tipado, não um crash de parse.
    }
    throw new ErroApi(tipo, message, resposta.status, error);
  }

  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

export function get<T>(url: string): Promise<T> {
  return executar<T>(url, { method: "GET", headers: cabecalhos(false) });
}

export function post<T>(url: string, corpo: unknown): Promise<T> {
  return executar<T>(url, {
    method: "POST",
    headers: cabecalhos(true),
    body: JSON.stringify(corpo),
  });
}

export function patch<T>(url: string, corpo: unknown): Promise<T> {
  return executar<T>(url, {
    method: "PATCH",
    headers: cabecalhos(true),
    body: JSON.stringify(corpo),
  });
}

// --- atalhos tipados -------------------------------------------------------

export const api = {
  saude: () => get<Saude>(ROTAS.health()),
  resumo: () => get<Resumo>(ROTAS.resumo()),
  traces: (id: string) => get<ListaDeTraces>(ROTAS.traces(id)),
  criarConversa: () => post<Conversation>(ROTAS.conversas(), { channel: "web" }),
  conversas: (params?: { state?: string; limit?: number; cursor?: string }) =>
    get<PaginaConversas>(ROTAS.conversas(params)),
  conversa: (id: string) => get<ConversationDetail>(ROTAS.conversa(id)),
  quoteHealth: (janela?: number) => get<QuoteHealth>(ROTAS.status(janela)),
  usage: (conversationId?: string) => get<Usage>(ROTAS.usage(conversationId)),
  handoffs: (params?: { status?: StatusHandoff; limit?: number }) =>
    get<FilaHandoffs>(ROTAS.handoffs(params)),
  transicionarHandoff: (id: string, status: StatusHandoff) =>
    patch<Handoff>(ROTAS.handoff(id), { status }),

  estadoAutenticacao: () => get<EstadoAuth>(ROTAS_AUTENTICACAO.estado()),
  /** Resolve quando a sessão foi criada; rejeita com `ErroApi` quando não. */
  entrar: (usuario: string, senha: string) =>
    post<void>(ROTAS_AUTENTICACAO.entrar(), { usuario, senha }),
  sair: () => post<void>(ROTAS_AUTENTICACAO.sair(), {}),
};
