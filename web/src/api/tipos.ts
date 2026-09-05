/**
 * Transcrição do contrato congelado (`docs/openapi.yaml`) — não invenção.
 *
 * Nada aqui é "o que o backend faz": é o que o documento promete. O teste
 * `tests/web/unit/tipos.test.ts` lê o YAML e compara enum a enum, que é o que
 * impede esta transcrição de envelhecer em silêncio; `openapi-deriva.test.ts`
 * fecha o cerco pelo lado das rotas.
 *
 * Campo anulável no contrato é `| null` aqui. Em particular `cache_read` e
 * `taxa_acerto_cache` **nunca** são `number` puro — é o tipo que obriga a tela a
 * tratar o "n/a" em vez de escorregar num `?? 0` (CLAUDE.md 26).
 */

export const ESTADOS_CONVERSA = [
  "novo",
  "qualificando",
  "cotando",
  "cotado",
  "fechado",
  "encaminhado",
] as const;
export type EstadoConversa = (typeof ESTADOS_CONVERSA)[number];

export const STATUS_MENSAGEM = ["received", "pending", "sent", "failed", "discarded"] as const;
export type StatusMensagem = (typeof STATUS_MENSAGEM)[number];

export const OUTCOMES = ["ok", "transient", "timeout", "refused", "bad_request"] as const;
export type Outcome = (typeof OUTCOMES)[number];

export const STATUS_JOB = ["pending", "ok", "refused", "failed"] as const;
export type StatusJob = (typeof STATUS_JOB)[number];

export const STATUS_HANDOFF = ["pendente", "assumido", "resolvido"] as const;
export type StatusHandoff = (typeof STATUS_HANDOFF)[number];

export const AUTORES = ["lead", "agente", "sistema", "operador"] as const;
export type Autor = (typeof AUTORES)[number];

export const TIPOS_MENSAGEM = ["text", "image", "audio", "document"] as const;
export type TipoMensagem = (typeof TIPOS_MENSAGEM)[number];

export const CANAIS = ["console", "web"] as const;
export type Canal = (typeof CANAIS)[number];

export const PLANOS = ["essencial", "completo", "premium"] as const;
export type Plano = (typeof PLANOS)[number];

/** Enum fechado. Um `default` genérico na tela esconderia um motivo novo. */
export const MOTIVOS_RECUSA = [
  "idade_acima_do_limite",
  "idade_abaixo_do_minimo",
  "veiculo_acima_de_20_anos",
] as const;
export type MotivoRecusa = (typeof MOTIVOS_RECUSA)[number];

export const ESTADOS_BREAKER = ["fechado", "aberto", "meia_abertura"] as const;
export type EstadoBreaker = (typeof ESTADOS_BREAKER)[number];

export const DISPARADO_POR = ["regra", "modelo"] as const;
export type DisparadoPor = (typeof DISPARADO_POR)[number];

/** Os sete gatilhos da tabela fechada (`DECISOES-FECHADAS.md` §3). */
export const GATILHOS_HANDOFF = [
  "assunto_sensivel",
  "guardrail",
  "lead_pediu",
  "cotacao_indisponivel",
  "extracao_falhou",
  "objecao_fora_da_alcada",
  "midia_sem_texto",
] as const;
export type GatilhoHandoff = (typeof GATILHOS_HANDOFF)[number];

// ---------------------------------------------------------------------------

export type Erro = {
  error: string;
  message: string;
};

export type Conversation = {
  id: string;
  channel: Canal;
  state: EstadoConversa;
  criado_em: string;
};

export type ConversationSummary = Conversation & {
  total_mensagens: number;
  atualizado_em: string;
  ultima_mensagem?: string | null;
  handoff_pendente?: boolean;
  ultima_cotacao_status?: StatusJob | null;
};

export type LeadProfile = {
  idade?: number | null;
  veiculo_ano?: number | null;
  /** 8 dígitos, sem máscara. Mascarado na exibição. */
  cep?: string | null;
  data_inicio?: string | null;
  plano_id?: Plano | null;
  campos_faltantes?: string[];
};

export type Message = {
  id: string;
  index: number;
  autor: Autor;
  tipo: TipoMensagem;
  /** Sempre a versão **mascarada**. Não existe endpoint com a crua. */
  conteudo: string;
  status: StatusMensagem;
  /** Não-nulo quando a mensagem apresenta uma cotação. Guardrail auditável. */
  quote_id?: string | null;
  criado_em: string;
};

/**
 * O trace de uma resposta do agente: as tools que ela executou, na ordem.
 *
 * A forma vem de `ai.agno_runs`, que é do Agno — por isso o backend não a congela num
 * Pydantic e por isso `cache_read` é anulável: o Ollama não popula o campo, e mostrar
 * "0 %" onde o provider não reporta seria inventar uma medição.
 */
export type ToolDoTrace = {
  nome: string;
  argumentos: Record<string, unknown>;
  resultado: string;
  duracao_ms: number;
  erro: boolean;
};

export type Trace = {
  run_id: string;
  index: number;
  status: string;
  modelo: string;
  provider: string;
  tokens_in: number;
  tokens_out: number;
  cache_read: number | null;
  duracao_ms: number;
  tools: readonly ToolDoTrace[];
};

export type ListaDeTraces = { items: readonly Trace[] };

export type QuoteAttempt = {
  id: string;
  attempt: number;
  /** Nulo quando não houve resposta (timeout ou erro de conexão). */
  http_status?: number | null;
  latency_ms: number;
  outcome: Outcome;
  criado_em: string;
};

export type TentativaComOrigem = QuoteAttempt & {
  quote_id?: string;
  conversation_id?: string;
};

export type QuoteResultado = {
  premio_mensal: number;
  franquia: number;
  moeda: string;
  coberturas: string[];
  carencia: {
    coberturas: string[];
    dias: number;
  };
  pro_rata?: {
    dias_no_mes: number;
    dias_cobrados: number;
    valor_primeiro_pagamento: number;
  } | null;
};

export type Quote = {
  id: string;
  status: StatusJob;
  request: {
    plano_id: Plano;
    idade: number;
    veiculo_ano: number;
    cep?: string | null;
    data_inicio?: string | null;
  };
  /** Presente **se e somente se** `status = ok`. */
  resultado?: QuoteResultado | null;
  /** Presente se e somente se `status = refused`. */
  motivo_recusa?: MotivoRecusa | null;
  erro_outcome?: Outcome | null;
  /**
   * O breaker impediu a chamada: o job é `failed` **sem nenhuma tentativa**. A
   * tela precisa distinguir isso de "tentamos 3 vezes e falhou".
   */
  circuito_aberto?: boolean;
  total_latency_ms?: number | null;
  attempts: QuoteAttempt[];
  criado_em: string;
};

export type Handoff = {
  id: string;
  conversation_id: string;
  trigger: string;
  reason: string;
  summary?: string | null;
  disparado_por: DisparadoPor;
  quote_id?: string | null;
  ultima_cotacao?: Quote | null;
  status: StatusHandoff;
  criado_em: string;
  assumido_em?: string | null;
  resolved_at?: string | null;
};

export type ConversationDetail = Conversation & {
  perfil: LeadProfile;
  /** Ordenado por `index`. Nunca por timestamp. */
  messages: Message[];
  quotes: Quote[];
  handoffs: Handoff[];
};

export type QuoteHealth = {
  upstream_health: {
    status: "ok" | "unreachable";
    latency_ms?: number | null;
    /** O `/health` do legado responde 200 mesmo com 100% das cotações falhando. */
    nota?: string;
  };
  janela: {
    total: number;
    sucesso: number;
    taxa_sucesso: number;
    p50_ms: number;
    /** Inclui as chamadas lentas de 8 s — é o que se quer ver. */
    p95_ms: number;
    por_outcome?: Record<string, number>;
  };
  breaker: {
    estado: EstadoBreaker;
    falhas_consecutivas: number;
    aberto_desde?: string | null;
    reabre_em?: string | null;
  };
  ultimas_tentativas: TentativaComOrigem[];
};

export type UsageAgregado = {
  tokens_in: number;
  tokens_out: number;
  /**
   * **Nulo, não zero**, quando o provider não reporta caching — o Ollama não
   * reporta. Zero diria "o cache não acertou" onde a verdade é "não existe
   * cache neste caminho".
   */
  cache_read?: number | null;
  cache_write?: number | null;
  taxa_acerto_cache?: number | null;
  /** Nulo para inferência local. Calculado pelo backend, nunca pela tela. */
  custo_usd?: number | null;
  pricing_vigencia?: string | null;
  latency_p50_ms?: number | null;
};

export type UsagePorProvider = UsageAgregado & { provider: string };
export type UsagePorConversa = UsageAgregado & { conversation_id: string; turnos?: number };

export type Usage = {
  total: UsageAgregado;
  por_provider: UsagePorProvider[];
  por_conversa: UsagePorConversa[];
};

export type PaginaConversas = {
  items: ConversationSummary[];
  next_cursor?: string | null;
};

export type FilaHandoffs = {
  items: Handoff[];
  pendentes: number;
};

/** Os números do painel. Cada campo é um recorte declarado — ver `/api/resumo`. */
export type Resumo = {
  conversas: number;
  conversas_encaminhadas: number;
  mensagens_enviadas: number;
  mensagens_recebidas: number;
  cotacoes_ok: number;
  cotacoes_recusadas: number;
  cotacoes_falhas: number;
  handoffs_pendentes: number;
  handoffs_total: number;
  cache: {
    turnos_medidos: number;
    tokens_do_cache: number;
    tokens_enviados: number;
    /** `null` quando não há turno medido — o Ollama não reporta cache. */
    fracao_do_cache: number | null;
    turnos_sem_cache: number;
  };
  evals: { total: number; passaram: number };
};

export type Saude = {
  status: "ok";
  db: "ok" | "degraded";
};

// --- frames do WebSocket ---------------------------------------------------

export type MessageEvent = { type: "message"; message: Message };
export type TypingEvent = { type: "typing"; ativo: boolean };
export type StateEvent = { type: "state"; state: EstadoConversa };

/** Servidor → cliente, no WS de chat. */
export type EventoChat = MessageEvent | TypingEvent | StateEvent;

export const TIPOS_EVENTO_CHAT = ["message", "typing", "state"] as const;

/**
 * Servidor → cliente, no WS `/api/events`. A UI **só usa o `type`**: o corpo é
 * ignorado de propósito, porque a tela recarrega do endpoint em vez de montar o
 * item a partir do frame.
 */
export const TIPOS_EVENTO_ADMIN = ["handoff.created", "handoff.updated", "quote.attempt"] as const;
export type TipoEventoAdmin = (typeof TIPOS_EVENTO_ADMIN)[number];
export type EventoAdmin = { type: TipoEventoAdmin } & Record<string, unknown>;

/** Cliente → servidor, na abertura do WS de chat (inclusive na primeira vez). */
export type Hello = { type: "hello"; last_index: number };
export type EnvioDoLead = { type: "message"; text: string; tipo?: TipoMensagem };
