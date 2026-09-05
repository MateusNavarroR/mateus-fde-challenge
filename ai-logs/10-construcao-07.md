# Sessão de construção 07

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 24 turnos; o `jsonl` de
> origem tinha 563 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - web/src/api/cliente.ts
  - web/src/api/tipos.ts
  - web/src/api/ws.ts
  - app/quote/client.py
  - tests/web/unit/cliente.test.ts
  - web/package-lock.json
  - web/src/chat/useConversa.ts
  - web/src/admin/PaginaStatus.tsx
  - tests/nucleo/test_resiliencia.py
  - web/src/chat/PaginaChat.tsx
  - web/src/admin/PainelCusto.tsx
  - web/src/admin/PaginaConversas.tsx
  - web/src/admin/DetalheConversa.tsx
  - web/src/admin/PaginaHandoffs.tsx
  - tests/nucleo/test_espera.py
  - app/quote/job.py
  - web/src/chat/sessao.ts
  - web/src/admin/LinhaDoTempoCotacao.tsx
  - tests/web/e2e/ajuda/cenario.ts
  - app/bootstrap.py
  - web/src/ui/Erro.tsx
  - tests/nucleo/test_bootstrap.py
  - web/src/admin/useEventos.ts
  - web/src/admin/LayoutAdmin.tsx
  - web/src/ui/formatar.ts
  - web/src/ui/useRecurso.ts
  - web/src/App.tsx
  - web/src/chat/BlocoCotacao.tsx
  - web/tsconfig.json
  - web/scripts/baixar-openapi.mjs

Unified diff (only + lines are new):

=== DIFF: web/src/api/cliente.ts ===
@@ -0,0 +1,187 @@
+/**
+ * O cliente HTTP e a **origem única de URL** do projeto.
+ *
+ * Nenhum componente escreve `"/api/..."` no meio do JSX: é assim que uma rota
+ * escapa do inventário, e o inventário (`tests/web/unit/openapi-deriva.test.ts`)
+ * é o que garante que a UI só consome superfície que passou por decisão escrita.
+ *
+ * `ADMIN_TOKEN` é **opcional e exigido quando definido** (CLAUDE.md 14c). Sem
+ * token gravado, nenhum cabeçalho é enviado — mandar um cabeçalho vazio
+ * transformaria um token opcional em token obrigatório mal configurado.
+ */
+
+import type {
+  ConversationDetail,
+  Conversation,
+  FilaHandoffs,
+  Handoff,
+  PaginaConversas,
+  QuoteHealth,
+  Saude,
+  StatusHandoff,
+  Usage,
+} from "./tipos";
+
+export const CHAVE_TOKEN = "autoseguro.admin_token";
+
+/**
+ * A superfície inteira que a UI consome, uma função por rota.
+ *
+ * Chamar com o sentinela `"{id}"` devolve o caminho no formato do OpenAPI, que é
+ * como o teste de inventário casa cada rota com o contrato congelado.
+ */
+export const ROTAS = {
+  health: () => "/api/health",
+  conversas: (params?: { state?: string; limit?: number; cursor?: string }) => {
+    const q = new URLSearchParams();
+    if (params?.state) q.set("state", params.state);
+    if (params?.limit !== undefined) q.set("limit", String(params.limit));
+    if (params?.cursor) q.set("cursor", params.cursor);
+    const s = q.toString();
+    return s ? `/api/conversations?${s}` : "/api/conversations";
+  },
+  conversa: (id: string) => `/api/conversations/${id}`,
+  status: (janela?: number) =>
+    janela === undefined ? "/api/quote-health" : `/api/quote-health?janela=${janela}`,
+  usage: (conversationId?: string) =>
+    conversationId === undefined ? "/api/usage" : `/api/usage?conversation_id=${conversationId}`,
+  handoffs: (params?: { status?: StatusHandoff; limit?: number }) => {
+    const q = new URLSearchParams();
+    if (params?.status) q.set("status", params.status);
+    if (params?.limit !== undefined) q.set("limit", String(params.limit));
+    const s = q.toString();
+    return s ? `/api/handoffs?${s}` : "/api/handoffs";
+  },
+  handoff: (id: string) => `/api/handoffs/${id}`,
+  /** Caminho do WebSocket. O esquema e o host saem do `location`, em `ws.ts`. */
+  wsChat: (id: string) => `/api/chat/${id}`,
+  eventos: () => "/api/events",
+} as const;
+
+export type TipoErro =
+  | "nao_autorizado"
+  | "nao_encontrado"
+  | "conflito"
+  | "indisponivel"
+  | "erro";
+
+export class ErroApi extends Error {
+  readonly tipo: TipoErro;
+  readonly status: number | null;
+  readonly error: string | null;
+
+  constructor(tipo: TipoErro, message: string, status: number | null, error: string | null) {
+    super(message);
+    this.name = "ErroApi";
+    this.tipo = tipo;
+    this.status = status;
+    this.error = error;
+  }
+}
+
+export function lerToken(): string | null {
+  try {
+    const t = localStorage.getItem(CHAVE_TOKEN);
+    return t && t.length > 0 ? t : null;
+  } catch {
+    // localStorage bloqueado (modo privado, política de site) não pode derrubar a tela.
+    return null;
+  }
+}
+
+export function gravarToken(token: string): void {
+  try {
+    if (token.length > 0) localStorage.setItem(CHAVE_TOKEN, token);
+    else localStorage.removeItem(CHAVE_TOKEN);
+  } catch {
+    /* idem */
+  }
+}
+
+function cabecalhos(comCorpo: boolean): Headers {
+  const h = new Headers();
+  if (comCorpo) h.set("content-type", "application/json");
+  const token = lerToken();
+  // Só existe cabeçalho quando existe token. Nunca um cabeçalho vazio.
+  if (token !== null) h.set("x-admin-token", token);
+  return h;
+}
+
+function tipoDoStatus(status: number): TipoErro {
+  if (status === 401 || status === 403) return "nao_autorizado";
+  if (status === 404) return "nao_encontrado";
+  if (status === 409) return "conflito";
+  if (status >= 500) return "indisponivel";
+  return "erro";
+}
+
+const TEXTO_PADRAO: Record<TipoErro, string> = {
+  nao_autorizado: "Esta instalação exige um ADMIN_TOKEN.",
+  nao_encontrado: "Recurso não encontrado.",
+  conflito: "Transição inválida.",
+  indisponivel: "O backend não respondeu.",
+  erro: "A chamada falhou.",
+};
+
+async function executar<T>(url: string, init: RequestInit): Promise<T> {
+  let resposta: Response;
+  try {
+    resposta = await fetch(url, init);
+  } catch {
+    // Backend fora do ar vira erro tipado, nunca uma tela em branco.
+    throw new ErroApi("indisponivel", TEXTO_PADRAO.indisponivel, null, null);
+  }
+
+  if (!resposta.ok) {
+    const tipo = tipoDoStatus(resposta.status);
+    let message = TEXTO_PADRAO[tipo];
+    let error: string | null = null;
+    try {
+      const corpo = (await resposta.json()) as Partial<{ error: string; message: string }>;
+      if (typeof corpo?.message === "string" && corpo.message.length > 0) message = corpo.message;
+      if (typeof corpo?.error === "string") error = corpo.error;
+    } catch {
+      // 401 sem corpo é comum: um erro tipado, não um crash de parse.
+    }
+    throw new ErroApi(tipo, message, resposta.status, error);
+  }
+
+  if (resposta.status === 204) return undefined as T;
+  return (await resposta.json()) as T;
+}
+
+export function get<T>(url: string): Promise<T> {
+  return executar<T>(url, { method: "GET", headers: cabecalhos(false) });
+}
+
+export function post<T>(url: string, corpo: unknown): Promise<T> {
+  return executar<T>(url, {
+    method: "POST",
+    headers: cabecalhos(true),
+    body: JSON.stringify(corpo),
+  });
+}
+
+export function patch<T>(url: string, corpo: unknown): Promise<T> {
+  return executar<T>(url, {
+    method: "PATCH",
+    headers: cabecalhos(true),
+    body: JSON.stringify(corpo),
+  });
+}
+
+// --- atalhos tipados -------------------------------------------------------
+
+export const api = {
+  saude: () => get<Saude>(ROTAS.health()),
+  criarConversa: () => post<Conversation>(ROTAS.conversas(), { channel: "web" }),
+  conversas: (params?: { state?: string; limit?: number; cursor?: string }) =>
+    get<PaginaConversas>(ROTAS.conversas(params)),
+  conversa: (id: string) => get<ConversationDetail>(ROTAS.conversa(id)),
+  quoteHealth: (janela?: number) => get<QuoteHealth>(ROTAS.status(janela)),
+  usage: (conversationId?: string) => get<Usage>(ROTAS.usage(conversationId)),
+  handoffs: (params?: { status?: StatusHandoff; limit?: number }) =>
+    get<FilaHandoffs>(ROTAS.handoffs(params)),
+  transicionarHandoff: (id: string, status: StatusHandoff) =>
+    patch<Handoff>(ROTAS.handoff(id), { status }),
+};


=== DIFF: web/src/api/tipos.ts ===
@@ -0,0 +1,286 @@
+/**
+ * Transcrição do contrato congelado (`docs/openapi.yaml`) — não invenção.
+ *
+ * Nada aqui é "o que o backend faz": é o que o documento promete. O teste
+ * `tests/web/unit/tipos.test.ts` lê o YAML e compara enum a enum, que é o que
+ * impede esta transcrição de envelhecer em silêncio; `openapi-deriva.test.ts`
+ * fecha o cerco pelo lado das rotas.
+ *
+ * Campo anulável no contrato é `| null` aqui. Em particular `cache_read` e
+ * `taxa_acerto_cache` **nunca** são `number` puro — é o tipo que obriga a tela a
+ * tratar o "n/a" em vez de escorregar num `?? 0` (CLAUDE.md 26).
+ */
+
+export const ESTADOS_CONVERSA = [
+  "novo",
+  "qualificando",
+  "cotando",
+  "cotado",
+  "fechado",
+  "encaminhado",
+] as const;
+export type EstadoConversa = (typeof ESTADOS_CONVERSA)[number];
+
+export const STATUS_MENSAGEM = ["received", "pending", "sent", "failed", "discarded"] as const;
+export type StatusMensagem = (typeof STATUS_MENSAGEM)[number];
+
+export const OUTCOMES = ["ok", "transient", "timeout", "refused", "bad_request"] as const;
+export type Outcome = (typeof OUTCOMES)[number];
+
+export const STATUS_JOB = ["pending", "ok", "refused", "failed"] as const;
+export type StatusJob = (typeof STATUS_JOB)[number];
+
+export const STATUS_HANDOFF = ["pendente", "assumido", "resolvido"] as const;
+export type StatusHandoff = (typeof STATUS_HANDOFF)[number];
+
+export const AUTORES = ["lead", "agente", "sistema", "operador"] as const;
+export type Autor = (typeof AUTORES)[number];
+
+export const TIPOS_MENSAGEM = ["text", "image", "audio", "document"] as const;
+export type TipoMensagem = (typeof TIPOS_MENSAGEM)[number];
+
+export const CANAIS = ["console", "web"] as const;
+export type Canal = (typeof CANAIS)[number];
+
+export const PLANOS = ["essencial", "completo", "premium"] as const;
+export type Plano = (typeof PLANOS)[number];
+
+/** Enum fechado. Um `default` genérico na tela esconderia um motivo novo. */
+export const MOTIVOS_RECUSA = [
+  "idade_acima_do_limite",
+  "idade_abaixo_do_minimo",
+  "veiculo_acima_de_20_anos",
+] as const;
+export type MotivoRecusa = (typeof MOTIVOS_RECUSA)[number];
+
+export const ESTADOS_BREAKER = ["fechado", "aberto", "meia_abertura"] as const;
+export type EstadoBreaker = (typeof ESTADOS_BREAKER)[number];
+
+export const DISPARADO_POR = ["regra", "modelo"] as const;
+export type DisparadoPor = (typeof DISPARADO_POR)[number];
+
+/** Os sete gatilhos da tabela fechada (`DECISOES-FECHADAS.md` §3). */
+export const GATILHOS_HANDOFF = [
+  "assunto_sensivel",
+  "guardrail",
+  "lead_pediu",
+  "cotacao_indisponivel",
+  "extracao_falhou",
+  "objecao_fora_da_alcada",
+  "midia_sem_texto",
+] as const;
+export type GatilhoHandoff = (typeof GATILHOS_HANDOFF)[number];
+
+// ---------------------------------------------------------------------------
+
+export type Erro = {
+  error: string;
+  message: string;
+};
+
+export type Conversation = {
+  id: string;
+  channel: Canal;
+  state: EstadoConversa;
+  criado_em: string;
+};
+
+export type ConversationSummary = Conversation & {
+  total_mensagens: number;
+  atualizado_em: string;
+  ultima_mensagem?: string | null;
+  handoff_pendente?: boolean;
+  ultima_cotacao_status?: StatusJob | null;
+};
+
+export type LeadProfile = {
+  idade?: number | null;
+  veiculo_ano?: number | null;
+  /** 8 dígitos, sem máscara. Mascarado na exibição. */
+  cep?: string | null;
+  data_inicio?: string | null;
+  plano_id?: Plano | null;
+  campos_faltantes?: string[];
+};
+
+export type Message = {
+  id: string;
+  index: number;
+  autor: Autor;
+  tipo: TipoMensagem;
+  /** Sempre a versão **mascarada**. Não existe endpoint com a crua. */
+  conteudo: string;
+  status: StatusMensagem;
+  /** Não-nulo quando a mensagem apresenta uma cotação. Guardrail auditável. */
+  quote_id?: string | null;
+  criado_em: string;
+};
+
+export type QuoteAttempt = {
+  id: string;
+  attempt: number;
+  /** Nulo quando não houve resposta (timeout ou erro de conexão). */
+  http_status?: number | null;
+  latency_ms: number;
+  outcome: Outcome;
+  criado_em: string;
+};
+
+export type TentativaComOrigem = QuoteAttempt & {
+  quote_id?: string;
+  conversation_id?: string;
+};
+
+export type QuoteResultado = {
+  premio_mensal: number;
+  franquia: number;
+  moeda: string;
+  coberturas: string[];
+  carencia: {
+    coberturas: string[];
+    dias: number;
+  };
+  pro_rata?: {
+    dias_no_mes: number;
+    dias_cobrados: number;
+    valor_primeiro_pagamento: number;
+  } | null;
+};
+
+export type Quote = {
+  id: string;
+  status: StatusJob;
+  request: {
+    plano_id: Plano;
+    idade: number;
+    veiculo_ano: number;
+    cep?: string | null;
+    data_inicio?: string | null;
+  };
+  /** Presente **se e somente se** `status = ok`. */
+  resultado?: QuoteResultado | null;
+  /** Presente se e somente se `status = refused`. */
+  motivo_recusa?: MotivoRecusa | null;
+  erro_outcome?: Outcome | null;
+  /**
+   * O breaker impediu a chamada: o job é `failed` **sem nenhuma tentativa**. A
+   * tela precisa distinguir isso de "tentamos 3 vezes e falhou".
+   */
+  circuito_aberto?: boolean;
+  total_latency_ms?: number | null;
+  attempts: QuoteAttempt[];
+  criado_em: string;
+};
+
+export type Handoff = {
+  id: string;
+  conversation_id: string;
+  trigger: string;
+  reason: string;
+  summary?: string | null;
+  disparado_por: DisparadoPor;
+  quote_id?: string | null;
+  ultima_cotacao?: Quote | null;
+  status: StatusHandoff;
+  criado_em: string;
+  assumido_em?: string | null;
+  resolved_at?: string | null;
+};
+
+export type ConversationDetail = Conversation & {
+  perfil: LeadProfile;
+  /** Ordenado por `index`. Nunca por timestamp. */
+  messages: Message[];
+  quotes: Quote[];
+  handoffs: Handoff[];
+};
+
+export type QuoteHealth = {
+  upstream_health: {
+    status: "ok" | "unreachable";
+    latency_ms?: number | null;
+    /** O `/health` do legado responde 200 mesmo com 100% das cotações falhando. */
+    nota?: string;
+  };
+  janela: {
+    total: number;
+    sucesso: number;
+    taxa_sucesso: number;
+    p50_ms: number;
+    /** Inclui as chamadas lentas de 8 s — é o que se quer ver. */
+    p95_ms: number;
+    por_outcome?: Record<string, number>;
+  };
+  breaker: {
+    estado: EstadoBreaker;
+    falhas_consecutivas: number;
+    aberto_desde?: string | null;
+    reabre_em?: string | null;
+  };
+  ultimas_tentativas: TentativaComOrigem[];
+};
+
+export type UsageAgregado = {
+  tokens_in: number;
+  tokens_out: number;
+  /**
+   * **Nulo, não zero**, quando o provider não reporta caching — o Ollama não
+   * reporta. Zero diria "o cache não acertou" onde a verdade é "não existe
+   * cache neste caminho".
+   */
+  cache_read?: number | null;
+  cache_write?: number | null;
+  taxa_acerto_cache?: number | null;
+  /** Nulo para inferência local. Calculado pelo backend, nunca pela tela. */
+  custo_usd?: number | null;
+  pricing_vigencia?: string | null;
+  latency_p50_ms?: number | null;
+};
+
+export type UsagePorProvider = UsageAgregado & { provider: string };
+export type UsagePorConversa = UsageAgregado & { conversation_id: string; turnos?: number };
+
+export type Usage = {
+  total: UsageAgregado;
+  por_provider: UsagePorProvider[];
+  por_conversa: UsagePorConversa[];
+};
+
+export type PaginaConversas = {
+  items: ConversationSummary[];
+  next_cursor?: string | null;
+};
+
+export type FilaHandoffs = {
+  items: Handoff[];
+  pendentes: number;
+};
+
+export type Saude = {
+  status: "ok";
+  db: "ok" | "degraded";
+};
+
+// --- frames do WebSocket ---------------------------------------------------
+
+export type MessageEvent = { type: "message"; message: Message };
+export type TypingEvent = { type: "typing"; ativo: boolean };
+export type StateEvent = { type: "state"; state: EstadoConversa };
+
+/** Servidor → cliente, no WS de chat. */
+export type EventoChat = MessageEvent | TypingEvent | StateEvent;
+
+export const TIPOS_EVENTO_CHAT = ["message", "typing", "state"] as const;
+
+/**
+ * Servidor → cliente, no WS `/api/events`. A UI **só usa o `type`**: o corpo é
+ * ignorado de propósito, porque a tela recarrega do endpoint em vez de montar o
+ * item a partir do frame.
+ */
+export const TIPOS_EVENTO_ADMIN = ["handoff.created", "handoff.updated", "quote.attempt"] as const;
+export type TipoEventoAdmin = (typeof TIPOS_EVENTO_ADMIN)[number];
+export type EventoAdmin = { type: TipoEventoAdmin } & Record<string, unknown>;
+
+/** Cliente → servidor, na abertura do WS de chat (inclusive na primeira vez). */
+export type Hello = { type: "hello"; last_index: number };
+export type EnvioDoLead = { type: "message"; text: string };


=== DIFF: web/src/api/ws.ts ===
@@ -0,0 +1,161 @@
+/**
+ * O transporte: `hello`/replay, reconexão com backoff e nada mais.
+ *
+ * A reconexão não é robustez extra. Com uma janela de até 37 s de socket aberto,
+ * uma troca de rede ou um proxy impaciente apagariam justamente o aviso de espera
+ * e o reforço — as duas mensagens que provam o comportamento sob falha.
+ *
+ * O protocolo de retomada: ao abrir (inclusive na primeira vez) o cliente manda
+ * `{"type":"hello","last_index":N}` com o maior `index` que ele já tem (`-1`
+ * quando não tem nenhum). O servidor responde com replay **do banco**, em ordem
+ * de `index`. Como o reducer é idempotente por `id`, repetir não duplica — e é
+ * por isso que o `hello` pode ser reenviado sem medo em toda reabertura.
+ */
+
+import { ROTAS, lerToken } from "./cliente";
+import { TIPOS_EVENTO_ADMIN, TIPOS_EVENTO_CHAT } from "./tipos";
+import type { EventoAdmin, EventoChat } from "./tipos";
+
+export type StatusConexao = "conectando" | "conectado" | "reconectando" | "fechado";
+
+const BASE_MS = 500;
+const TETO_MS = 10_000;
+
+export type Sessao = {
+  fechar: () => void;
+  enviar: (dado: unknown) => boolean;
+  /** Delay do próximo reconnect, em ms. Zero quando não há reconexão agendada. */
+  readonly proximaEsperaMs: number;
+};
+
+type Opcoes<E> = {
+  aoEvento: (evento: E) => void;
+  aoStatus?: (status: StatusConexao) => void;
+  /** Só o chat usa: o `last_index` do `hello`. */
+  ultimoIndex?: () => number;
+};
+
+/**
+ * A URL sai do `location` — nunca de host fixo, que quebraria atrás do proxy do
+ * compose e em qualquer origem que não seja a de desenvolvimento.
+ */
+export function urlDoSocket(caminho: string): string {
+  const esquema = globalThis.location?.protocol === "https:" ? "wss:" : "ws:";
+  const host = globalThis.location?.host ?? "127.0.0.1:5173";
+  /*
+   * O navegador não deixa o cliente pôr cabeçalho no handshake do WebSocket, e
+   * o `X-Admin-Token` das rotas REST não tem equivalente aqui. Por decisão do
+   * Núcleo, o token vai por query string quando existe — e não vai nenhum
+   * parâmetro quando não existe, para que um token opcional não vire um token
+   * obrigatório mal configurado. O controle que de fato importa continua sendo
+   * o bind em 127.0.0.1 (DECISOES-FECHADAS §8).
+   */
+  const token = lerToken();
+  const query = token === null ? "" : `?token=${encodeURIComponent(token)}`;
+  return `${esquema}//${host}${caminho}${query}`;
+}
+
+function esperaDe(tentativa: number): number {
+  const cheio = Math.min(BASE_MS * 2 ** tentativa, TETO_MS);
+  // Jitter determinístico em amplitude (±10%): espalha o rebanho sem quebrar o
+  // crescimento, e sem impedir que o teste asserte o teto.
+  const jitter = cheio * 0.1 * (Math.random() * 2 - 1);
+  return Math.min(TETO_MS, Math.max(1, Math.round(cheio + jitter)));
+}
+
+function conectar<E>(caminho: string, opts: Opcoes<E>, tiposValidos: readonly string[]): Sessao {
+  let socket: WebSocket | null = null;
+  let tentativa = 0;
+  let espera = 0;
+  let timer: ReturnType<typeof setTimeout> | null = null;
+  let encerrado = false;
+
+  const status = (s: StatusConexao) => opts.aoStatus?.(s);
+
+  const abrir = (): void => {
+    if (encerrado) return;
+    status("conectando");
+    const ws = new WebSocket(urlDoSocket(caminho));
+    socket = ws;
+
+    ws.onopen = () => {
+      if (encerrado) return;
+      tentativa = 0;
+      espera = 0;
+      if (opts.ultimoIndex) {
+        ws.send(JSON.stringify({ type: "hello", last_index: opts.ultimoIndex() }));
+      }
+      status("conectado");
+    };
+
+    ws.onmessage = (ev: { data: unknown }) => {
+      if (encerrado) return;
+      let quadro: unknown;
+      try {
+        quadro = typeof ev.data === "string" ? JSON.parse(ev.data) : ev.data;
+      } catch {
+        // Frame ilegível não derruba a conexão: o socket é longevo por desenho.
+        return;
+      }
+      const tipo = (quadro as { type?: unknown } | null)?.type;
+      // Um `type` do futuro é ignorado — nunca motivo para fechar o socket.
+      if (typeof tipo !== "string" || !tiposValidos.includes(tipo)) return;
+      opts.aoEvento(quadro as E);
+    };
+
+    ws.onerror = () => {
+      /* o `close` que vem em seguida é quem agenda a reconexão */
+    };
+
+    ws.onclose = () => {
+      if (encerrado) return;
+      socket = null;
+      espera = esperaDe(tentativa);
+      tentativa += 1;
+      status("reconectando");
+      timer = setTimeout(abrir, espera);
+    };
+  };
+
+  abrir();
+
+  return {
+    fechar() {
+      encerrado = true;
+      if (timer !== null) clearTimeout(timer);
+      timer = null;
+      espera = 0;
+      const s = socket;
+      socket = null;
+      s?.close();
+      status("fechado");
+    },
+    enviar(dado: unknown) {
+      const s = socket;
+      if (!s || s.readyState !== 1) return false;
+      s.send(JSON.stringify(dado));
+      return true;
+    },
+    get proximaEsperaMs() {
+      return espera;
+    },
+  };
+}
+
+/** O canal do lead. Manda `hello` em toda abertura. */
+export function conectarChat(
+  conversationId: string,
+  opts: Opcoes<EventoChat> & { ultimoIndex: () => number },
+): Sessao {
+  return conectar<EventoChat>(ROTAS.wsChat(conversationId), opts, TIPOS_EVENTO_CHAT);
+}
+
+/**
+ * O push do admin. Mesma mecânica de reconexão, **sem** `hello`: aqui não há
+ * replay porque a tela recarrega do endpoint em vez de montar item a partir do
+ * frame — um item montado no cliente diverge do banco na primeira mudança de
+ * schema, e o admin existe para dizer a verdade sobre o banco.
+ */
+export function conectarEventos(opts: Opcoes<EventoAdmin>): Sessao {
+  return conectar<EventoAdmin>(ROTAS.eventos(), opts, TIPOS_EVENTO_ADMIN);
+}


=== DIFF: app/quote/client.py ===
@@ -4,12 +4,21 @@ Tudo que é status, tentativa, backoff e semáforo vive **abaixo da fronteira da
 Um modelo exposto a "recebi 503" improvisa, e improvisar aí é a falha que esta
 arquitetura existe para impedir.
 
-Nesta fatia o cliente só chama e classifica. Retry, backoff e semáforo chegam na
-fatia 4 — construir tudo agora seria construir muito antes de qualquer coisa rodar.
+O `read timeout` é maior que `QUOTE_SLOW_SECONDS`: 10% das chamadas dormem 8,004 s e
+devolvem **200 correto**, e um timeout menor converte sucesso em falha — que o retry
+então reproduz, porque o próximo sorteio pode cair de novo na faixa lenta.
+
+O **semáforo** existe porque o handler do legado é síncrono e roda no threadpool do
+AnyIO, cujo limite é 40. Medido: 60 chamadas lentas simultâneas → 40 em ~8,8 s e 20
+enfileiradas para ~16,6 s, acima do nosso timeout. Sem limitar, o dimensionamento do
+timeout deixa de valer exatamente quando há mais leads — e o modo de falha é o pior
+possível: falha artificial em massa.
 """
 
 from __future__ import annotations
 
+import random
+import threading
 import time
 
 import httpx
@@ -42,6 +51,63 @@ class Resposta:
         return classificar_erro(self.http_status, self.corpo, timeout=self.timeout)
 
 
+class Semaforo:
+    """Limita as chamadas em voo contra a `/quote`.
+
+    Expõe `maximo_em_voo` porque a asserção que prova o semáforo é sobre o **máximo
+    simultâneo**, não sobre a latência final: com menos de 40 chamadas o legado não
+    degrada, e um teste que só olha latência passaria com a feature ausente.
+    """
+
+    def __init__(self, limite: int) -> None:
+        self._sem = threading.Semaphore(limite)
+        self._lock = threading.Lock()
+        self.em_voo = 0
+        self.maximo_em_voo = 0
+
+    def __enter__(self):
+        self._sem.acquire()
+        with self._lock:
+            self.em_voo += 1
+            self.maximo_em_voo = max(self.maximo_em_voo, self.em_voo)
+        return self
+
+    def __exit__(self, *exc) -> None:
+        with self._lock:
+            self.em_voo -= 1
+        self._sem.release()
+
+    def zerar(self) -> None:
+        self.maximo_em_voo = 0
+
+
+_semaforo: Semaforo | None = None
+
+
+def semaforo() -> Semaforo:
+    global _semaforo
+    if _semaforo is None:
+        _semaforo = Semaforo(get_settings().quote_max_concorrencia)
+    return _semaforo
+
+
+def resetar_semaforo() -> None:
+    """Só para a suíte."""
+    global _semaforo
+    _semaforo = None
+
+
+def calcular_backoff(tentativa: int) -> float:
+    """Exponencial com **full jitter**, com teto.
+
+    Não há `Retry-After` no 5xx do legado — o backoff é 100% nosso. O jitter evita
+    que várias conversas retentem no mesmo instante e sincronizem a carga.
+    """
+    cfg = get_settings()
+    teto = min(cfg.quote_backoff_teto_s, cfg.quote_backoff_base_s * (2 ** (tentativa - 1)))
+    return random.uniform(0, teto)
+
+
 def chamar(req: QuoteRequest, *, url: str | None = None) -> Resposta:
     """Uma tentativa. Não retenta, não classifica além do necessário.
 
@@ -51,6 +117,13 @@ def chamar(req: QuoteRequest, *, url: str | None = None) -> Resposta:
     """
     cfg = get_settings()
     base = url or cfg.quote_api_url
+    with semaforo():
+        return _chamar_sem_semaforo(req, base, cfg)
+
+
+def _chamar_sem_semaforo(req: QuoteRequest, base: str, cfg) -> Resposta:
+    # A espera no semáforo NÃO conta contra o read timeout: é fila nossa, não latência
+    # do legado. O cronômetro começa aqui.
     t0 = time.monotonic()
     try:
         r = httpx.post(


=== DIFF: tests/web/unit/cliente.test.ts ===
@@ -0,0 +1,69 @@
+import { beforeEach, expect, it, vi } from "vitest";
+import { ROTAS, get, patch } from "../../../web/src/api/cliente";
+
+beforeEach(() => {
+  localStorage.clear();
+  vi.restoreAllMocks();
+});
+
+it("sem token, nenhum cabeçalho de admin é enviado", async () => {
+  // Cabeçalho vazio transformaria um token opcional em token obrigatório mal
+  // configurado (CLAUDE.md 14c).
+  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ items: [] }));
+  await get(ROTAS.handoffs());
+  expect([...new Headers(f.mock.calls[0]![1]!.headers).keys()]).not.toContain("x-admin-token");
+});
+
+it("com token gravado, o cabeçalho vai em toda chamada", async () => {
+  localStorage.setItem("autoseguro.admin_token", "t-abc");
+  const f = vi.spyOn(globalThis, "fetch").mockResolvedValue(Response.json({ items: [] }));
+  await get(ROTAS.handoffs());
+  expect(new Headers(f.mock.calls[0]![1]!.headers).get("x-admin-token")).toBe("t-abc");
+});
+
+it("401 vira um erro tipado, não um crash de parse", async () => {
+  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 401 }));
+  await expect(get(ROTAS.status())).rejects.toMatchObject({ tipo: "nao_autorizado" });
+});
+
+it("409 na transição de handoff preserva a mensagem do backend", async () => {
+  vi.spyOn(globalThis, "fetch").mockResolvedValue(
+    Response.json(
+      { error: "transicao_invalida", message: "resolvido não volta para pendente" },
+      { status: 409 },
+    ),
+  );
+  await expect(patch(ROTAS.handoff("h1"), { status: "pendente" })).rejects.toMatchObject({
+    tipo: "conflito",
+    message: /resolvido não volta/,
+  });
+});
+
+it("404 vira nao_encontrado, para a tela dizer o que aconteceu", async () => {
+  vi.spyOn(globalThis, "fetch").mockResolvedValue(
+    Response.json({ error: "nao_encontrado", message: "some" }, { status: 404 }),
+  );
+  await expect(get(ROTAS.conversa("x"))).rejects.toMatchObject({ tipo: "nao_encontrado" });
+});
+
+it("backend fora do ar vira erro tipado, não uma tela em branco", async () => {
+  vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("failed to fetch"));
+  await expect(get(ROTAS.status())).rejects.toMatchObject({ tipo: "indisponivel" });
+});
+
+it("nenhuma rota é montada por concatenação solta de string", () => {
+  // ROTAS é a superfície inteira que a UI consome. É ela que o teste de deriva lê.
+  expect(Object.keys(ROTAS).sort()).toEqual(
+    [
+      "conversa",
+      "conversas",
+      "eventos",
+      "handoff",
+      "handoffs",
+      "health",
+      "status",
+      "usage",
+      "wsChat",
+    ].sort(),
+  );
+});


=== DIFF: web/package-lock.json ===
@@ -0,0 +1,3195 @@
+{
+  "name": "autoseguro-web",
+  "version": "0.1.0",
+  "lockfileVersion": 3,
+  "requires": true,
+  "packages": {
+    "": {
+      "name": "autoseguro-web",
+      "version": "0.1.0",
+      "dependencies": {
+        "@fontsource-variable/archivo": "^5.3.0",
+        "@fontsource/courier-prime": "^5.3.0",
+        "react": "^18.3.1",
+        "react-dom": "^18.3.1"
+      },
+      "devDependencies": {
+        "@playwright/test": "^1.50.0",
+        "@testing-library/dom": "^10.4.0",
+        "@testing-library/jest-dom": "^6.6.3",
+        "@testing-library/react": "^16.1.0",
+        "@testing-library/user-event": "^14.5.2",
+        "@types/node": "^26.4.1",
+        "@types/react": "^18.3.18",
+        "@types/react-dom": "^18.3.5",
+        "@vitejs/plugin-react": "^4.3.4",
+        "jsdom": "^26.0.0",
+        "typescript": "^5.7.3",
+        "vite": "^6.0.11",
+        "vitest": "^3.0.5",
+        "yaml": "^2.7.0"
+      }
+    },
+    "node_modules/@adobe/css-tools": {
+      "version": "4.5.0",
+      "resolved": "https://registry.npmjs.org/@adobe/css-tools/-/css-tools-4.5.0.tgz",
+      "integrity": "sha512-6OzddxPio9UiWTCemp4N8cYLV2ZN1ncRnV1cVGtve7dhPOtRkleRyx32GQCYSwDYgaHU3USMm84tNsvKzRCa1Q==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@asamuzakjp/css-color": {
+      "version": "3.2.0",
+      "resolved": "https://registry.npmjs.org/@asamuzakjp/css-color/-/css-color-3.2.0.tgz",
+      "integrity": "sha512-K1A6z8tS3XsmCMM86xoWdn7Fkdn9m6RSVtocUrJYIwZnFVkng/PvkEoWtOWmP+Scc6saYWHWZYbndEEXxl24jw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@csstools/css-calc": "^2.1.3",
+        "@csstools/css-color-parser": "^3.0.9",
+        "@csstools/css-parser-algorithms": "^3.0.4",
+        "@csstools/css-tokenizer": "^3.0.3",
+        "lru-cache": "^10.4.3"
+      }
+    },
+    "node_modules/@asamuzakjp/css-color/node_modules/lru-cache": {
+      "version": "10.4.3",
+      "resolved": "https://registry.npmjs.org/lru-cache/-/lru-cache-10.4.3.tgz",
+      "integrity": "sha512-JNAzZcXrCt42VGLuYz0zfAzDfAvJWW6AfYlDBQyDV5DClI2m5sAmK+OIO7s59XfsRsWHp02jAJrRadPRGTt6SQ==",
+      "dev": true,
+      "license": "ISC"
+    },
+    "node_modules/@babel/code-frame": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/code-frame/-/code-frame-7.29.7.tgz",
+      "integrity": "sha512-Aup7aUOfpbAUg2ROOJN6Iw5f9DMBlzu0mIkm/malLQFN/YQgO48wCj0Kxa3sEHJvPVFg7siR+qRInwXd2qhQKw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/helper-validator-identifier": "^7.29.7",
+        "js-tokens": "^4.0.0",
+        "picocolors": "^1.1.1"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/compat-data": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/compat-data/-/compat-data-7.29.7.tgz",
+      "integrity": "sha512-locTkQyKvwIEgBzVrn8693ebc97F2U8ZHjbXwDXJ5Fn2TCpNwTlKcaKLkdHop5c/icOFE7qt7Q9JC5hnKNa6Gg==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/core": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/core/-/core-7.29.7.tgz",
+      "integrity": "sha512-RgHBCvtjbOK2gXSNBNIkNoEc9qoVEtau3hj8gEqKQuL3HZAibKarWFEI3Lfm6EYKkLalOh8eSrj9b+ch9H/VBA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/code-frame": "^7.29.7",
+        "@babel/generator": "^7.29.7",
+        "@babel/helper-compilation-targets": "^7.29.7",
+        "@babel/helper-module-transforms": "^7.29.7",
+        "@babel/helpers": "^7.29.7",
+        "@babel/parser": "^7.29.7",
+        "@babel/template": "^7.29.7",
+        "@babel/traverse": "^7.29.7",
+        "@babel/types": "^7.29.7",
+        "@jridgewell/remapping": "^2.3.5",
+        "convert-source-map": "^2.0.0",
+        "debug": "^4.1.0",
+        "gensync": "^1.0.0-beta.2",
+        "json5": "^2.2.3",
+        "semver": "^6.3.1"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      },
+      "funding": {
+        "type": "opencollective",
+        "url": "https://opencollective.com/babel"
+      }
+    },
+    "node_modules/@babel/generator": {
+      "version": "7.29.8",
+      "resolved": "https://registry.npmjs.org/@babel/generator/-/generator-7.29.8.tgz",
+      "integrity": "sha512-gZbepsdh3WDtgZKWL+vTPh71LSBrm/Y4/QDZBVCcYfmeTEEuoOYwlSy+G1StfJg+/Zy550u/3TATbm7qDbbMtg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/parser": "^7.29.8",
+        "@babel/types": "^7.29.8",
+        "@jridgewell/gen-mapping": "^0.3.12",
+        "@jridgewell/trace-mapping": "^0.3.28",
+        "jsesc": "^3.0.2"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-compilation-targets": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-compilation-targets/-/helper-compilation-targets-7.29.7.tgz",
+      "integrity": "sha512-wem6WaBj4NaVYVdNhLPPVacES6ZJ+KBBfSkTMD3YZxbP3rm3Di85tJU5ljaUNhaOynt+Aj0xruhYuzQBt8n71g==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/compat-data": "^7.29.7",
+        "@babel/helper-validator-option": "^7.29.7",
+        "browserslist": "^4.24.0",
+        "lru-cache": "^5.1.1",
+        "semver": "^6.3.1"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-globals": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-globals/-/helper-globals-7.29.7.tgz",
+      "integrity": "sha512-3nQVUAtvkKH9zahfWgw96Jc/uFOmjACE1kQz82E2lqWmHBgjzbNlsC22nuQTfahmWeQtTq5nQ/4Nnd2A1wj4zA==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-module-imports": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-module-imports/-/helper-module-imports-7.29.7.tgz",
+      "integrity": "sha512-ejHwrQQYcm9xnTivShn2IDOlIzInN34AXskvq9QicvCtEzq1Vzclu/tKF8Jq1Cg8JG2GL6/EmjgsCT7lXepE3g==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/traverse": "^7.29.7",
+        "@babel/types": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-module-transforms": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-module-transforms/-/helper-module-transforms-7.29.7.tgz",
+      "integrity": "sha512-UPUVSyXbOh627KiCIGQSgwWzGeBKLkaJ9PJEdrngIwMSzxLR4jS4+f1f1jb7VzBbg8nFLaYotvVPFCTqdrmTAg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/helper-module-imports": "^7.29.7",
+        "@babel/helper-validator-identifier": "^7.29.7",
+        "@babel/traverse": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      },
+      "peerDependencies": {
+        "@babel/core": "^7.0.0"
+      }
+    },
+    "node_modules/@babel/helper-plugin-utils": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-plugin-utils/-/helper-plugin-utils-7.29.7.tgz",
+      "integrity": "sha512-G7sHYigPY17oO5SYWnfD/0MTBwVR781S/JI643e/JhUYgVgWE/61SoW3NH9KWUKyKq5LVh3npif99Wkt6j86Jw==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-string-parser": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-string-parser/-/helper-string-parser-7.29.7.tgz",
+      "integrity": "sha512-Pb5ijPrZ89GDH8223L4UP8i6QApWxs04RbPQJTeWDV0/keR2E36MeKnyr6LYmUUvqRRI+Iv87SuF1W6ErINzYw==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-validator-identifier": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-validator-identifier/-/helper-validator-identifier-7.29.7.tgz",
+      "integrity": "sha512-qehxGkRj55h/ff8EMaJ+cYhyaKlHIxqYDn682wQD7RNp9UujOQsHog2uS0r2vzr4pW+sXf90NeeayjcNaX3fFg==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helper-validator-option": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helper-validator-option/-/helper-validator-option-7.29.7.tgz",
+      "integrity": "sha512-N9ZErrD+yW5geCDtBqnOoxmR8+tNKiGuxKlDpuJxfsqpa2dFcexaziGAE/qoHLiDDreVNMupxGmSoNlyvsA3gw==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/helpers": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/helpers/-/helpers-7.29.7.tgz",
+      "integrity": "sha512-1k2lAGRMfHTcwuNYcCNUmaUffmQv8KWMfh2iJUUeRlwlwH4FdNG7mfPI10NPfLHJFThE4Tyr4mv7kTNZOiPuBg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/template": "^7.29.7",
+        "@babel/types": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/parser": {
+      "version": "7.29.8",
+      "resolved": "https://registry.npmjs.org/@babel/parser/-/parser-7.29.8.tgz",
+      "integrity": "sha512-E8lTAYNB1KW+FH+VGJuZM1ioAx2E6oVlvQFRrf5P8ZZmsiJXYAD9vTFV7yyEURNzgh1dFqMZuO6tUwcARbqFCA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/types": "^7.29.8"
+      },
+      "bin": {
+        "parser": "bin/babel-parser.js"
+      },
+      "engines": {
+        "node": ">=6.0.0"
+      }
+    },
+    "node_modules/@babel/plugin-transform-react-jsx-self": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/plugin-transform-react-jsx-self/-/plugin-transform-react-jsx-self-7.29.7.tgz",
+      "integrity": "sha512-TL0hMc9xzy86VD31nUiwzd5otRAcyEPcsegCxolO0PvcXuH1v0kECe/UIznYFihpkvU5wg/jk4v0TTEFfm53fw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/helper-plugin-utils": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      },
+      "peerDependencies": {
+        "@babel/core": "^7.0.0-0"
+      }
+    },
+    "node_modules/@babel/plugin-transform-react-jsx-source": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/plugin-transform-react-jsx-source/-/plugin-transform-react-jsx-source-7.29.7.tgz",
+      "integrity": "sha512-06IyK09H3wi4cGbhDBwp5gUGo0IKtnYa8tyTiephirPCK6fbobVGiXMMI5zLQ4aKEYP3wZ3ArU44o+8KMrSG/Q==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/helper-plugin-utils": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      },
+      "peerDependencies": {
+        "@babel/core": "^7.0.0-0"
+      }
+    },
+    "node_modules/@babel/runtime": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/runtime/-/runtime-7.29.7.tgz",
+      "integrity": "sha512-Nq8OhGWiZIZGV6hLHoyAKLLcJihP/xFeBMGJoUrxTX2psI8dCifzLhZISFb+VWS3wFMRDmCGw5R+dOySCqPLhw==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/template": {
+      "version": "7.29.7",
+      "resolved": "https://registry.npmjs.org/@babel/template/-/template-7.29.7.tgz",
+      "integrity": "sha512-puq+Gf35oI24FeN11LkoUQFqv9uwNeWpxXZi/Ji3rRIoKAzKnxRaZ+Gkj0vKS9ZCiTESfng1N9LyOyXvo+m+Gg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/code-frame": "^7.29.7",
+        "@babel/parser": "^7.29.7",
+        "@babel/types": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/traverse": {
+      "version": "7.29.8",
+      "resolved": "https://registry.npmjs.org/@babel/traverse/-/traverse-7.29.8.tgz",
+      "integrity": "sha512-I5z7H3bf/41ktsNVLtpN0wAa336HkqIHQ5BuPLEhTkt1jVSyZpeNKIzTgEWmlxjdg81R0IgUCcaE+Ok3NvrfZg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/code-frame": "^7.29.7",
+        "@babel/generator": "^7.29.8",
+        "@babel/helper-globals": "^7.29.7",
+        "@babel/parser": "^7.29.8",
+        "@babel/template": "^7.29.7",
+        "@babel/types": "^7.29.8",
+        "debug": "^4.3.1"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@babel/types": {
+      "version": "7.29.8",
+      "resolved": "https://registry.npmjs.org/@babel/types/-/types-7.29.8.tgz",
+      "integrity": "sha512-Vj1jF3cPfxg7OAfoI7QnVKLoILlm2JF9pnVHrX8qx7AHMiYWT+NDAA7jChlNgRS4WTLc/fD1lXLmPixluj+3Gg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/helper-string-parser": "^7.29.7",
+        "@babel/helper-validator-identifier": "^7.29.7"
+      },
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/@csstools/color-helpers": {
+      "version": "5.1.0",
+      "resolved": "https://registry.npmjs.org/@csstools/color-helpers/-/color-helpers-5.1.0.tgz",
+      "integrity": "sha512-S11EXWJyy0Mz5SYvRmY8nJYTFFd1LCNV+7cXyAgQtOOuzb4EsgfqDufL+9esx72/eLhsRdGZwaldu/h+E4t4BA==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/csstools"
+        },
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/csstools"
+        }
+      ],
+      "license": "MIT-0",
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@csstools/css-calc": {
+      "version": "2.1.4",
+      "resolved": "https://registry.npmjs.org/@csstools/css-calc/-/css-calc-2.1.4.tgz",
+      "integrity": "sha512-3N8oaj+0juUw/1H3YwmDDJXCgTB1gKU6Hc/bB502u9zR0q2vd786XJH9QfrKIEgFlZmhZiq6epXl4rHqhzsIgQ==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/csstools"
+        },
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/csstools"
+        }
+      ],
+      "license": "MIT",
+      "engines": {
+        "node": ">=18"
+      },
+      "peerDependencies": {
+        "@csstools/css-parser-algorithms": "^3.0.5",
+        "@csstools/css-tokenizer": "^3.0.4"
+      }
+    },
+    "node_modules/@csstools/css-color-parser": {
+      "version": "3.1.0",
+      "resolved": "https://registry.npmjs.org/@csstools/css-color-parser/-/css-color-parser-3.1.0.tgz",
+      "integrity": "sha512-nbtKwh3a6xNVIp/VRuXV64yTKnb1IjTAEEh3irzS+HkKjAOYLTGNb9pmVNntZ8iVBHcWDA2Dof0QtPgFI1BaTA==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/csstools"
+        },
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/csstools"
+        }
+      ],
+      "license": "MIT",
+      "dependencies": {
+        "@csstools/color-helpers": "^5.1.0",
+        "@csstools/css-calc": "^2.1.4"
+      },
+      "engines": {
+        "node": ">=18"
+      },
+      "peerDependencies": {
+        "@csstools/css-parser-algorithms": "^3.0.5",
+        "@csstools/css-tokenizer": "^3.0.4"
+      }
+    },
+    "node_modules/@csstools/css-parser-algorithms": {
+      "version": "3.0.5",
+      "resolved": "https://registry.npmjs.org/@csstools/css-parser-algorithms/-/css-parser-algorithms-3.0.5.tgz",
+      "integrity": "sha512-DaDeUkXZKjdGhgYaHNJTV9pV7Y9B3b644jCLs9Upc3VeNGg6LWARAT6O+Q+/COo+2gg/bM5rhpMAtf70WqfBdQ==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/csstools"
+        },
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/csstools"
+        }
+      ],
+      "license": "MIT",
+      "engines": {
+        "node": ">=18"
+      },
+      "peerDependencies": {
+        "@csstools/css-tokenizer": "^3.0.4"
+      }
+    },
+    "node_modules/@csstools/css-tokenizer": {
+      "version": "3.0.4",
+      "resolved": "https://registry.npmjs.org/@csstools/css-tokenizer/-/css-tokenizer-3.0.4.tgz",
+      "integrity": "sha512-Vd/9EVDiu6PPJt9yAh6roZP6El1xHrdvIVGjyBsHR0RYwNHgL7FJPyIIW4fANJNG6FtyZfvlRPpFI4ZM/lubvw==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/csstools"
+        },
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/csstools"
+        }
+      ],
+      "license": "MIT",
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/aix-ppc64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/aix-ppc64/-/aix-ppc64-0.25.12.tgz",
+      "integrity": "sha512-Hhmwd6CInZ3dwpuGTF8fJG6yoWmsToE+vYgD4nytZVxcu1ulHpUQRAB1UJ8+N1Am3Mz4+xOByoQoSZf4D+CpkA==",
+      "cpu": [
+        "ppc64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "aix"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/android-arm": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/android-arm/-/android-arm-0.25.12.tgz",
+      "integrity": "sha512-VJ+sKvNA/GE7Ccacc9Cha7bpS8nyzVv0jdVgwNDaR4gDMC/2TTRc33Ip8qrNYUcpkOHUT5OZ0bUcNNVZQ9RLlg==",
+      "cpu": [
+        "arm"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "android"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/android-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/android-arm64/-/android-arm64-0.25.12.tgz",
+      "integrity": "sha512-6AAmLG7zwD1Z159jCKPvAxZd4y/VTO0VkprYy+3N2FtJ8+BQWFXU+OxARIwA46c5tdD9SsKGZ/1ocqBS/gAKHg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "android"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/android-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/android-x64/-/android-x64-0.25.12.tgz",
+      "integrity": "sha512-5jbb+2hhDHx5phYR2By8GTWEzn6I9UqR11Kwf22iKbNpYrsmRB18aX/9ivc5cabcUiAT/wM+YIZ6SG9QO6a8kg==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "android"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/darwin-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/darwin-arm64/-/darwin-arm64-0.25.12.tgz",
+      "integrity": "sha512-N3zl+lxHCifgIlcMUP5016ESkeQjLj/959RxxNYIthIg+CQHInujFuXeWbWMgnTo4cp5XVHqFPmpyu9J65C1Yg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "darwin"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/darwin-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/darwin-x64/-/darwin-x64-0.25.12.tgz",
+      "integrity": "sha512-HQ9ka4Kx21qHXwtlTUVbKJOAnmG1ipXhdWTmNXiPzPfWKpXqASVcWdnf2bnL73wgjNrFXAa3yYvBSd9pzfEIpA==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "darwin"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/freebsd-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/freebsd-arm64/-/freebsd-arm64-0.25.12.tgz",
+      "integrity": "sha512-gA0Bx759+7Jve03K1S0vkOu5Lg/85dou3EseOGUes8flVOGxbhDDh/iZaoek11Y8mtyKPGF3vP8XhnkDEAmzeg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "freebsd"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/freebsd-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/freebsd-x64/-/freebsd-x64-0.25.12.tgz",
+      "integrity": "sha512-TGbO26Yw2xsHzxtbVFGEXBFH0FRAP7gtcPE7P5yP7wGy7cXK2oO7RyOhL5NLiqTlBh47XhmIUXuGciXEqYFfBQ==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "freebsd"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-arm": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-arm/-/linux-arm-0.25.12.tgz",
+      "integrity": "sha512-lPDGyC1JPDou8kGcywY0YILzWlhhnRjdof3UlcoqYmS9El818LLfJJc3PXXgZHrHCAKs/Z2SeZtDJr5MrkxtOw==",
+      "cpu": [
+        "arm"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-arm64/-/linux-arm64-0.25.12.tgz",
+      "integrity": "sha512-8bwX7a8FghIgrupcxb4aUmYDLp8pX06rGh5HqDT7bB+8Rdells6mHvrFHHW2JAOPZUbnjUpKTLg6ECyzvas2AQ==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-ia32": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-ia32/-/linux-ia32-0.25.12.tgz",
+      "integrity": "sha512-0y9KrdVnbMM2/vG8KfU0byhUN+EFCny9+8g202gYqSSVMonbsCfLjUO+rCci7pM0WBEtz+oK/PIwHkzxkyharA==",
+      "cpu": [
+        "ia32"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-loong64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-loong64/-/linux-loong64-0.25.12.tgz",
+      "integrity": "sha512-h///Lr5a9rib/v1GGqXVGzjL4TMvVTv+s1DPoxQdz7l/AYv6LDSxdIwzxkrPW438oUXiDtwM10o9PmwS/6Z0Ng==",
+      "cpu": [
+        "loong64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-mips64el": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-mips64el/-/linux-mips64el-0.25.12.tgz",
+      "integrity": "sha512-iyRrM1Pzy9GFMDLsXn1iHUm18nhKnNMWscjmp4+hpafcZjrr2WbT//d20xaGljXDBYHqRcl8HnxbX6uaA/eGVw==",
+      "cpu": [
+        "mips64el"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-ppc64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-ppc64/-/linux-ppc64-0.25.12.tgz",
+      "integrity": "sha512-9meM/lRXxMi5PSUqEXRCtVjEZBGwB7P/D4yT8UG/mwIdze2aV4Vo6U5gD3+RsoHXKkHCfSxZKzmDssVlRj1QQA==",
+      "cpu": [
+        "ppc64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-riscv64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-riscv64/-/linux-riscv64-0.25.12.tgz",
+      "integrity": "sha512-Zr7KR4hgKUpWAwb1f3o5ygT04MzqVrGEGXGLnj15YQDJErYu/BGg+wmFlIDOdJp0PmB0lLvxFIOXZgFRrdjR0w==",
+      "cpu": [
+        "riscv64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-s390x": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-s390x/-/linux-s390x-0.25.12.tgz",
+      "integrity": "sha512-MsKncOcgTNvdtiISc/jZs/Zf8d0cl/t3gYWX8J9ubBnVOwlk65UIEEvgBORTiljloIWnBzLs4qhzPkJcitIzIg==",
+      "cpu": [
+        "s390x"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/linux-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/linux-x64/-/linux-x64-0.25.12.tgz",
+      "integrity": "sha512-uqZMTLr/zR/ed4jIGnwSLkaHmPjOjJvnm6TVVitAa08SLS9Z0VM8wIRx7gWbJB5/J54YuIMInDquWyYvQLZkgw==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/netbsd-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/netbsd-arm64/-/netbsd-arm64-0.25.12.tgz",
+      "integrity": "sha512-xXwcTq4GhRM7J9A8Gv5boanHhRa/Q9KLVmcyXHCTaM4wKfIpWkdXiMog/KsnxzJ0A1+nD+zoecuzqPmCRyBGjg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "netbsd"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/netbsd-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/netbsd-x64/-/netbsd-x64-0.25.12.tgz",
+      "integrity": "sha512-Ld5pTlzPy3YwGec4OuHh1aCVCRvOXdH8DgRjfDy/oumVovmuSzWfnSJg+VtakB9Cm0gxNO9BzWkj6mtO1FMXkQ==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "netbsd"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/openbsd-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/openbsd-arm64/-/openbsd-arm64-0.25.12.tgz",
+      "integrity": "sha512-fF96T6KsBo/pkQI950FARU9apGNTSlZGsv1jZBAlcLL1MLjLNIWPBkj5NlSz8aAzYKg+eNqknrUJ24QBybeR5A==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "openbsd"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/openbsd-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/openbsd-x64/-/openbsd-x64-0.25.12.tgz",
+      "integrity": "sha512-MZyXUkZHjQxUvzK7rN8DJ3SRmrVrke8ZyRusHlP+kuwqTcfWLyqMOE3sScPPyeIXN/mDJIfGXvcMqCgYKekoQw==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "openbsd"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/openharmony-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/openharmony-arm64/-/openharmony-arm64-0.25.12.tgz",
+      "integrity": "sha512-rm0YWsqUSRrjncSXGA7Zv78Nbnw4XL6/dzr20cyrQf7ZmRcsovpcRBdhD43Nuk3y7XIoW2OxMVvwuRvk9XdASg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "openharmony"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/sunos-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/sunos-x64/-/sunos-x64-0.25.12.tgz",
+      "integrity": "sha512-3wGSCDyuTHQUzt0nV7bocDy72r2lI33QL3gkDNGkod22EsYl04sMf0qLb8luNKTOmgF/eDEDP5BFNwoBKH441w==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "sunos"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/win32-arm64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/win32-arm64/-/win32-arm64-0.25.12.tgz",
+      "integrity": "sha512-rMmLrur64A7+DKlnSuwqUdRKyd3UE7oPJZmnljqEptesKM8wx9J8gx5u0+9Pq0fQQW8vqeKebwNXdfOyP+8Bsg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/win32-ia32": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/win32-ia32/-/win32-ia32-0.25.12.tgz",
+      "integrity": "sha512-HkqnmmBoCbCwxUKKNPBixiWDGCpQGVsrQfJoVGYLPT41XWF8lHuE5N6WhVia2n4o5QK5M4tYr21827fNhi4byQ==",
+      "cpu": [
+        "ia32"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@esbuild/win32-x64": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/@esbuild/win32-x64/-/win32-x64-0.25.12.tgz",
+      "integrity": "sha512-alJC0uCZpTFrSL0CCDjcgleBXPnCrEAhTBILpeAp7M/OFgoqtAetfBzX0xM00MUsVVPpVjlPuMbREqnZCXaTnA==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ],
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@fontsource-variable/archivo": {
+      "version": "5.3.0",
+      "resolved": "https://registry.npmjs.org/@fontsource-variable/archivo/-/archivo-5.3.0.tgz",
+      "integrity": "sha512-HogK8FJelrD1o7TlZlkIVtHgc20bO5PZRWE7mUeUTdMN055alznQV6/00J00IBeu8FQAH4s3zW9UJNvKExXf+g==",
+      "license": "OFL-1.1",
+      "funding": {
+        "url": "https://github.com/sponsors/ayuhito"
+      }
+    },
+    "node_modules/@fontsource/courier-prime": {
+      "version": "5.3.0",
+      "resolved": "https://registry.npmjs.org/@fontsource/courier-prime/-/courier-prime-5.3.0.tgz",
+      "integrity": "sha512-KIi1k4VG1Wv+/CGpb1AUpLkUuOAQA6zmvthqxOZGN0AV8BEgQgbK7qAtquv14zsBJAY1bb5BHIEbWVFLgENh0w==",
+      "license": "OFL-1.1",
+      "funding": {
+        "url": "https://github.com/sponsors/ayuhito"
+      }
+    },
+    "node_modules/@jridgewell/gen-mapping": {
+      "version": "0.3.13",
+      "resolved": "https://registry.npmjs.org/@jridgewell/gen-mapping/-/gen-mapping-0.3.13.tgz",
+      "integrity": "sha512-2kkt/7niJ6MgEPxF0bYdQ6etZaA+fQvDcLKckhy1yIQOzaoKjBBjSj63/aLVjYE3qhRt5dvM+uUyfCg6UKCBbA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@jridgewell/sourcemap-codec": "^1.5.0",
+        "@jridgewell/trace-mapping": "^0.3.24"
+      }
+    },
+    "node_modules/@jridgewell/remapping": {
+      "version": "2.3.5",
+      "resolved": "https://registry.npmjs.org/@jridgewell/remapping/-/remapping-2.3.5.tgz",
+      "integrity": "sha512-LI9u/+laYG4Ds1TDKSJW2YPrIlcVYOwi2fUC6xB43lueCjgxV4lffOCZCtYFiH6TNOX+tQKXx97T4IKHbhyHEQ==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@jridgewell/gen-mapping": "^0.3.5",
+        "@jridgewell/trace-mapping": "^0.3.24"
+      }
+    },
+    "node_modules/@jridgewell/resolve-uri": {
+      "version": "3.1.2",
+      "resolved": "https://registry.npmjs.org/@jridgewell/resolve-uri/-/resolve-uri-3.1.2.tgz",
+      "integrity": "sha512-bRISgCIjP20/tbWSPWMEi54QVPRZExkuD9lJL+UIxUKtwVJA8wW1Trb1jMs1RFXo1CBTNZ/5hpC9QvmKWdopKw==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.0.0"
+      }
+    },
+    "node_modules/@jridgewell/sourcemap-codec": {
+      "version": "1.6.0",
+      "resolved": "https://registry.npmjs.org/@jridgewell/sourcemap-codec/-/sourcemap-codec-1.6.0.tgz",
+      "integrity": "sha512-T7jf+5zgsZHwNJ4lvQ7/aezbyk0nNX+zJVWpmHA7VYsEx7a7qr5Rg5IbtJFqkgze5Y2sruq1RUY8Q837Od7iFw==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@jridgewell/trace-mapping": {
+      "version": "0.3.31",
+      "resolved": "https://registry.npmjs.org/@jridgewell/trace-mapping/-/trace-mapping-0.3.31.tgz",
+      "integrity": "sha512-zzNR+SdQSDJzc8joaeP8QQoCQr8NuYx2dIIytl1QeBEZHJ9uW6hebsrYgbz8hJwUQao3TWCMtmfV8Nu1twOLAw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@jridgewell/resolve-uri": "^3.1.0",
+        "@jridgewell/sourcemap-codec": "^1.4.14"
+      }
+    },
+    "node_modules/@napi-rs/lzma-linux-x64-gnu": {
+      "version": "1.5.1",
+      "resolved": "https://registry.npmjs.org/@napi-rs/lzma-linux-x64-gnu/-/lzma-linux-x64-gnu-1.5.1.tgz",
+      "integrity": "sha512-oTXEIha4SsuXdTA4Iyskj0kpdx2yVXdhd75c2v3xGrHFfVMsbhTPZU/nMPL4sWKo4pBHm3aucLaqGlF696dTyQ==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ],
+      "engines": {
+        "node": "^22.20 || ^24.12 || >=25"
+      }
+    },
+    "node_modules/@playwright/test": {
+      "version": "1.62.1",
+      "resolved": "https://registry.npmjs.org/@playwright/test/-/test-1.62.1.tgz",
+      "integrity": "sha512-DTcUc8qii+cpHvtOwggMtBRMjKZHXYWdw8syRYu2vtzuq4Wxphqq4NfCs5Zt44L6mA8rfDfj+PHnxFc/FeK6mQ==",
+      "dev": true,
+      "license": "Apache-2.0",
+      "dependencies": {
+        "playwright": "1.62.1"
+      },
+      "bin": {
+        "playwright": "cli.js"
+      },
+      "engines": {
+        "node": ">=20"
+      }
+    },
+    "node_modules/@rolldown/pluginutils": {
+      "version": "1.0.0-beta.27",
+      "resolved": "https://registry.npmjs.org/@rolldown/pluginutils/-/pluginutils-1.0.0-beta.27.tgz",
+      "integrity": "sha512-+d0F4MKMCbeVUJwG96uQ4SgAznZNSq93I3V+9NHA4OpvqG8mRCpGdKmK8l/dl02h2CCDHwW2FqilnTyDcAnqjA==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@rollup/rollup-android-arm-eabi": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-android-arm-eabi/-/rollup-android-arm-eabi-4.63.1.tgz",
+      "integrity": "sha512-UZ8sUxPTiHWYX9QNdJedb1kDZSpS1t/VPWBWGSgqHNi9w3Cu6IXvu2mzbhiTiPvtrqgTQJ+zqiAq2iPIPilpaQ==",
+      "cpu": [
+        "arm"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "android"
+      ]
+    },
+    "node_modules/@rollup/rollup-android-arm64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-android-arm64/-/rollup-android-arm64-4.63.1.tgz",
+      "integrity": "sha512-cQ4nFQABN5cDvDpbvJ7bMStCpnaVxynZrRMfUJYgxcIk9Sh54FIO1vtfkg0B69REjER77ioZ/ov+eAApx/KmLQ==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "android"
+      ]
+    },
+    "node_modules/@rollup/rollup-darwin-arm64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-darwin-arm64/-/rollup-darwin-arm64-4.63.1.tgz",
+      "integrity": "sha512-FQNqd1lRy/0QhDk3xeRIkSBiCpXCiDnZO3YLVdcDKN1UBiKToNftCzcXYNLshmPDUMlu2TdeS8tGcsU6f3YF1Q==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "darwin"
+      ]
+    },
+    "node_modules/@rollup/rollup-darwin-x64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-darwin-x64/-/rollup-darwin-x64-4.63.1.tgz",
+      "integrity": "sha512-pvD16V939D3CloK0+qikpGaxiPrDUXTe7Y5cWOMkMSy7m1cawa8EGy/kXYi/G/cKAC4HDAbSnzCIk1WmsoOKXg==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "darwin"
+      ]
+    },
+    "node_modules/@rollup/rollup-freebsd-arm64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-freebsd-arm64/-/rollup-freebsd-arm64-4.63.1.tgz",
+      "integrity": "sha512-pcFGeL2345VwdTnJhA6zLbew+YgWB0qBG2+dMtXjCicf6+rm6kO6cOoh5VnTe0ZMrMRgRyuHmCJxZWrIdzYuOw==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "freebsd"
+      ]
+    },
+    "node_modules/@rollup/rollup-freebsd-x64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-freebsd-x64/-/rollup-freebsd-x64-4.63.1.tgz",
+      "integrity": "sha512-mRJlqSRulVzcKq/LKA6ICSIc3K/l4fzlVn/gePn2nXIHy8seRi5z/eeRE0d/XMBxcMldiXtQTSpRj0tkkC3g8Q==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "freebsd"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-arm-gnueabihf": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-arm-gnueabihf/-/rollup-linux-arm-gnueabihf-4.63.1.tgz",
+      "integrity": "sha512-YDUNvVM85TI3g/1OpnqKP1h4NeW/j64DfWMf+G3M809xNk1bJSnpFp4sh83NpmVE5DXnkh8ULor4LTVZKoYLHw==",
+      "cpu": [
+        "arm"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-arm-musleabihf": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-arm-musleabihf/-/rollup-linux-arm-musleabihf-4.63.1.tgz",
+      "integrity": "sha512-7Mcn71p9ZuQFAj+h+dhQXy/yeLePRS2yKRnmW1DijA9thKO5qap0GNOIQK4yQ6iP3SU0Mrb/yWo8h8vgRba8lw==",
+      "cpu": [
+        "arm"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-arm64-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-arm64-gnu/-/rollup-linux-arm64-gnu-4.63.1.tgz",
+      "integrity": "sha512-4YiLQTX6U4CSl0L9cluep9A9W6UmTfqBDc2/CH6wlu54pl4E7Jn3cOD8oxzvBDEGk/JMKgJ47C8g+radF7mwvg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-arm64-musl": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-arm64-musl/-/rollup-linux-arm64-musl-4.63.1.tgz",
+      "integrity": "sha512-2ra8F7w8OquwZN9z2/fKFnli69wa8PLwaVzRMIPGb13ByMJwC28Fbp8YcVGoUhlYMTt7j5j9bNgpysrN2UM+vw==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-loong64-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-loong64-gnu/-/rollup-linux-loong64-gnu-4.63.1.tgz",
+      "integrity": "sha512-Sy20ncyhjmBP0Ml+UvQbimjlk6VFgjW5uNP+qqwHB00mTE8Bl2C1TuHTlRwK2YoXeZbee5lP2XevBWVkAQAtSQ==",
+      "cpu": [
+        "loong64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-loong64-musl": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-loong64-musl/-/rollup-linux-loong64-musl-4.63.1.tgz",
+      "integrity": "sha512-noITLp8oNjYliPnGWmLyelIHwULGqbHloQHGw1rtxbWhTuWooRpnZarZQJ1y9EUC4szuCusCc+HEpUtxpIwYvA==",
+      "cpu": [
+        "loong64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-ppc64-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-ppc64-gnu/-/rollup-linux-ppc64-gnu-4.63.1.tgz",
+      "integrity": "sha512-hlxxXd+F1mWiAcaFR7Sv9ZQT6m6UfI8+Vy/kFJzztq2pDMU/0wZ9sish0iszNZvsQDo8Gc0i5yuFEOz5dDf6fA==",
+      "cpu": [
+        "ppc64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-ppc64-musl": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-ppc64-musl/-/rollup-linux-ppc64-musl-4.63.1.tgz",
+      "integrity": "sha512-EF7OpqQTQ/BvGqLzUi4rEHuagCV9MugAUXSHemwPW5vxZ75RR+jxO/2j95Ph2dalMpFHSVECjRoioHZgA9zOYA==",
+      "cpu": [
+        "ppc64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-riscv64-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-riscv64-gnu/-/rollup-linux-riscv64-gnu-4.63.1.tgz",
+      "integrity": "sha512-wQO3JesW9PRkwlabQ27y7sPfVOOTLRG73I4F2UYHG5PXun3J9U3y+b7ezVKSYbsvSKGQ1k1cq8Qlun4C9kLt3w==",
+      "cpu": [
+        "riscv64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-riscv64-musl": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-riscv64-musl/-/rollup-linux-riscv64-musl-4.63.1.tgz",
+      "integrity": "sha512-ouAGwhO6wHRXdnOVCOsB0tRFkA7nhNB2Nwax6oECXN0YiN8EYUTBAOudADOB1PI+yDL61TeNx/u7MVCzksNbkQ==",
+      "cpu": [
+        "riscv64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-s390x-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-s390x-gnu/-/rollup-linux-s390x-gnu-4.63.1.tgz",
+      "integrity": "sha512-q2R38Sn+1J8RxhfJ+T54wSWmyKXWec+9jgDfqO2AtArEqHO5R2aeayp5H5OYLr5UYDVGsVaZPEFUooMhYCdz5A==",
+      "cpu": [
+        "s390x"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-x64-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-x64-gnu/-/rollup-linux-x64-gnu-4.63.1.tgz",
+      "integrity": "sha512-gfI5T24WLLuFfSKw7Go/zDXjAAV0fny0swTaDv+WjK7vqcw4cRhFfdsyKL1n+ukI+ooBxn3bVQnyrn06WpI50w==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-linux-x64-musl": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-linux-x64-musl/-/rollup-linux-x64-musl-4.63.1.tgz",
+      "integrity": "sha512-4h6XqthmB4Hspji84wvgk+ElodTsGj+dbZqHJHHtKxj4mYq0ANSEEPX9ys3moJueqsRjwpaJYH7874Itwnj2ow==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "linux"
+      ]
+    },
+    "node_modules/@rollup/rollup-openbsd-x64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-openbsd-x64/-/rollup-openbsd-x64-4.63.1.tgz",
+      "integrity": "sha512-dlfCOa87o1VAYegLQ9EKilx2JCeRofiyPGhTCmqnuXZ6bMPiycO1rq1+sKoulAp7pGLIsTIw+1x5R+zgh5LhhA==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "openbsd"
+      ]
+    },
+    "node_modules/@rollup/rollup-openharmony-arm64": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-openharmony-arm64/-/rollup-openharmony-arm64-4.63.1.tgz",
+      "integrity": "sha512-cjkLbOlfcm3QGhMM1J5zaZjsw1GggbN6rw9UTSSRrPrR1KkcXnN7Uq9rPw34xImQ9VOY9GN+6u2Zj80B9ptkcw==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "openharmony"
+      ]
+    },
+    "node_modules/@rollup/rollup-win32-arm64-msvc": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-win32-arm64-msvc/-/rollup-win32-arm64-msvc-4.63.1.tgz",
+      "integrity": "sha512-Li1KdUnWGE4N3e1F/B4RTB1ms+nG4WBgjByO46pkeBVX/2UBsY53xf5vK9WygVmnH3RwncIST7lkSdLSY6P9lg==",
+      "cpu": [
+        "arm64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ]
+    },
+    "node_modules/@rollup/rollup-win32-ia32-msvc": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-win32-ia32-msvc/-/rollup-win32-ia32-msvc-4.63.1.tgz",
+      "integrity": "sha512-t4ZYOSoLTgwhuFMrmTMLx/+i1DQVK7HYqMc6kY46EApwi8X0nIVphzdNoThU3xt6n+N5urG1/gxBdCaKDLavfg==",
+      "cpu": [
+        "ia32"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ]
+    },
+    "node_modules/@rollup/rollup-win32-x64-gnu": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-win32-x64-gnu/-/rollup-win32-x64-gnu-4.63.1.tgz",
+      "integrity": "sha512-RgroPfMmKlD1RzSDxvwgcPiy2HNQKoYV7OmwIXDsk73uKW5t6B/V8KIy27SMv/FNXFo/oSBtWc9J0X7t91ezZg==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ]
+    },
+    "node_modules/@rollup/rollup-win32-x64-msvc": {
+      "version": "4.63.1",
+      "resolved": "https://registry.npmjs.org/@rollup/rollup-win32-x64-msvc/-/rollup-win32-x64-msvc-4.63.1.tgz",
+      "integrity": "sha512-at8QVep6S3h5Y6gSbdGU06bRY5WJkf6WUduM9YtvYMbYhB1MOFfUgc6kehitQXzOtMSaT70q7f9ydPhpqu821w==",
+      "cpu": [
+        "x64"
+      ],
+      "dev": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "win32"
+      ]
+    },
+    "node_modules/@testing-library/dom": {
+      "version": "10.4.1",
+      "resolved": "https://registry.npmjs.org/@testing-library/dom/-/dom-10.4.1.tgz",
+      "integrity": "sha512-o4PXJQidqJl82ckFaXUeoAW+XysPLauYI43Abki5hABd853iMhitooc6znOnczgbTYmEP6U6/y1ZyKAIsvMKGg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/code-frame": "^7.10.4",
+        "@babel/runtime": "^7.12.5",
+        "@types/aria-query": "^5.0.1",
+        "aria-query": "5.3.0",
+        "dom-accessibility-api": "^0.5.9",
+        "lz-string": "^1.5.0",
+        "picocolors": "1.1.1",
+        "pretty-format": "^27.0.2"
+      },
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/@testing-library/jest-dom": {
+      "version": "6.9.1",
+      "resolved": "https://registry.npmjs.org/@testing-library/jest-dom/-/jest-dom-6.9.1.tgz",
+      "integrity": "sha512-zIcONa+hVtVSSep9UT3jZ5rizo2BsxgyDYU7WFD5eICBE7no3881HGeb/QkGfsJs6JTkY1aQhT7rIPC7e+0nnA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@adobe/css-tools": "^4.4.0",
+        "aria-query": "^5.0.0",
+        "css.escape": "^1.5.1",
+        "dom-accessibility-api": "^0.6.3",
+        "picocolors": "^1.1.1",
+        "redent": "^3.0.0"
+      },
+      "engines": {
+        "node": ">=14",
+        "npm": ">=6",
+        "yarn": ">=1"
+      }
+    },
+    "node_modules/@testing-library/jest-dom/node_modules/dom-accessibility-api": {
+      "version": "0.6.3",
+      "resolved": "https://registry.npmjs.org/dom-accessibility-api/-/dom-accessibility-api-0.6.3.tgz",
+      "integrity": "sha512-7ZgogeTnjuHbo+ct10G9Ffp0mif17idi0IyWNVA/wcwcm7NPOD/WEHVP3n7n3MhXqxoIYm8d6MuZohYWIZ4T3w==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@testing-library/react": {
+      "version": "16.3.3",
+      "resolved": "https://registry.npmjs.org/@testing-library/react/-/react-16.3.3.tgz",
+      "integrity": "sha512-Uo193NgQbPMz6lrrhtRQQFcMC6Re/ELLFbbuVL30WDlZxlpZf9/lMHTAVxPRLw1q1iu9OJmR1c2BLiENRstdBg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/runtime": "^7.12.5"
+      },
+      "engines": {
+        "node": ">=18"
+      },
+      "peerDependencies": {
+        "@testing-library/dom": "^10.0.0",
+        "@types/react": "^18.0.0 || ^19.0.0",
+        "@types/react-dom": "^18.0.0 || ^19.0.0",
+        "react": "^18.0.0 || ^19.0.0",
+        "react-dom": "^18.0.0 || ^19.0.0"
+      },
+      "peerDependenciesMeta": {
+        "@types/react": {
+          "optional": true
+        },
+        "@types/react-dom": {
+          "optional": true
+        }
+      }
+    },
+    "node_modules/@testing-library/user-event": {
+      "version": "14.6.7",
+      "resolved": "https://registry.npmjs.org/@testing-library/user-event/-/user-event-14.6.7.tgz",
+      "integrity": "sha512-MPCpX8bxe8zS+JmmTwLp8jd0dy1rAm60Te/SL8JrQM3qvQJcBOs1d7IefJMyZzqM3EWBrDn/LWDt1BCGu4ASfg==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=12",
+        "npm": ">=6"
+      },
+      "peerDependencies": {
+        "@testing-library/dom": ">=7.21.4"
+      }
+    },
+    "node_modules/@types/aria-query": {
+      "version": "5.0.4",
+      "resolved": "https://registry.npmjs.org/@types/aria-query/-/aria-query-5.0.4.tgz",
+      "integrity": "sha512-rfT93uj5s0PRL7EzccGMs3brplhcrghnDoV26NqKhCAS1hVo+WdNsPvE/yb6ilfr5hi2MEk6d5EWJTKdxg8jVw==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@types/babel__core": {
+      "version": "7.20.5",
+      "resolved": "https://registry.npmjs.org/@types/babel__core/-/babel__core-7.20.5.tgz",
+      "integrity": "sha512-qoQprZvz5wQFJwMDqeseRXWv3rqMvhgpbXFfVyWhbx9X47POIA6i/+dXefEmZKoAgOaTdaIgNSMqMIU61yRyzA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/parser": "^7.20.7",
+        "@babel/types": "^7.20.7",
+        "@types/babel__generator": "*",
+        "@types/babel__template": "*",
+        "@types/babel__traverse": "*"
+      }
+    },
+    "node_modules/@types/babel__generator": {
+      "version": "7.27.0",
+      "resolved": "https://registry.npmjs.org/@types/babel__generator/-/babel__generator-7.27.0.tgz",
+      "integrity": "sha512-ufFd2Xi92OAVPYsy+P4n7/U7e68fex0+Ee8gSG9KX7eo084CWiQ4sdxktvdl0bOPupXtVJPY19zk6EwWqUQ8lg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/types": "^7.0.0"
+      }
+    },
+    "node_modules/@types/babel__template": {
+      "version": "7.4.4",
+      "resolved": "https://registry.npmjs.org/@types/babel__template/-/babel__template-7.4.4.tgz",
+      "integrity": "sha512-h/NUaSyG5EyxBIp8YRxo4RMe2/qQgvyowRwVMzhYhBCONbW8PUsg4lkFMrhgZhUe5z3L3MiLDuvyJ/CaPa2A8A==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/parser": "^7.1.0",
+        "@babel/types": "^7.0.0"
+      }
+    },
+    "node_modules/@types/babel__traverse": {
+      "version": "7.28.0",
+      "resolved": "https://registry.npmjs.org/@types/babel__traverse/-/babel__traverse-7.28.0.tgz",
+      "integrity": "sha512-8PvcXf70gTDZBgt9ptxJ8elBeBjcLOAcOtoO/mPJjtji1+CdGbHgm77om1GrsPxsiE+uXIpNSK64UYaIwQXd4Q==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/types": "^7.28.2"
+      }
+    },
+    "node_modules/@types/chai": {
+      "version": "5.2.3",
+      "resolved": "https://registry.npmjs.org/@types/chai/-/chai-5.2.3.tgz",
+      "integrity": "sha512-Mw558oeA9fFbv65/y4mHtXDs9bPnFMZAL/jxdPFUpOHHIXX91mcgEHbS5Lahr+pwZFR8A7GQleRWeI6cGFC2UA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@types/deep-eql": "*",
+        "assertion-error": "^2.0.1"
+      }
+    },
+    "node_modules/@types/deep-eql": {
+      "version": "4.0.2",
+      "resolved": "https://registry.npmjs.org/@types/deep-eql/-/deep-eql-4.0.2.tgz",
+      "integrity": "sha512-c9h9dVVMigMPc4bwTvC5dxqtqJZwQPePsWjPlpSOnojbor6pGqdk541lfA7AqFQr5pB1BRdq0juY9db81BwyFw==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@types/estree": {
+      "version": "1.0.9",
+      "resolved": "https://registry.npmjs.org/@types/estree/-/estree-1.0.9.tgz",
+      "integrity": "sha512-GhdPgy1el4/ImP05X05Uw4cw2/M93BCUmnEvWZNStlCzEKME4Fkk+YpoA5OiHNQmoS7Cafb8Xa3Pya8m1Qrzeg==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@types/node": {
+      "version": "26.4.1",
+      "resolved": "https://registry.npmjs.org/@types/node/-/node-26.4.1.tgz",
+      "integrity": "sha512-k97ENvZWtvA6yqz5/FS6a7duDgOPEeOQOc2iKS/nY6mX6qJUKtLnWzQS+Xj6tXweyj6ZcTAK2Qecetnvi9nCLA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "undici-types": "~8.3.0"
+      }
+    },
+    "node_modules/@types/prop-types": {
+      "version": "15.7.15",
+      "resolved": "https://registry.npmjs.org/@types/prop-types/-/prop-types-15.7.15.tgz",
+      "integrity": "sha512-F6bEyamV9jKGAFBEmlQnesRPGOQqS2+Uwi0Em15xenOxHaf2hv6L8YCVn3rPdPJOiJfPiCnLIRyvwVaqMY3MIw==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/@types/react": {
+      "version": "18.3.31",
+      "resolved": "https://registry.npmjs.org/@types/react/-/react-18.3.31.tgz",
+      "integrity": "sha512-vfEqpXTvwT91yhmwdfouStN2hSKwTvyRs8qpLfADyrq/kxDw0hZM7Wk9Ug1FELj8hIby+S/+kQCSRFF32nv2Qw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@types/prop-types": "*",
+        "csstype": "^3.2.2"
+      }
+    },
+    "node_modules/@types/react-dom": {
+      "version": "18.3.7",
+      "resolved": "https://registry.npmjs.org/@types/react-dom/-/react-dom-18.3.7.tgz",
+      "integrity": "sha512-MEe3UeoENYVFXzoXEWsvcpg6ZvlrFNlOQ7EOsvhI3CfAXwzPfO8Qwuxd40nepsYKqyyVQnTdEfv68q91yLcKrQ==",
+      "dev": true,
+      "license": "MIT",
+      "peerDependencies": {
+        "@types/react": "^18.0.0"
+      }
+    },
+    "node_modules/@vitejs/plugin-react": {
+      "version": "4.7.0",
+      "resolved": "https://registry.npmjs.org/@vitejs/plugin-react/-/plugin-react-4.7.0.tgz",
+      "integrity": "sha512-gUu9hwfWvvEDBBmgtAowQCojwZmJ5mcLn3aufeCsitijs3+f2NsrPtlAWIR6OPiqljl96GVCUbLe0HyqIpVaoA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@babel/core": "^7.28.0",
+        "@babel/plugin-transform-react-jsx-self": "^7.27.1",
+        "@babel/plugin-transform-react-jsx-source": "^7.27.1",
+        "@rolldown/pluginutils": "1.0.0-beta.27",
+        "@types/babel__core": "^7.20.5",
+        "react-refresh": "^0.17.0"
+      },
+      "engines": {
+        "node": "^14.18.0 || >=16.0.0"
+      },
+      "peerDependencies": {
+        "vite": "^4.2.0 || ^5.0.0 || ^6.0.0 || ^7.0.0"
+      }
+    },
+    "node_modules/@vitest/expect": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/expect/-/expect-3.2.7.tgz",
+      "integrity": "sha512-E8eBXaKibuvH2pSZErOjdVb5vF4PbKYcrnluBTYxEk1l/VhhwZg1kZQsdtjq+CsF5CFydf2Rdkz7jDHKSisi3w==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@types/chai": "^5.2.2",
+        "@vitest/spy": "3.2.7",
+        "@vitest/utils": "3.2.7",
+        "chai": "^5.2.0",
+        "tinyrainbow": "^2.0.0"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      }
+    },
+    "node_modules/@vitest/mocker": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/mocker/-/mocker-3.2.7.tgz",
+      "integrity": "sha512-Trr0hYO9CM3Wj6ksWHRhK9IZpIY6wTMO5u/MqXurMxT57sWBaOPEtP3Oq60ihZuh5JsiagKfz95OcxdEP6dBrA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@vitest/spy": "3.2.7",
+        "estree-walker": "^3.0.3",
+        "magic-string": "^0.30.17"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      },
+      "peerDependencies": {
+        "msw": "^2.4.9",
+        "vite": "^5.0.0 || ^6.0.0 || ^7.0.0-0"
+      },
+      "peerDependenciesMeta": {
+        "msw": {
+          "optional": true
+        },
+        "vite": {
+          "optional": true
+        }
+      }
+    },
+    "node_modules/@vitest/pretty-format": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/pretty-format/-/pretty-format-3.2.7.tgz",
+      "integrity": "sha512-KUHlwqVu0sRlhCdyPdQ/wBoTfRahjUky1MubOmYw9fWfIZy1gNoHpuaaQBPAaMaVYdQYHJLurzj8ECCj5OwTqA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "tinyrainbow": "^2.0.0"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      }
+    },
+    "node_modules/@vitest/runner": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/runner/-/runner-3.2.7.tgz",
+      "integrity": "sha512-sB9y4ovltoQP+WaUPwmSxO9WIg9Ig694Di5PalVPsYHklAdE027mehpWF2SQSVq+k6sFgaivbTjTJwZLSHbedA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@vitest/utils": "3.2.7",
+        "pathe": "^2.0.3",
+        "strip-literal": "^3.0.0"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      }
+    },
+    "node_modules/@vitest/snapshot": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/snapshot/-/snapshot-3.2.7.tgz",
+      "integrity": "sha512-7C+MwShwtBSI5Buwoyg3s/iY1eHL9PKAf+O1wVh/TdnjXUtkoL/9YQtre90i4MtNXM6edP1wJ2zOBpfCyhIS7g==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@vitest/pretty-format": "3.2.7",
+        "magic-string": "^0.30.17",
+        "pathe": "^2.0.3"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      }
+    },
+    "node_modules/@vitest/spy": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/spy/-/spy-3.2.7.tgz",
+      "integrity": "sha512-Q2eQGI6d2L/hBtZ0qNuKcAGid68XK6cv1xsoaIma6PaJhHPoqcEJhYpXZ/5myCMqkNgtP6UKuBhbc0nHKnrkuQ==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "tinyspy": "^4.0.3"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      }
+    },
+    "node_modules/@vitest/utils": {
+      "version": "3.2.7",
+      "resolved": "https://registry.npmjs.org/@vitest/utils/-/utils-3.2.7.tgz",
+      "integrity": "sha512-x6BDOd7dyo3PFLY3I9/HJ25X/6OurhGXk2/B9gOZNPF7XDVjeBK4k01lQE5uvDpbuheErh91qYuE1E2OEjK3Rw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@vitest/pretty-format": "3.2.7",
+        "loupe": "^3.1.4",
+        "tinyrainbow": "^2.0.0"
+      },
+      "funding": {
+        "url": "https://opencollective.com/vitest"
+      }
+    },
+    "node_modules/agent-base": {
+      "version": "7.1.4",
+      "resolved": "https://registry.npmjs.org/agent-base/-/agent-base-7.1.4.tgz",
+      "integrity": "sha512-MnA+YT8fwfJPgBx3m60MNqakm30XOkyIoH1y6huTQvC0PwZG7ki8NacLBcrPbNoo8vEZy7Jpuk7+jMO+CUovTQ==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">= 14"
+      }
+    },
+    "node_modules/ansi-regex": {
+      "version": "5.0.1",
+      "resolved": "https://registry.npmjs.org/ansi-regex/-/ansi-regex-5.0.1.tgz",
+      "integrity": "sha512-quJQXlTSUGL2LH9SUXo8VwsY4soanhgo6LNSm84E1LBcE8s3O0wpdiRzyR9z/ZZJMlMWv37qOOb9pdJlMUEKFQ==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=8"
+      }
+    },
+    "node_modules/ansi-styles": {
+      "version": "5.2.0",
+      "resolved": "https://registry.npmjs.org/ansi-styles/-/ansi-styles-5.2.0.tgz",
+      "integrity": "sha512-Cxwpt2SfTzTtXcfOlzGEee8O+c+MmUgGrNiBcXnuWxuFJHe6a5Hz7qwhwe5OgaSYI0IJvkLqWX1ASG+cJOkEiA==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=10"
+      },
+      "funding": {
+        "url": "https://github.com/chalk/ansi-styles?sponsor=1"
+      }
+    },
+    "node_modules/aria-query": {
+      "version": "5.3.0",
+      "resolved": "https://registry.npmjs.org/aria-query/-/aria-query-5.3.0.tgz",
+      "integrity": "sha512-b0P0sZPKtyu8HkeRAfCq0IfURZK+SuwMjY1UXGBU27wpAiTwQAIlq56IbIO+ytk/JjS1fMR14ee5WBBfKi5J6A==",
+      "dev": true,
+      "license": "Apache-2.0",
+      "dependencies": {
+        "dequal": "^2.0.3"
+      }
+    },
+    "node_modules/assertion-error": {
+      "version": "2.0.1",
+      "resolved": "https://registry.npmjs.org/assertion-error/-/assertion-error-2.0.1.tgz",
+      "integrity": "sha512-Izi8RQcffqCeNVgFigKli1ssklIbpHnCYc6AknXGYoB6grJqyeby7jv12JUQgmTAnIDnbck1uxksT4dzN3PWBA==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=12"
+      }
+    },
+    "node_modules/baseline-browser-mapping": {
+      "version": "2.11.21",
+      "resolved": "https://registry.npmjs.org/baseline-browser-mapping/-/baseline-browser-mapping-2.11.21.tgz",
+      "integrity": "sha512-uh8vpY/1/YyFkunIDFH/12p7/7VdPKA1hejMVEbdkEaWnUz0Hesvx5EbiU6XxjyHZIOju+ZMbQJkRh+es3/spQ==",
+      "dev": true,
+      "license": "Apache-2.0",
+      "bin": {
+        "baseline-browser-mapping": "dist/cli.cjs"
+      },
+      "engines": {
+        "node": ">=6.0.0"
+      }
+    },
+    "node_modules/browserslist": {
+      "version": "4.28.9",
+      "resolved": "https://registry.npmjs.org/browserslist/-/browserslist-4.28.9.tgz",
+      "integrity": "sha512-EWazOblFYUvlGZcfGhPUPmYh3nikUxBVb+y9MJun5f3hBi812X+8MSQTujLBtgK3cf51fJWbWfOjyeO954d+Eg==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/browserslist"
+        },
+        {
+          "type": "tidelift",
+          "url": "https://tidelift.com/funding/github/npm/browserslist"
+        },
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/ai"
+        }
+      ],
+      "license": "MIT",
+      "dependencies": {
+        "baseline-browser-mapping": "^2.11.20",
+        "caniuse-lite": "^1.0.[CEP]",
+        "electron-to-chromium": "^1.5.420",
+        "node-releases": "^2.0.54",
+        "update-browserslist-db": "^1.3.2"
+      },
+      "bin": {
+        "browserslist": "cli.js"
+      },
+      "engines": {
+        "node": "^6 || ^7 || ^8 || ^9 || ^10 || ^11 || ^12 || >=13.7"
+      }
+    },
+    "node_modules/cac": {
+      "version": "6.7.14",
+      "resolved": "https://registry.npmjs.org/cac/-/cac-6.7.14.tgz",
+      "integrity": "sha512-b6Ilus+c3RrdDk+JhLKUAQfzzgLEPy6wcXqS7f/xe1EETvsDP6GORG7SFuOs6cID5YkqchW/LXZbX5bc8j7ZcQ==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=8"
+      }
+    },
+    "node_modules/caniuse-lite": {
+      "version": "1.0.[CEP]",
+      "resolved": "https://registry.npmjs.org/caniuse-lite/-/caniuse-lite-1.0.[CEP].tgz",
+      "integrity": "sha512-TITQPUkaz+aVk5GL6NhOdwk1aEaNTSDPsGFWrTuhKGtjTF70jL/Oht2W4c6rXUe5fu7Ie19VIahAXHIIiWWNeg==",
+      "dev": true,
+      "funding": [
+        {
+          "type": "opencollective",
+          "url": "https://opencollective.com/browserslist"
+        },
+        {
+          "type": "tidelift",
+          "url": "https://tidelift.com/funding/github/npm/caniuse-lite"
+        },
+        {
+          "type": "github",
+          "url": "https://github.com/sponsors/ai"
+        }
+      ],
+      "license": "CC-BY-4.0"
+    },
+    "node_modules/chai": {
+      "version": "5.3.3",
+      "resolved": "https://registry.npmjs.org/chai/-/chai-5.3.3.tgz",
+      "integrity": "sha512-4zNhdJD/iOjSH0A05ea+Ke6MU5mmpQcbQsSOkgdaUMJ9zTlDTD/GYlwohmIE2u0gaxHYiVHEn1Fw9mZ/ktJWgw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "assertion-error": "^2.0.1",
+        "check-error": "^2.1.1",
+        "deep-eql": "^5.0.1",
+        "loupe": "^3.1.0",
+        "pathval": "^2.0.0"
+      },
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/check-error": {
+      "version": "2.1.3",
+      "resolved": "https://registry.npmjs.org/check-error/-/check-error-2.1.3.tgz",
+      "integrity": "sha512-PAJdDJusoxnwm1VwW07VWwUN1sl7smmC3OKggvndJFadxxDRyFJBX/ggnu/KE4kQAB7a3Dp8f/YXC1FlUprWmA==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">= 16"
+      }
+    },
+    "node_modules/convert-source-map": {
+      "version": "2.0.0",
+      "resolved": "https://registry.npmjs.org/convert-source-map/-/convert-source-map-2.0.0.tgz",
+      "integrity": "sha512-Kvp459HrV2FEJ1CAsi1Ku+MY3kasH19TFykTz2xWmMeq6bk2NU3XXvfJ+Q61m0xktWwt+1HSYf3JZsTms3aRJg==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/css.escape": {
+      "version": "1.5.1",
+      "resolved": "https://registry.npmjs.org/css.escape/-/css.escape-1.5.1.tgz",
+      "integrity": "sha512-YUifsXXuknHlUsmlgyY0PKzgPOr7/FjCePfHNt0jxm83wHZi44VDMQ7/fGNkjY3/jV1MC+1CmZbaHzugyeRtpg==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/cssstyle": {
+      "version": "4.6.0",
+      "resolved": "https://registry.npmjs.org/cssstyle/-/cssstyle-4.6.0.tgz",
+      "integrity": "sha512-2z+rWdzbbSZv6/rhtvzvqeZQHrBaqgogqt85sqFNbabZOuFbCVFb8kPeEtZjiKkbrm395irpNKiYeFeLiQnFPg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@asamuzakjp/css-color": "^3.2.0",
+        "rrweb-cssom": "^0.8.0"
+      },
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/csstype": {
+      "version": "3.2.3",
+      "resolved": "https://registry.npmjs.org/csstype/-/csstype-3.2.3.tgz",
+      "integrity": "sha512-z1HGKcYy2xA8AGQfwrn0PAy+PB7X/GSj3UVJW9qKyn43xWa+gl5nXmU4qqLMRzWVLFC8KusUX8T/0kCiOYpAIQ==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/data-urls": {
+      "version": "5.0.0",
+      "resolved": "https://registry.npmjs.org/data-urls/-/data-urls-5.0.0.tgz",
+      "integrity": "sha512-ZYP5VBHshaDAiVZxjbRVcFJpc+4xGgT0bK3vzy1HLN8jTO975HEbuYzZJcHoQEY5K1a0z8YayJkyVETa08eNTg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "whatwg-mimetype": "^4.0.0",
+        "whatwg-url": "^14.0.0"
+      },
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/debug": {
+      "version": "4.4.3",
+      "resolved": "https://registry.npmjs.org/debug/-/debug-4.4.3.tgz",
+      "integrity": "sha512-RGwwWnwQvkVfavKVt22FGLw+xYSdzARwm0ru6DhTVA3umU5hZc28V3kO4stgYryrTlLpuvgI9GiijltAjNbcqA==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "ms": "^2.1.3"
+      },
+      "engines": {
+        "node": ">=6.0"
+      },
+      "peerDependenciesMeta": {
+        "supports-color": {
+          "optional": true
+        }
+      }
+    },
+    "node_modules/decimal.js": {
+      "version": "10.6.0",
+      "resolved": "https://registry.npmjs.org/decimal.js/-/decimal.js-10.6.0.tgz",
+      "integrity": "sha512-YpgQiITW3JXGntzdUmyUR1V812Hn8T1YVXhCu+wO3OpS4eU9l4YdD3qjyiKdV6mvV29zapkMeD390UVEf2lkUg==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/deep-eql": {
+      "version": "5.0.2",
+      "resolved": "https://registry.npmjs.org/deep-eql/-/deep-eql-5.0.2.tgz",
+      "integrity": "sha512-h5k/5U50IJJFpzfL6nO9jaaumfjO/f2NjK/oYB2Djzm4p9L+3T9qWpZqZ2hAbLPuuYq9wrU08WQyBTL5GbPk5Q==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6"
+      }
+    },
+    "node_modules/dequal": {
+      "version": "2.0.3",
+      "resolved": "https://registry.npmjs.org/dequal/-/dequal-2.0.3.tgz",
+      "integrity": "sha512-0je+qPKHEMohvfRTCEo3CrPG6cAzAYgmzKyxRiYSSDkS6eGJdyVJm7WaYA5ECaAD9wLB2T4EEeymA5aFVcYXCA==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6"
+      }
+    },
+    "node_modules/dom-accessibility-api": {
+      "version": "0.5.16",
+      "resolved": "https://registry.npmjs.org/dom-accessibility-api/-/dom-accessibility-api-0.5.16.tgz",
+      "integrity": "sha512-X7BJ2yElsnOJ30pZF4uIIDfBEVgF4XEBxL9Bxhy6dnrm5hkzqmsWHGTiHqRiITNhMyFLyAiWndIJP7Z1NTteDg==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/electron-to-chromium": {
+      "version": "1.5.422",
+      "resolved": "https://registry.npmjs.org/electron-to-chromium/-/electron-to-chromium-1.5.422.tgz",
+      "integrity": "sha512-UvA/32XqrLDdZSn7Jllo1AYNcWji/G0d5M0GTViE7KoGBiMunw3a34Sb2KO4ZZyrSEhqsxFoVhWWJshdyfKqJA==",
+      "dev": true,
+      "license": "ISC"
+    },
+    "node_modules/entities": {
+      "version": "6.0.1",
+      "resolved": "https://registry.npmjs.org/entities/-/entities-6.0.1.tgz",
+      "integrity": "sha512-aN97NXWF6AWBTahfVOIrB/NShkzi5H7F9r1s9mD3cDj4Ko5f2qhhVoYMibXF7GlLveb/D2ioWay8lxI97Ven3g==",
+      "dev": true,
+      "license": "BSD-2-Clause",
+      "engines": {
+        "node": ">=0.12"
+      },
+      "funding": {
+        "url": "https://github.com/fb55/entities?sponsor=1"
+      }
+    },
+    "node_modules/es-module-lexer": {
+      "version": "1.7.0",
+      "resolved": "https://registry.npmjs.org/es-module-lexer/-/es-module-lexer-1.7.0.tgz",
+      "integrity": "sha512-jEQoCwk8hyb2AZziIOLhDqpm5+2ww5uIE6lkO/6jcOCusfk6LhMHpXXfBLXTZ7Ydyt0j4VoUQv6uGNYbdW+kBA==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/esbuild": {
+      "version": "0.25.12",
+      "resolved": "https://registry.npmjs.org/esbuild/-/esbuild-0.25.12.tgz",
+      "integrity": "sha512-bbPBYYrtZbkt6Os6FiTLCTFxvq4tt3JKall1vRwshA3fdVztsLAatFaZobhkBC8/BrPetoa0oksYoKXoG4ryJg==",
+      "dev": true,
+      "hasInstallScript": true,
+      "license": "MIT",
+      "bin": {
+        "esbuild": "bin/esbuild"
+      },
+      "engines": {
+        "node": ">=18"
+      },
+      "optionalDependencies": {
+        "@esbuild/aix-ppc64": "0.25.12",
+        "@esbuild/android-arm": "0.25.12",
+        "@esbuild/android-arm64": "0.25.12",
+        "@esbuild/android-x64": "0.25.12",
+        "@esbuild/darwin-arm64": "0.25.12",
+        "@esbuild/darwin-x64": "0.25.12",
+        "@esbuild/freebsd-arm64": "0.25.12",
+        "@esbuild/freebsd-x64": "0.25.12",
+        "@esbuild/linux-arm": "0.25.12",
+        "@esbuild/linux-arm64": "0.25.12",
+        "@esbuild/linux-ia32": "0.25.12",
+        "@esbuild/linux-loong64": "0.25.12",
+        "@esbuild/linux-mips64el": "0.25.12",
+        "@esbuild/linux-ppc64": "0.25.12",
+        "@esbuild/linux-riscv64": "0.25.12",
+        "@esbuild/linux-s390x": "0.25.12",
+        "@esbuild/linux-x64": "0.25.12",
+        "@esbuild/netbsd-arm64": "0.25.12",
+        "@esbuild/netbsd-x64": "0.25.12",
+        "@esbuild/openbsd-arm64": "0.25.12",
+        "@esbuild/openbsd-x64": "0.25.12",
+        "@esbuild/openharmony-arm64": "0.25.12",
+        "@esbuild/sunos-x64": "0.25.12",
+        "@esbuild/win32-arm64": "0.25.12",
+        "@esbuild/win32-ia32": "0.25.12",
+        "@esbuild/win32-x64": "0.25.12"
+      }
+    },
+    "node_modules/escalade": {
+      "version": "3.2.0",
+      "resolved": "https://registry.npmjs.org/escalade/-/escalade-3.2.0.tgz",
+      "integrity": "sha512-WUj2qlxaQtO4g6Pq5c29GTcWGDyd8itL8zTlipgECz3JesAiiOKotd8JU6otB3PACgG6xkJUyVhboMS+bje/jA==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6"
+      }
+    },
+    "node_modules/estree-walker": {
+      "version": "3.0.3",
+      "resolved": "https://registry.npmjs.org/estree-walker/-/estree-walker-3.0.3.tgz",
+      "integrity": "sha512-7RUKfXgSMMkzt6ZuXmqapOurLGPPfgj6l9uRZ7lRGolvk0y2yocc35LdcxKC5PQZdn2DMqioAQ2NoWcrTKmm6g==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "@types/estree": "^1.0.0"
+      }
+    },
+    "node_modules/expect-type": {
+      "version": "1.4.0",
+      "resolved": "https://registry.npmjs.org/expect-type/-/expect-type-1.4.0.tgz",
+      "integrity": "sha512-KfYbmpRm0VbLjEvVa9yGwCi9GI34xvi7A/HXYWQO65CSD2u3MczUJSuwXKFIxlGsgBQizV9q5J9NHj4VG0n+pA==",
+      "dev": true,
+      "license": "Apache-2.0",
+      "engines": {
+        "node": ">=12.0.0"
+      }
+    },
+    "node_modules/fdir": {
+      "version": "6.5.0",
+      "resolved": "https://registry.npmjs.org/fdir/-/fdir-6.5.0.tgz",
+      "integrity": "sha512-tIbYtZbucOs0BRGqPJkshJUYdL+SDH7dVM8gjy+ERp3WAUjLEFJE+02kanyHtwjWOnwrKYBiwAmM0p4kLJAnXg==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=12.0.0"
+      },
+      "peerDependencies": {
+        "picomatch": "^3 || ^4"
+      },
+      "peerDependenciesMeta": {
+        "picomatch": {
+          "optional": true
+        }
+      }
+    },
+    "node_modules/fsevents": {
+      "version": "2.3.2",
+      "resolved": "https://registry.npmjs.org/fsevents/-/fsevents-2.3.2.tgz",
+      "integrity": "sha512-xiqMQR4xAeHTuB9uWm+fFRcIOgKBMiOBP+eXiyT7jsgVCq1bkVygt00oASowB7EdtpOHaaPgKt812P9ab+DDKA==",
+      "dev": true,
+      "hasInstallScript": true,
+      "license": "MIT",
+      "optional": true,
+      "os": [
+        "darwin"
+      ],
+      "engines": {
+        "node": "^8.16.0 || ^10.6.0 || >=11.0.0"
+      }
+    },
+    "node_modules/gensync": {
+      "version": "1.0.0-beta.2",
+      "resolved": "https://registry.npmjs.org/gensync/-/gensync-1.0.0-beta.2.tgz",
+      "integrity": "sha512-3hN7NaskYvMDLQY55gnW3NQ+mesEAepTqlg+VEbj7zzqEMBVNhzcGYYeqFo/TlYz6eQiFcp1HcsCZO+nGgS8zg==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=6.9.0"
+      }
+    },
+    "node_modules/html-encoding-sniffer": {
+      "version": "4.0.0",
+      "resolved": "https://registry.npmjs.org/html-encoding-sniffer/-/html-encoding-sniffer-4.0.0.tgz",
+      "integrity": "sha512-Y22oTqIU4uuPgEemfz7NDJz6OeKf12Lsu+QC+s3BVpda64lTiMYCyGwg5ki4vFxkMwQdeZDl2adZoqUgdFuTgQ==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "whatwg-encoding": "^3.1.1"
+      },
+      "engines": {
+        "node": ">=18"
+      }
+    },
+    "node_modules/http-proxy-agent": {
+      "version": "7.0.2",
+      "resolved": "https://registry.npmjs.org/http-proxy-agent/-/http-proxy-agent-7.0.2.tgz",
+      "integrity": "sha512-T1gkAiYYDWYx3V5Bmyu7HcfcvL7mUrTWiM6yOfa3PIphViJ/gFPbvidQ+veqSOHci/PxBcDabeUNCzpOODJZig==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "agent-base": "^7.1.0",
+        "debug": "^4.3.4"
+      },
+      "engines": {
+        "node": ">= 14"
+      }
+    },
+    "node_modules/https-proxy-agent": {
+      "version": "7.0.6",
+      "resolved": "https://registry.npmjs.org/https-proxy-agent/-/https-proxy-agent-7.0.6.tgz",
+      "integrity": "sha512-vK9P5/iUfdl95AI+JVyUuIcVtd4ofvtrOr3HNtM2yxC9bnMbEdp3x01OhQNnjb8IJYi38VlTE3mBXwcfvywuSw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "agent-base": "^7.1.2",
+        "debug": "4"
+      },
+      "engines": {
+        "node": ">= 14"
+      }
+    },
+    "node_modules/iconv-lite": {
+      "version": "0.6.3",
+      "resolved": "https://registry.npmjs.org/iconv-lite/-/iconv-lite-0.6.3.tgz",
+      "integrity": "sha512-4fCk79wshMdzMp2rH06qWrJE4iolqLhCUH+OiuIgU++RB0+94NlDL81atO7GX55uUKueo0txHNtvEyI6D7WdMw==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "safer-buffer": ">= 2.1.2 < 3.0.0"
+      },
+      "engines": {
+        "node": ">=0.10.0"
+      }
+    },
+    "node_modules/indent-string": {
+      "version": "4.0.0",
+      "resolved": "https://registry.npmjs.org/indent-string/-/indent-string-4.0.0.tgz",
+      "integrity": "sha512-EdDDZu4A2OyIK7Lr/2zG+w5jmbuk1DVBnEwREQvBzspBJkCEbRa8GxU1lghYcaGJCnRWibjDXlq779X1/y5xwg==",
+      "dev": true,
+      "license": "MIT",
+      "engines": {
+        "node": ">=8"
+      }
+    },
+    "node_modules/is-potential-custom-element-name": {
+      "version": "1.0.1",
+      "resolved": "https://registry.npmjs.org/is-potential-custom-element-name/-/is-potential-custom-element-name-1.0.1.tgz",
+      "integrity": "sha512-bCYeRA2rVibKZd+s2625gGnGF/t7DSqDs4dP7CrLA1m7jKWz6pps0LpYLJN8Q64HtmPKJ1hrN3nzPNKFEKOUiQ==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/js-tokens": {
+      "version": "4.0.0",
+      "resolved": "https://registry.npmjs.org/js-tokens/-/js-tokens-4.0.0.tgz",
+      "integrity": "sha512-RdJUflcE3cUzKiMqQgsCu06FPu9UdIJO0beYbPhHN4k6apgJtifcoCtT9bcxOpYBtpD2kCM6Sbzg4CausW/PKQ==",
+      "license": "MIT"
+    },
+    "node_modules/jsdom": {
+      "version": "26.1.0",
+      "resolved": "https://registry.npmjs.org/jsdom/-/jsdom-26.1.0.tgz",
+      "integrity": "sha512-Cvc9WUhxSMEo4McES3P7oK3QaXldCfNWp7pl2NNeiIFlCoLr3kfq9kb1fxftiwk1FLV7CvpvDfonxtzUDeSOPg==",
+      "dev": true,
+      "license": "MIT",
+      "dependencies": {
+        "cssstyle": "^4.2.1",
+        "data-urls": "^5.0.0",
+        "decimal.js": "^10.5.0",
+        "html-encoding-sniffer": "^4.0.0",
+        "http-proxy-agent": "^7.0.2",
+        "https-proxy-agent": "^7.0.6",
+        "is-potential-custom-element-name": "^1.0.1",
+        "nwsapi": "^2.2.16",
+        "parse5": "^7.2.1",
+        "rrweb-cssom": "^0.8.0",
+        "saxes": "^6.0.0",
+        "symbol-tree": "^3.2.4",
+        "tough-cookie": "^5.1.1",
+        "w3c-xmlserializer": "^5.0.0",
+        "webidl-conversions": "^7.0.0",
+        "whatwg-encoding": "^3.1.1",
+        "whatwg-mimetype": "^4.0.0",
+        "whatwg-url": "^14.1.1",
+        "ws": "^8.18.0",
+        "xml-name-validator": "^5.0.0"
+      },
+      "engines": {
+        "node": ">=18"
+      },
+      "peerDependencies": {
+        "canvas": "^3.0.0"
+      },
+      "peerDependenciesMeta": {
+        "canvas": {
+          "optional": true
+        }
+      }
+    },
+    "node_modules/jsesc": {
+      "version": "3.1.0",
+      "resolved": "https://registry.npmjs.org/jsesc/-/jsesc-3.1.0.tgz",
+      "integrity": "sha512-/sM3dO2FOzXjKQhJuo0Q173wf2KOo8t4I8vHy6lF9poUp7bKT0/NHE8fPX23PwfhnykfqnC2xRxOnVw5XuGIaA==",
+      "dev": true,
+      "license": "MIT",
+      "bin": {
+        "jsesc": "bin/jsesc"
+      },
+      "engines": {
+        "node": ">=6"
+      }
+    },
+    "node_modules/json5": {
+      "version": "2.2.3",
+      "resolved": "https://registry.npmjs.org/json5/-/json5-2.2.3.tgz",
+      "integrity": "sha512-XmOWe7eyHYH14cLdVPoyg+GOH3rYX++KpzrylJwSW98t3Nk+U8XOl8FWKOgwtzdb8lXGf6zYwDUzeHMWfxasyg==",
+      "dev": true,
+      "license": "MIT",
+      "bin": {
+        "json5": "lib/cli.js"
+      },
+      "engines": {
+        "node": ">=6"
+      }
+    },
+    "node_modules/loose-envify": {
+      "version": "1.4.0",
+      "resolved": "https://registry.npmjs.org/loose-envify/-/loose-envify-1.4.0.tgz",
+      "integrity": "sha512-lyuxPGr/Wfhrlem2CL/UcnUc1zcqKAImBDzukY7Y5F/yQiNdko6+fRLevlw1HgMySw7f611UIY408EtxRSoK3Q==",
+      "license": "MIT",
+      "dependencies": {
+        "js-tokens": "^3.0.0 || ^4.0.0"
+      },
+      "bin": {
+        "loose-envify": "cli.js"
+      }
+    },
+    "node_modules/loupe": {
+      "version": "3.2.1",
+      "resolved": "https://registry.npmjs.org/loupe/-/loupe-3.2.1.tgz",
+      "integrity": "sha512-CdzqowRJCeLU72bHvWqwRBBlLcMEtIvGrlvef74kMnV2AolS9Y8xUv1I0U/MNAWMhBlKIoyuEgoJ0t/bbwHbLQ==",
+      "dev": true,
+      "license": "MIT"
+    },
+    "node_modules/lru-cache": {
+      "version": "5.1.1",
+      "resolved": "https://registry.npmjs.org/lru-cache/-/lru-cache-5.1.1.tgz",
+      "integrity": "sha512-KpNARQA3Iwv+jTA0utUVVbrh+Jlrr1Fv0e56GGzAFOXN7dk/Fvia
... [truncated by security-guidance: file exceeds per-file byte cap]

=== DIFF: web/src/chat/useConversa.ts ===
@@ -0,0 +1,221 @@
+/**
+ * O coração da tela `/chat` é uma **função pura**.
+ *
+ * A tela não decide nada sobre a conversa: recebe frames e os reduz. Não existe
+ * `setTimeout(6000)` no navegador — se existisse, a política de degradação teria
+ * duas cópias, e elas divergiriam na primeira mudança de limiar.
+ *
+ * Testar o reducer sem navegador é o que permite exercitar a janela de 37 s em
+ * milissegundos: uma suíte que dorme 37 s ninguém roda.
+ */
+
+import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";
+import { conectarChat, type StatusConexao } from "../api/ws";
+import type { EstadoConversa, EventoChat, Message } from "../api/tipos";
+
+export type Mensagem = Message & {
+  /** Bolha otimista: existe na tela e ainda não no banco. */
+  pendente: boolean;
+  /**
+   * Texto com valor monetário e `quote_id` nulo é **bug** (openapi.yaml,
+   * invariante 1). A tela **exibe** o bug; quem o impede é o backend.
+   */
+  suspeitaDeBug: boolean;
+};
+
+export type Estado = {
+  porId: Map<string, Mensagem>;
+  /** Ids temporários na ordem de envio. A reconciliação é FIFO. */
+  pendentesDoLead: string[];
+  mensagens: Mensagem[];
+  digitando: boolean;
+  state: EstadoConversa;
+  entradaBloqueada: boolean;
+  ultimoIndex: number;
+  conexao: StatusConexao;
+};
+
+export type Acao =
+  | EventoChat
+  | { type: "envio-local"; idTemp: string; texto: string }
+  | { type: "historico"; messages: Message[]; state?: EstadoConversa }
+  | { type: "conexao"; status: StatusConexao };
+
+/**
+ * O mesmo regex de dinheiro do guardrail do Núcleo, transcrito. Um marcador que
+ * dispara em "35 anos" viraria paranoia e ninguém olharia mais para ele.
+ */
+const DINHEIRO = /(R\$\s*[\d.,]+)|([\d.,]+\s*reais\b)/i;
+
+function pareceCotacaoSemLastro(m: Message): boolean {
+  // A fala do lead não é nossa: ele pode citar um valor sem que isso seja bug.
+  if (m.autor === "lead") return false;
+  const temQuote = m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "";
+  return DINHEIRO.test(m.conteudo) && !temQuote;
+}
+
+function enriquecer(m: Message, pendente: boolean): Mensagem {
+  return { ...m, pendente, suspeitaDeBug: pareceCotacaoSemLastro(m) };
+}
+
+export function estadoInicial(): Estado {
+  return {
+    porId: new Map(),
+    pendentesDoLead: [],
+    mensagens: [],
+    digitando: false,
+    state: "novo",
+    entradaBloqueada: false,
+    ultimoIndex: -1,
+    conexao: "conectando",
+  };
+}
+
+/**
+ * A ordem é `index`, nunca chegada nem `criado_em`: os timestamps do dataset
+ * estão 99,8 % fora de ordem, e sob replay de reconexão a chegada é arbitrária
+ * por construção. As bolhas otimistas ficam no fim, porque ainda não têm índice.
+ */
+function derivar(porId: Map<string, Mensagem>, pendentes: string[]): Mensagem[] {
+  const persistidas: Mensagem[] = [];
+  for (const m of porId.values()) if (!m.pendente) persistidas.push(m);
+  persistidas.sort((a, b) => a.index - b.index);
+  const otimistas = pendentes
+    .map((id) => porId.get(id))
+    .filter((m): m is Mensagem => m !== undefined);
+  return [...persistidas, ...otimistas];
+}
+
+function fechar(porId: Map<string, Mensagem>, pendentes: string[], base: Estado): Estado {
+  const mensagens = derivar(porId, pendentes);
+  let ultimo = -1;
+  for (const m of mensagens) if (!m.pendente && m.index > ultimo) ultimo = m.index;
+  return { ...base, porId, pendentesDoLead: pendentes, mensagens, ultimoIndex: ultimo };
+}
+
+export function reduzir(estado: Estado, acao: Acao): Estado {
+  switch (acao.type) {
+    case "message": {
+      const porId = new Map(estado.porId);
+      let pendentes = estado.pendentesDoLead;
+      const chegando = acao.message;
+
+      /*
+       * Reconciliação da bolha otimista: **por id, nunca por texto**. O conteúdo
+       * que volta já passou pelo mascaramento, e não existe endpoint que devolva
+       * a versão crua — casar por texto duplicaria a bolha exatamente na conversa
+       * que exercita PII. A fila é FIFO porque a camada de conversa enfileira em
+       * vez de recusar, então o lead pode mandar duas antes do primeiro eco.
+       */
+      if (
+        chegando.autor === "lead" &&
+        chegando.index > estado.ultimoIndex &&
+        pendentes.length > 0 &&
+        !porId.has(chegando.id)
+      ) {
+        const [primeiro, ...resto] = pendentes;
+        if (primeiro !== undefined) {
+          porId.delete(primeiro);
+          pendentes = resto;
+        }
+      }
+
+      porId.set(chegando.id, enriquecer(chegando, false));
+      return fechar(porId, pendentes, estado);
+    }
+
+    case "historico": {
+      const porId = new Map(estado.porId);
+      for (const m of acao.messages) porId.set(m.id, enriquecer(m, false));
+      const base = acao.state
+        ? { ...estado, state: acao.state, entradaBloqueada: acao.state === "encaminhado" }
+        : estado;
+      return fechar(porId, base.pendentesDoLead, base);
+    }
+
+    case "envio-local": {
+      const porId = new Map(estado.porId);
+      const otimista: Mensagem = {
+        id: acao.idTemp,
+        // Índice provisório: as pendentes são posicionadas no fim, não por ele.
+        index: Number.MAX_SAFE_INTEGER,
+        autor: "lead",
+        tipo: "text",
+        conteudo: acao.texto,
+        status: "pending",
+        quote_id: null,
+        criado_em: new Date().toISOString(),
+        pendente: true,
+        suspeitaDeBug: false,
+      };
+      porId.set(acao.idTemp, otimista);
+      return fechar(porId, [...estado.pendentesDoLead, acao.idTemp], estado);
+    }
+
+    /*
+     * O digitando é por TURNO, não por mensagem. Um cliente ingênuo o apagaria
+     * ao receber a primeira mensagem — e o lead veria o aviso de espera seguido
+     * de 31 s de silêncio morto, que é exatamente o buraco que a política existe
+     * para tapar.
+     */
+    case "typing":
+      return { ...estado, digitando: acao.ativo };
+
+    case "state":
+      return {
+        ...estado,
+        state: acao.state,
+        entradaBloqueada: acao.state === "encaminhado",
+      };
+
+    case "conexao":
+      return { ...estado, conexao: acao.status };
+
+    default:
+      return estado;
+  }
+}
+
+// ---------------------------------------------------------------------------
+
+let contador = 0;
+export function novoIdTemporario(): string {
+  contador += 1;
+  return `tmp-${contador}-${Date.now().toString(36)}`;
+}
+
+/** Liga o reducer ao socket. O componente não conhece o protocolo. */
+export function useConversa(conversationId: string | null, historico?: Message[] | null) {
+  const [estado, despachar] = useReducer(reduzir, undefined, estadoInicial);
+  const enviarRef = useRef<(texto: string) => boolean>(() => false);
+  const ultimoIndexRef = useRef(-1);
+  ultimoIndexRef.current = estado.ultimoIndex;
+
+  useEffect(() => {
+    if (!historico || historico.length === 0) return;
+    despachar({ type: "historico", messages: historico });
+  }, [historico]);
+
+  useEffect(() => {
+    if (conversationId === null) return;
+    const sessao = conectarChat(conversationId, {
+      ultimoIndex: () => ultimoIndexRef.current,
+      aoEvento: (evento) => despachar(evento),
+      aoStatus: (status) => despachar({ type: "conexao", status }),
+    });
+    enviarRef.current = (texto: string) => sessao.enviar({ type: "message", text: texto });
+    return () => {
+      enviarRef.current = () => false;
+      sessao.fechar();
+    };
+  }, [conversationId]);
+
+  const enviar = useCallback((texto: string) => {
+    const idTemp = novoIdTemporario();
+    despachar({ type: "envio-local", idTemp, texto });
+    enviarRef.current(texto);
+    return idTemp;
+  }, []);
+
+  return useMemo(() => ({ estado, enviar }), [estado, enviar]);
+}


=== DIFF: web/src/admin/PaginaStatus.tsx ===
@@ -0,0 +1,215 @@
+import { useEffect, useRef } from "react";
+import { api } from "../api/cliente";
+import type { EstadoBreaker, QuoteHealth, Usage } from "../api/tipos";
+import { Erro } from "../ui/Erro";
+import { duracao, inteiro, instante, percentual } from "../ui/formatar";
+import { useRecurso } from "../ui/useRecurso";
+import { PainelCusto } from "./PainelCusto";
+import { useEventos } from "./useEventos";
+
+const CLASSE_BREAKER: Record<EstadoBreaker, string> = {
+  fechado: "breaker breaker--fechado",
+  aberto: "breaker breaker--aberto",
+  meia_abertura: "breaker breaker--meia",
+};
+
+const TEXTO_BREAKER: Record<EstadoBreaker, string> = {
+  fechado: "fechado",
+  aberto: "aberto",
+  meia_abertura: "meia-abertura",
+};
+
+/**
+ * A saúde **real** da `/quote`, que é diferente do `/health` do legado.
+ *
+ * O `/health` deles responde 200 com 100 % das cotações falhando. Exibi-lo sem a
+ * ressalva é como se produz um monitor que mente — por isso a nota vem colada no
+ * número, e não num rodapé de documentação.
+ *
+ * O breaker é o único elemento com escala de cartaz: o avaliador precisa achá-lo
+ * em dois segundos.
+ */
+export function PaginaStatus() {
+  const saude = useRecurso<QuoteHealth>(() => api.quoteHealth(), []);
+  const uso = useRecurso<Usage>(() => api.usage(), []);
+  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
+
+  // Um cenário degradado emite dezenas de `quote.attempt` por segundo. Sem
+  // debounce a tela se repintaria a cada frame e o número ficaria ilegível.
+  useEventos((tipo) => {
+    if (tipo !== "quote.attempt") return;
+    if (debounce.current !== null) clearTimeout(debounce.current);
+    debounce.current = setTimeout(() => saude.recarregar(), 400);
+  });
+
+  useEffect(
+    () => () => {
+      if (debounce.current !== null) clearTimeout(debounce.current);
+    },
+    [],
+  );
+
+  // A âncora `/admin/status#custo` rola até a seção ao carregar.
+  useEffect(() => {
+    if (globalThis.location?.hash !== "#custo") return;
+    document.getElementById("custo")?.scrollIntoView({ block: "start" });
+  }, [saude.dado, uso.dado]);
+
+  if (saude.erro) return <Erro erro={saude.erro} aoTentarDeNovo={saude.recarregar} />;
+
+  const h = saude.dado;
+  /*
+   * Nada de estado antes de saber o estado. Desenhar o disjuntor como "fechado"
+   * enquanto a resposta não chegou é a mesma classe de defeito do `/health` do
+   * legado que esta tela existe para desmentir: um monitor que afirma o que não
+   * apurou.
+   */
+  if (h === null) {
+    return (
+      <section>
+        <div className="pagina__topo">
+          <h1 className="pagina__titulo">Status da integração</h1>
+        </div>
+        <p className="rotulo">Lendo a janela de tentativas…</p>
+      </section>
+    );
+  }
+
+  const breaker = h.breaker ?? { estado: "fechado" as EstadoBreaker, falhas_consecutivas: 0 };
+  const janela = h.janela;
+  const upstream = h.upstream_health;
+
+  return (
+    <section>
+      <div className="pagina__topo">
+        <div>
+          <h1 className="pagina__titulo">Status da integração</h1>
+          <p className="pagina__subtitulo">
+            Verde e vermelho não provam que a instabilidade foi tratada. Aqui estão a
+            janela real de tentativas, as latências e o estado do disjuntor.
+          </p>
+        </div>
+      </div>
+
+      {/*
+        O carimbo. É o único elemento da aplicação inteira com escala e rotação,
+        e a ousadia foi gasta aqui de propósito: um disjuntor aberto tem que ser
+        achado em dois segundos, sem ler nada.
+      */}
+      <div
+        className={CLASSE_BREAKER[breaker.estado]}
+        data-testid="breaker"
+        data-estado={breaker.estado}
+      >
+        <p className="breaker__selo">
+          <span className="breaker__caption">disjuntor da /quote</span>
+          <span className="breaker__estado">{TEXTO_BREAKER[breaker.estado]}</span>
+        </p>
+        <div className="breaker__dados">
+          <span className="metrica">
+            <span className="metrica__valor num">{breaker.falhas_consecutivas}</span>
+            <span className="metrica__nome">falhas seguidas</span>
+          </span>
+          <span className="metrica">
+            <span className="metrica__valor num">{instante(breaker.aberto_desde)}</span>
+            <span className="metrica__nome">abriu em</span>
+          </span>
+          {/* Quando reabre, não só que abriu — é a única informação acionável ali. */}
+          <span className="metrica">
+            <span className="metrica__valor num">{instante(breaker.reabre_em)}</span>
+            <span className="metrica__nome">reabre em</span>
+          </span>
+        </div>
+      </div>
+
+      <div className="grade">
+        <div className="metrica" data-testid="upstream">
+          <span className="metrica__valor">
+            {upstream?.status === "unreachable" ? "inalcançável" : (upstream?.status ?? "—")}
+          </span>
+          <span className="metrica__nome">o /health do legado responde</span>
+          <span className="metrica__nota">
+            {upstream?.nota ??
+              "responde 200 mesmo com 100% das cotações falhando — não é a saúde da cotação"}
+          </span>
+        </div>
+        <div className="metrica">
+          <span className="metrica__valor num" data-testid="taxa-sucesso">
+            {janela ? percentual(janela.taxa_sucesso) : "—"}
+          </span>
+          <span className="metrica__nome">cotações que deram certo</span>
+          <span className="metrica__nota">
+            {janela ? `${inteiro(janela.sucesso)} de ${inteiro(janela.total)} tentativas` : ""}
+          </span>
+        </div>
+        <div className="metrica">
+          <span className="metrica__valor num" data-testid="p50">
+            {janela ? duracao(janela.p50_ms) : "—"}
+          </span>
+          <span className="metrica__nome">metade responde em até</span>
+        </div>
+        <div className="metrica">
+          <span className="metrica__valor num" data-testid="p95">
+            {janela ? duracao(janela.p95_ms) : "—"}
+          </span>
+          <span className="metrica__nome">as 5% mais lentas passam de</span>
+          <span className="metrica__nota">inclui as chamadas lentas de 8 s</span>
+        </div>
+      </div>
+
+      <div className="cartao" data-testid="por-outcome">
+        <p className="rotulo" style={{ margin: "0 0 0.45rem" }}>
+          Como as tentativas terminaram
+        </p>
+        <div className="handoff__topo">
+          {Object.entries(janela?.por_outcome ?? {}).length === 0 ? (
+            <span className="rotulo">nenhuma tentativa na janela</span>
+          ) : (
+            Object.entries(janela?.por_outcome ?? {}).map(([nome, n]) => (
+              <span
+                key={nome}
+                className={nome === "ok" ? "selo selo--ok" : "selo selo--falha"}
+              >
+                {nome} <strong className="num">{n}</strong>
+              </span>
+            ))
+          )}
+        </div>
+      </div>
+
+      <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
+        Últimas tentativas
+      </h2>
+      {(h.ultimas_tentativas ?? []).length === 0 ? (
+        <p className="rotulo">nenhuma tentativa registrada na janela</p>
+      ) : (
+        <div>
+          {(h.ultimas_tentativas ?? []).map((t) => (
+            <div className="tentativa" data-testid={`tentativa-${t.id}`} key={t.id}>
+              <span>#{t.attempt}</span>
+              <span>{t.http_status === null || t.http_status === undefined ? "—" : t.http_status}</span>
+              <span>{duracao(t.latency_ms)}</span>
+              <span className="trilho">
+                <span className={t.outcome === "ok" ? "selo selo--ok" : "selo selo--falha"}>
+                  {t.outcome}
+                </span>
+                {/* Cada tentativa leva à conversa que a originou: é a navegação
+                    que demonstra rastreabilidade. */}
+                {t.conversation_id ? (
+                  <a href={`/admin/conversas/${t.conversation_id}`}>{t.conversation_id}</a>
+                ) : null}
+              </span>
+            </div>
+          ))}
+        </div>
+      )}
+
+      {uso.carregando ? (
+        <p className="rotulo">Somando o uso de tokens…</p>
+      ) : (
+        <PainelCusto usage={uso.dado} />
+      )}
+    </section>
+  );
+}
+


=== DIFF: tests/nucleo/test_resiliencia.py ===
@@ -0,0 +1,213 @@
+"""A fatia 4 — o critério que o enunciado diz que **mais separa**.
+
+Cada teste bate numa instância da API configurada para isolar um efeito:
+
+| porta | instância | configuração |
+|---|---|---|
+| 8001 | `lab-clean` | `FAILURE_RATE=0`, `SLOW_RATE=0` |
+| 8002 | `lab-fail`  | `FAILURE_RATE=1.0` |
+| 8003 | `lab-slow`  | `SLOW_RATE=1.0`, `SLOW_SECONDS=8` |
+
+⚠️ As suítes que dependem de `QUOTE_SEED` rodam **em série, com restart do container
+antes**: o RNG é um fluxo global do processo, e um cenário reproduzível é a tripla
+(seed, processo reiniciado, sequência exata). A seed sozinha não é nada.
+"""
+
+from __future__ import annotations
+
+import datetime as dt
+import os
+import time
+from concurrent.futures import ThreadPoolExecutor
+
+import httpx
+import pytest
+
+from app.contracts.quote import QuoteJobStatus, QuoteOutcome, QuoteRequest
+from app.persistence.models import QuoteAttempt
+from app.quote import client
+from app.quote.breaker import Estado, breaker_global, resetar_breaker
+from app.quote.job import executar_job
+
+pytestmark = [pytest.mark.db, pytest.mark.live, pytest.mark.serial]
+
+LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
+FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
+LENTA = os.getenv("QUOTE_API_LENTA", "http://localhost:8003")
+
+REQ = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
+                   cep="[CEP]", data_inicio=dt.date(2026, 10, 17))
+
+
+def _viva(url: str) -> bool:
+    try:
+        httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
+        return True
+    except Exception:  # noqa: BLE001
+        return False
+
+
+@pytest.fixture(autouse=True)
+def bancada(monkeypatch):
+    from app.config import get_settings
+
+    for url in (LIMPA, FALHA, LENTA):
+        if not _viva(url):
+            pytest.skip(f"bancada indisponível: {url}")
+    resetar_breaker()
+    client.resetar_semaforo()
+    yield
+    resetar_breaker()
+    client.resetar_semaforo()
+
+
+def _apontar(monkeypatch, url: str, **overrides):
+    from app.config import get_settings
+
+    cfg = get_settings()
+    monkeypatch.setattr(cfg, "quote_api_url", url)
+    for k, v in overrides.items():
+        monkeypatch.setattr(cfg, k, v)
+
+
+# ─── retry ───────────────────────────────────────────────────────────────────
+
+
+def test_tres_tentativas_em_5xx(sessao, conversa, monkeypatch):
+    _apontar(monkeypatch, FALHA, quote_backoff_teto_s=0.01)
+    q = executar_job(sessao, conversa.id, REQ)
+    assert q.status == str(QuoteJobStatus.FAILED)
+    assert [a.attempt for a in q.attempts] == [1, 2, 3]
+    assert all(a.outcome == "transient" for a in q.attempts)
+    assert all(a.http_status in (500, 502, 503) for a in q.attempts)
+
+
+def test_lenta_nao_e_falha(sessao, conversa, monkeypatch):
+    """10% das chamadas dormem 8,004 s e devolvem **200 correto**."""
+    _apontar(monkeypatch, LENTA)
+    q = executar_job(sessao, conversa.id, REQ)
+    assert q.status == str(QuoteJobStatus.OK)
+    assert len(q.attempts) == 1
+    assert 7_900 < q.attempts[0].latency_ms < 12_000
+
+
+def test_timeout_de_5s_destroi_o_sucesso(sessao, conversa, monkeypatch):
+    """Regressão que deixa **no código** o motivo de o timeout ser 12 s.
+
+    Se alguém "otimizar" para 5 s, este teste passa a falhar — e a mensagem diz por
+    quê. Sem ele, o número 12 vive só na prosa do README.
+    """
+    _apontar(monkeypatch, LENTA, quote_read_timeout_s=5.0,
+             quote_max_attempts=1, quote_backoff_teto_s=0.01)
+    q = executar_job(sessao, conversa.id, REQ)
+    assert q.status == str(QuoteJobStatus.FAILED)
+    assert q.attempts[0].outcome == "timeout"
+    assert q.attempts[0].http_status is None   # timeout não tem status
+
+
+# ─── o que NÃO retenta ───────────────────────────────────────────────────────
+
+
+def test_recusa_nao_consome_tentativa(sessao, conversa, monkeypatch):
+    _apontar(monkeypatch, LIMPA)
+    q = executar_job(sessao, conversa.id,
+                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
+    assert q.status == str(QuoteJobStatus.REFUSED)
+    assert len(q.attempts) == 1 and q.attempts[0].attempt == 1
+
+
+@pytest.mark.parametrize(
+    "req,porque",
+    [
+        (QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2030),
+         "ano futuro: 422 vestido de recusa, mas é dado nosso errado"),
+        (QuoteRequest(plano_id="completo", idade=17, veiculo_ano=2019),
+         "idade abaixo do mínimo: recusa real"),
+    ],
+)
+def test_nao_retentaveis_gastam_uma_tentativa_so(sessao, conversa, monkeypatch, req, porque):
+    _apontar(monkeypatch, LIMPA)
+    q = executar_job(sessao, conversa.id, req)
+    assert len(q.attempts) == 1, porque
+    assert not QuoteOutcome(q.attempts[0].outcome).retentavel
+
+
+def test_contar_linhas_e_a_ascercao_certa(sessao, conversa, monkeypatch):
+    """`quote_attempts` é a evidência que o /admin/status e a linha do tempo leem —
+    então o teste checa o que o avaliador vai ver, não um contador interno."""
+    _apontar(monkeypatch, LIMPA)
+    executar_job(sessao, conversa.id,
+                 QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
+    assert sessao.query(QuoteAttempt).count() == 1
+
+
+# ─── breaker ─────────────────────────────────────────────────────────────────
+
+
+def test_abre_apos_falhas_consecutivas(sessao, conversa, monkeypatch):
+    _apontar(monkeypatch, FALHA, quote_backoff_teto_s=0.01)
+    executar_job(sessao, conversa.id, REQ)          # 3 tentativas
+    assert breaker_global().estado is Estado.FECHADO or True
+    executar_job(sessao, conversa.id, REQ)          # +3 → passa de 5
+    assert breaker_global().estado is Estado.ABERTO
+
+
+def test_job_com_circuito_aberto_nasce_failed_sem_tentativa(sessao, conversa, monkeypatch):
+    """A tela precisa distinguir isso de "tentamos 3 vezes e falhou" — são situações
+    diferentes para quem opera."""
+    _apontar(monkeypatch, FALHA, quote_backoff_teto_s=0.01)
+    for _ in range(2):
+        executar_job(sessao, conversa.id, REQ)
+    q = executar_job(sessao, conversa.id, REQ)
+    assert q.status == str(QuoteJobStatus.FAILED)
+    assert q.attempts == []
+    assert q.circuito_aberto is True
+
+
+def test_recusa_nao_conta_para_o_breaker(sessao, conversa, monkeypatch):
+    """Recusa é a API funcionando perfeitamente; contá-la abriria o circuito num dia
+    de muitos leads idosos."""
+    _apontar(monkeypatch, LIMPA)
+    for _ in range(10):
+        executar_job(sessao, conversa.id,
+                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
+    assert breaker_global().estado is Estado.FECHADO
+
+
+# ─── semáforo ────────────────────────────────────────────────────────────────
+
+
+def test_semaforo_limita_as_chamadas_em_voo(monkeypatch):
+    """A asserção é sobre o **máximo em voo**, não sobre a latência final.
+
+    Medir latência não provaria nada: o legado só degrada acima de 40 lentas
+    simultâneas, então com 20 jobs toda tentativa fica em 8,1–8,9 s **com ou sem**
+    semáforo, e o teste passaria com a feature ausente.
+    """
+    _apontar(monkeypatch, LENTA)
+    sem = client.semaforo()
+    sem.zerar()
+    with ThreadPoolExecutor(max_workers=20) as ex:
+        list(ex.map(lambda _: client.chamar(REQ), range(20)))
+    assert sem.maximo_em_voo <= 8
+
+
+def test_sem_semaforo_o_teto_e_estourado(monkeypatch):
+    """O par negativo: prova que o contador mede o que diz medir. Sem ele, o contador
+    poderia estar sempre em 1 por um bug de instrumentação e o teste acima passaria
+    feliz."""
+    _apontar(monkeypatch, LENTA, quote_max_concorrencia=20)
+    client.resetar_semaforo()
+    sem = client.semaforo()
+    with ThreadPoolExecutor(max_workers=20) as ex:
+        list(ex.map(lambda _: client.chamar(REQ), range(20)))
+    assert sem.maximo_em_voo > 8
+
+
+# ─── backoff ─────────────────────────────────────────────────────────────────
+
+
+def test_backoff_tem_jitter_e_teto():
+    esperas = [client.calcular_backoff(n) for n in (1, 2, 3) for _ in range(50)]
+    assert len(set(esperas)) > 100                     # não é determinístico
+    assert max(esperas) <= client.get_settings().quote_backoff_teto_s


=== DIFF: web/src/chat/PaginaChat.tsx ===
@@ -0,0 +1,194 @@
+import { useEffect, useRef, useState } from "react";
+import type { ConversationDetail, Message } from "../api/tipos";
+import { Bolha } from "./Bolha";
+import { BlocoCotacao } from "./BlocoCotacao";
+import { Digitando } from "./Digitando";
+import { abrirSessao, reiniciarSessao } from "./sessao";
+import { useConversa } from "./useConversa";
+
+const ESTADO_LEGIVEL: Record<string, string> = {
+  novo: "conversa aberta",
+  qualificando: "coletando dados",
+  cotando: "cotação em andamento",
+  cotado: "cotação entregue",
+  fechado: "conversa encerrada",
+  encaminhado: "com a equipe",
+};
+
+/**
+ * A tela é um **cliente burro** de um fluxo de eventos. Ela não decide nada
+ * sobre a conversa: recebe `MessageEvent`, `TypingEvent` e `StateEvent`, mantém
+ * um mapa `id → Message` e renderiza ordenado por `index`.
+ *
+ * Não existe cronômetro aqui. Os 6 s e os 20 s da política de degradação são do
+ * backend — se a tela tivesse um `setTimeout(6000)`, existiriam duas cópias da
+ * política e elas divergiriam na primeira mudança de limiar.
+ */
+export function PaginaChat({ conversationId }: { conversationId?: string }) {
+  const [id, setId] = useState<string | null>(conversationId ?? null);
+  const [historico, setHistorico] = useState<Message[] | null>(null);
+  const [falhaAoAbrir, setFalhaAoAbrir] = useState(false);
+  const [rascunho, setRascunho] = useState("");
+  const fim = useRef<HTMLDivElement | null>(null);
+
+  // Retomada ao carregar. Um F5 no meio de uma janela de 37 s não pode destruir
+  // a conversa — sempre-nova é o comportamento do botão, não do carregamento.
+  useEffect(() => {
+    if (conversationId !== undefined) return;
+    let vivo = true;
+    void abrirSessao()
+      .then(({ id: aberta, detalhe }: { id: string; detalhe: ConversationDetail | null }) => {
+        if (!vivo) return;
+        setHistorico(detalhe?.messages ?? null);
+        setId(aberta);
+      })
+      .catch(() => {
+        if (vivo) setFalhaAoAbrir(true);
+      });
+    return () => {
+      vivo = false;
+    };
+  }, [conversationId]);
+
+  const { estado, enviar } = useConversa(id, historico);
+
+  useEffect(() => {
+    fim.current?.scrollIntoView({ block: "end" });
+  }, [estado.mensagens.length, estado.digitando]);
+
+  const submeter = () => {
+    const texto = rascunho.trim();
+    if (texto.length === 0 || estado.entradaBloqueada) return;
+    enviar(texto);
+    setRascunho("");
+  };
+
+  const trocarDeConversa = () => {
+    void reiniciarSessao()
+      .then((nova) => {
+        setHistorico(null);
+        setId(nova);
+      })
+      .catch(() => setFalhaAoAbrir(true));
+  };
+
+  return (
+    <div className="chat">
+      <header className="chat__topo">
+        <h1 className="chat__marca">AutoSeguro</h1>
+        <div className="chat__meta">
+          <span className="pilula" data-testid="estado-conversa">
+            {ESTADO_LEGIVEL[estado.state] ?? estado.state}
+          </span>
+        </div>
+      </header>
+
+      <div className="chat__acoes">
+        <button type="button" className="botao-fantasma" onClick={trocarDeConversa}>
+          Nova conversa
+        </button>
+        {/*
+          A navegação é assimétrica de propósito: `chat → admin` existe e é a
+          demonstração inteira da rastreabilidade. O inverso não existe.
+        */}
+        {id !== null ? (
+          <a className="elo-admin" href={`/admin/conversas/${id}`}>
+            Ver esta conversa no admin
+          </a>
+        ) : null}
+      </div>
+
+      <main className="chat__thread">
+        {estado.conexao === "reconectando" ? (
+          <p role="status" className="pilula pilula--atencao">
+            Reconectando… nada se perde: ao voltar, tudo que chegou aparece aqui.
+          </p>
+        ) : null}
+
+        {falhaAoAbrir ? (
+          <div role="alert" className="erro">
+            <p className="erro__titulo">Não consegui abrir a conversa</p>
+            <p className="erro__texto">
+              O backend não respondeu. Confira se ele está no ar com{" "}
+              <code>docker compose ps</code> e tente de novo.
+            </p>
+            <button
+              type="button"
+              className="botao"
+              onClick={() => {
+                setFalhaAoAbrir(false);
+                trocarDeConversa();
+              }}
+            >
+              Tentar de novo
+            </button>
+          </div>
+        ) : null}
+
+        {/*
+          Vazio é convite. Uma janela em branco de 37 s já é longa o bastante sem
+          que a primeira tela também não diga nada.
+        */}
+        {!falhaAoAbrir && estado.mensagens.length === 0 && !estado.digitando ? (
+          <p className="vazio__texto" data-testid="conversa-vazia">
+            Conte o que você precisa: idade, ano do carro, CEP e quando quer começar. Com
+            isso eu já consigo buscar o valor.
+          </p>
+        ) : null}
+
+        {estado.mensagens.map((m) =>
+          m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "" ? (
+            <BlocoCotacao key={m.id} mensagem={m} />
+          ) : (
+            <Bolha key={m.id} mensagem={m} />
+          ),
+        )}
+
+        {estado.digitando ? <Digitando /> : null}
+        <div ref={fim} />
+      </main>
+
+      <footer className="chat__rodape">
+        {estado.entradaBloqueada ? (
+          <p className="chat__travado">
+            Já passei sua conversa pra um atendente da equipe. A equipe assume daqui — por
+            isso o campo abaixo está travado.
+          </p>
+        ) : null}
+        <form
+          className="compositor"
+          onSubmit={(e) => {
+            e.preventDefault();
+            submeter();
+          }}
+        >
+          <label className="so-leitor" htmlFor="campo-mensagem">
+            Sua mensagem
+          </label>
+          <textarea
+            id="campo-mensagem"
+            className="compositor__campo"
+            placeholder="Escreva aqui…"
+            rows={1}
+            value={rascunho}
+            disabled={estado.entradaBloqueada}
+            onChange={(e) => setRascunho(e.target.value)}
+            onKeyDown={(e) => {
+              if (e.key === "Enter" && !e.shiftKey) {
+                e.preventDefault();
+                submeter();
+              }
+            }}
+          />
+          <button
+            type="submit"
+            className="compositor__enviar"
+            disabled={estado.entradaBloqueada || rascunho.trim().length === 0}
+          >
+            Enviar
+          </button>
+        </form>
+      </footer>
+    </div>
+  );
+}


=== DIFF: web/src/admin/PainelCusto.tsx ===
@@ -0,0 +1,191 @@
+import type { Usage, UsageAgregado } from "../api/tipos";
+import { Vazio } from "../ui/Vazio";
+import { dolar, duracao, formatarOuNa, inteiro, percentual } from "../ui/formatar";
+
+/**
+ * O painel de custo é uma **seção** de `/admin/status`, com título próprio e
+ * âncora — não um rodapé, não uma quinta tela (`DECISOES-FECHADAS.md` §8). São
+ * seis números, e o leitor já vai a `/admin/status` porque é lá que o circuit
+ * breaker aparece.
+ *
+ * Duas regras de exibição, e as duas são invariantes:
+ *
+ * 1. **A tela não abre arquivo de preço e não multiplica token por valor.** O
+ *    custo chega calculado do backend, com a vigência da tabela usada. Duas
+ *    origens de preço é como um custo histórico deixa de ser auditável no dia em
+ *    que a tabela muda.
+ * 2. **Nulo é "n/a", nunca "0 %".** O Ollama não reporta cache; um zero ali
+ *    diria "o cache não acertou" onde a verdade é "não existe cache neste
+ *    caminho". Todo número anulável passa por `formatarOuNa` — o `??` proibido
+ *    escrito em código.
+ */
+export function PainelCusto({ usage }: { usage: Usage | null }) {
+  const total: UsageAgregado | null = usage?.total ?? null;
+  const vazio =
+    total === null ||
+    (total.tokens_in === 0 &&
+      total.tokens_out === 0 &&
+      (usage?.por_conversa.length ?? 0) === 0);
+
+  return (
+    <section className="secao" id="custo" aria-labelledby="titulo-custo">
+      <h2 className="secao__titulo" id="titulo-custo">
+        Custo e uso de tokens
+      </h2>
+      <p className="pagina__subtitulo">
+        Lido da nossa própria base, a cada turno. Prova o prompt caching com número e diz
+        quanto custou cada conversa.
+      </p>
+
+      {vazio ? (
+        <div style={{ marginTop: "1rem" }}>
+          <Vazio titulo="Nenhum turno gravado ainda">
+            Assim que o agente responder a primeira mensagem, os tokens, o custo e a taxa
+            de acerto de cache aparecem aqui — com a vigência da tabela de preço usada.
+          </Vazio>
+        </div>
+      ) : (
+        <>
+          <div className="grade" style={{ marginTop: "1rem" }}>
+            <div className="metrica">
+              <span className="metrica__valor num">{inteiro(total.tokens_in)}</span>
+              <span className="metrica__nome">tokens enviados ao modelo</span>
+            </div>
+            <div className="metrica">
+              <span className="metrica__valor num">{inteiro(total.tokens_out)}</span>
+              <span className="metrica__nome">tokens gerados pelo modelo</span>
+            </div>
+            <div className="metrica">
+              <span
+                className={
+                  total.taxa_acerto_cache === null || total.taxa_acerto_cache === undefined
+                    ? "metrica__valor num metrica__valor--na"
+                    : "metrica__valor num"
+                }
+                data-testid="taxa-cache"
+              >
+                {formatarOuNa(total.taxa_acerto_cache, percentual)}
+              </span>
+              <span className="metrica__nome">do contexto veio do cache</span>
+              <span className="metrica__nota">
+                {total.cache_read === null || total.cache_read === undefined
+                  ? "este provider não reporta cache"
+                  : `${inteiro(total.cache_read)} lidos do cache`}
+              </span>
+            </div>
+            <div className="metrica">
+              <span
+                className={
+                  total.custo_usd === null || total.custo_usd === undefined
+                    ? "metrica__valor num metrica__valor--na"
+                    : "metrica__valor num"
+                }
+                data-testid="custo-total"
+              >
+                {formatarOuNa(total.custo_usd, dolar)}
+              </span>
+              <span className="metrica__nome">gasto acumulado nas conversas</span>
+              <span className="metrica__nota">
+                {/* Sem procedência, um custo é um número solto. */}
+                tabela vigente em{" "}
+                <span data-testid="vigencia">
+                  {formatarOuNa(total.pricing_vigencia, (v) => v)}
+                </span>
+              </span>
+            </div>
+            <div className="metrica">
+              <span className="metrica__valor num">
+                {formatarOuNa(total.latency_p50_ms, duracao)}
+              </span>
+              <span className="metrica__nome">metade dos turnos responde em até</span>
+            </div>
+          </div>
+
+          <h3 className="secao__titulo" style={{ marginTop: "1.4rem", fontSize: "1.05rem" }}>
+            Por provider
+          </h3>
+          <table className="tabela" role="table">
+            <thead>
+              <tr>
+                <th scope="col">Provider</th>
+                <th scope="col">Entrada</th>
+                <th scope="col">Saída</th>
+                <th scope="col">Acerto de cache</th>
+                <th scope="col">Custo</th>
+                <th scope="col">p50</th>
+              </tr>
+            </thead>
+            <tbody>
+              {(usage?.por_provider ?? []).map((p) => (
+                <tr key={p.provider}>
+                  <td data-rotulo="Provider">{p.provider}</td>
+                  <td data-rotulo="Entrada" className="num">
+                    {inteiro(p.tokens_in)}
+                  </td>
+                  <td data-rotulo="Saída" className="num">
+                    {inteiro(p.tokens_out)}
+                  </td>
+                  <td data-rotulo="Acerto de cache" className="num">
+                    {formatarOuNa(p.taxa_acerto_cache, percentual)}
+                  </td>
+                  <td data-rotulo="Custo" className="num">
+                    {formatarOuNa(p.custo_usd, dolar)}
+                  </td>
+                  <td data-rotulo="p50" className="num">
+                    {formatarOuNa(p.latency_p50_ms, duracao)}
+                  </td>
+                </tr>
+              ))}
+            </tbody>
+          </table>
+
+          {(usage?.por_conversa ?? []).length > 0 ? (
+            <>
+              <h3 className="secao__titulo" style={{ marginTop: "1.4rem", fontSize: "1.05rem" }}>
+                Por conversa
+              </h3>
+              <table className="tabela" role="table">
+                <thead>
+                  <tr>
+                    <th scope="col">Conversa</th>
+                    <th scope="col">Turnos</th>
+                    <th scope="col">Entrada</th>
+                    <th scope="col">Saída</th>
+                    <th scope="col">Acerto de cache</th>
+                    <th scope="col">Custo</th>
+                  </tr>
+                </thead>
+                <tbody>
+                  {(usage?.por_conversa ?? []).map((c) => (
+                    <tr key={c.conversation_id}>
+                      <td data-rotulo="Conversa">
+                        <a href={`/admin/conversas/${c.conversation_id}`}>
+                          {c.conversation_id}
+                        </a>
+                      </td>
+                      <td data-rotulo="Turnos" className="num">
+                        {c.turnos ?? "—"}
+                      </td>
+                      <td data-rotulo="Entrada" className="num">
+                        {inteiro(c.tokens_in)}
+                      </td>
+                      <td data-rotulo="Saída" className="num">
+                        {inteiro(c.tokens_out)}
+                      </td>
+                      <td data-rotulo="Acerto de cache" className="num">
+                        {formatarOuNa(c.taxa_acerto_cache, percentual)}
+                      </td>
+                      <td data-rotulo="Custo" className="num">
+                        {formatarOuNa(c.custo_usd, dolar)}
+                      </td>
+                    </tr>
+                  ))}
+                </tbody>
+              </table>
+            </>
+          ) : null}
+        </>
+      )}
+    </section>
+  );
+}


=== DIFF: web/src/admin/PaginaConversas.tsx ===
@@ -0,0 +1,153 @@
+import { useCallback, useId, useState } from "react";
+import { api } from "../api/cliente";
+import { ESTADOS_CONVERSA } from "../api/tipos";
+import type { ConversationSummary, PaginaConversas as Pagina, StatusJob } from "../api/tipos";
+import { Erro } from "../ui/Erro";
+import { Vazio } from "../ui/Vazio";
+import { instante } from "../ui/formatar";
+import { useRecurso } from "../ui/useRecurso";
+
+/**
+ * `refused` e `failed` precisam ser distinguíveis à primeira vista.
+ *
+ * Recusa é desfecho de **negócio** e não gera handoff; `failed` é
+ * indisponibilidade e gera. Empilhar os dois no mesmo cinza apagaria a decisão
+ * mais importante do produto — por isso cores diferentes, não dois tons.
+ */
+const SELO_COTACAO: Record<StatusJob, { texto: string; classe: string }> = {
+  pending: { texto: "cotando", classe: "selo selo--espera" },
+  ok: { texto: "cotada", classe: "selo selo--ok" },
+  refused: { texto: "recusada", classe: "selo selo--recusa" },
+  failed: { texto: "falhou", classe: "selo selo--falha" },
+};
+
+export function PaginaConversas() {
+  const idFiltro = useId();
+  const [estado, setEstado] = useState<string>("");
+  const [cursor, setCursor] = useState<string | undefined>(undefined);
+  const [acumulado, setAcumulado] = useState<ConversationSummary[]>([]);
+
+  const carregar = useCallback(async (): Promise<Pagina> => {
+    const p = await api.conversas({
+      ...(estado ? { state: estado } : {}),
+      ...(cursor ? { cursor } : {}),
+    });
+    setAcumulado((antes) => (cursor ? [...antes, ...p.items] : p.items));
+    return p;
+  }, [estado, cursor]);
+
+  const { dado, erro, carregando, recarregar } = useRecurso<Pagina>(carregar, [estado, cursor]);
+
+  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;
+
+  const linhas = acumulado;
+
+  return (
+    <section>
+      <div className="pagina__topo">
+        <div>
+          <h1 className="pagina__titulo">Conversas</h1>
+          <p className="pagina__subtitulo">
+            Tudo que o agente conduziu, com o desfecho da última cotação. A linha leva ao
+            detalhe, com mensagens e tentativas.
+          </p>
+        </div>
+      </div>
+
+      <div className="filtros">
+        <span className="campo">
+          <label className="rotulo" htmlFor={idFiltro}>
+            Estado
+          </label>
+          {/* Os valores saem do enum do contrato — nunca digitados à mão aqui. */}
+          <select
+            id={idFiltro}
+            value={estado}
+            onChange={(e) => {
+              setCursor(undefined);
+              setAcumulado([]);
+              setEstado(e.target.value);
+            }}
+          >
+            <option value="">todos</option>
+            {ESTADOS_CONVERSA.map((e) => (
+              <option key={e} value={e}>
+                {e}
+              </option>
+            ))}
+          </select>
+        </span>
+      </div>
+
+      {linhas.length === 0 && !carregando ? (
+        <Vazio titulo="Nenhuma conversa ainda">
+          O banco está no ar e vazio. Abra <code>/chat</code>, mande uma mensagem, e ela
+          aparece aqui com id, estado e o desfecho da cotação.
+        </Vazio>
+      ) : (
+        <table className="tabela" role="table">
+          <thead>
+            <tr>
+              <th scope="col">Conversa</th>
+              <th scope="col">Estado</th>
+              <th scope="col">Msgs</th>
+              <th scope="col">Última cotação</th>
+              <th scope="col">Última mensagem</th>
+              <th scope="col">Atualizada</th>
+            </tr>
+          </thead>
+          <tbody>
+            {linhas.map((c) => {
+              const selo = c.ultima_cotacao_status ? SELO_COTACAO[c.ultima_cotacao_status] : null;
+              return (
+                <tr key={c.id}>
+                  <td data-rotulo="Conversa">
+                    <a href={`/admin/conversas/${c.id}`}>{c.id}</a>
+                    {c.handoff_pendente ? (
+                      <span
+                        className="selo selo--falha"
+                        data-testid="marca-handoff-pendente"
+                        title="handoff pendente"
+                      >
+                        handoff
+                      </span>
+                    ) : null}
+                  </td>
+                  <td data-rotulo="Estado">
+                    <span className="selo selo--neutro">{c.state}</span>
+                  </td>
+                  <td data-rotulo="Msgs" className="num">
+                    {c.total_mensagens}
+                  </td>
+                  <td data-rotulo="Última cotação">
+                    {selo ? (
+                      <span className={selo.classe} data-testid="selo-cotacao">
+                        {selo.texto}
+                      </span>
+                    ) : (
+                      <span className="rotulo">sem cotação</span>
+                    )}
+                  </td>
+                  <td data-rotulo="Última mensagem">{c.ultima_mensagem ?? "—"}</td>
+                  <td data-rotulo="Atualizada" className="num">
+                    {instante(c.atualizado_em)}
+                  </td>
+                </tr>
+              );
+            })}
+          </tbody>
+        </table>
+      )}
+
+      {dado?.next_cursor ? (
+        <button
+          type="button"
+          className="botao botao--discreto"
+          onClick={() => setCursor(dado.next_cursor ?? undefined)}
+        >
+          Carregar mais
+        </button>
+      ) : null}
+    </section>
+  );
+}


=== DIFF: web/src/admin/DetalheConversa.tsx ===
@@ -0,0 +1,151 @@
+import { api } from "../api/cliente";
+import type { ConversationDetail, Message } from "../api/tipos";
+import { Erro } from "../ui/Erro";
+import { Vazio } from "../ui/Vazio";
+import { cepMascarado, hora } from "../ui/formatar";
+import { useRecurso } from "../ui/useRecurso";
+import { LinhaDoTempoCotacao } from "./LinhaDoTempoCotacao";
+
+const DINHEIRO = /(R\$\s*[\d.,]+)|([\d.,]+\s*reais\b)/i;
+
+function suspeita(m: Message): boolean {
+  if (m.autor === "lead") return false;
+  const temQuote = m.quote_id !== null && m.quote_id !== undefined && m.quote_id !== "";
+  return DINHEIRO.test(m.conteudo) && !temQuote;
+}
+
+const ROTULO_CAMPO: Record<string, string> = {
+  idade: "idade",
+  veiculo_ano: "ano do veículo",
+  cep: "CEP",
+  data_inicio: "data de início",
+  plano_id: "plano",
+};
+
+/**
+ * A resposta ao critério C4 numa tela só: cada mensagem com id e status, cada
+ * cotação com todas as suas tentativas.
+ *
+ * Aqui `sistema` **é** distinguível de `agente` — no admin isso é informação.
+ * Na `/chat` os dois são idênticos, de propósito. A assimetria é deliberada e as
+ * duas pontas têm teste, senão alguém "uniformiza" e a auditoria se perde.
+ */
+export function DetalheConversa({ id }: { id: string }) {
+  const { dado, erro, recarregar } = useRecurso<ConversationDetail>(
+    () => api.conversa(id),
+    [id],
+  );
+
+  if (erro) return <Erro erro={erro} aoTentarDeNovo={recarregar} />;
+  if (!dado) return <p className="rotulo">carregando…</p>;
+
+  // Ordem por `index`, nunca por timestamp: 99,8 % do dataset está fora de ordem.
+  const mensagens = [...(dado.messages ?? [])].sort((a, b) => a.index - b.index);
+  const perfil = dado.perfil ?? {};
+  const faltantes = perfil.campos_faltantes ?? [];
+
+  return (
+    <section>
+      <div className="pagina__topo">
+        <div>
+          <h1 className="pagina__titulo">Conversa {dado.id}</h1>
+          <p className="pagina__subtitulo">
+            Está em <strong>{dado.state}</strong>, aberta pelo canal {dado.channel}.
+          </p>
+        </div>
+      </div>
+
+      <div className="grade">
+        <div className="metrica">
+          <span className="metrica__valor num">{perfil.idade ?? "—"}</span>
+          <span className="metrica__nome">idade do condutor</span>
+        </div>
+        <div className="metrica">
+          <span className="metrica__valor num">{perfil.veiculo_ano ?? "—"}</span>
+          <span className="metrica__nome">ano do veículo</span>
+        </div>
+        <div className="metrica">
+          {/* Mascarado: não existe endpoint que devolva a versão crua. */}
+          <span className="metrica__valor num">{cepMascarado(perfil.cep)}</span>
+          <span className="metrica__nome">CEP</span>
+        </div>
+        <div className="metrica">
+          <span className="metrica__valor">{perfil.plano_id ?? "—"}</span>
+          <span className="metrica__nome">plano escolhido</span>
+        </div>
+      </div>
+
+      {faltantes.length > 0 ? (
+        <p className="chat__travado" data-testid="campos-faltantes">
+          Qualificação em andamento — faltam:{" "}
+          {faltantes.map((c) => ROTULO_CAMPO[c] ?? c).join(", ")}.
+        </p>
+      ) : null}
+
+      <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
+        Mensagens
+      </h2>
+      {mensagens.length === 0 ? (
+        <Vazio titulo="Nenhuma mensagem">
+          A conversa existe mas ninguém falou ainda.
+        </Vazio>
+      ) : (
+        <div>
+          {mensagens.map((m) => (
+            <div
+              key={m.id}
+              className={`msg msg--${m.autor}`}
+              data-testid={`msg-${m.id}`}
+              data-index={m.index}
+            >
+              <span className="num">{m.index}</span>
+              <span className="rotulo">{m.autor}</span>
+              <span className="msg__conteudo">
+                {m.conteudo}
+                {suspeita(m) ? (
+                  <span className="marca-bug" data-testid="marca-bug">
+                    valor sem cotação vinculada
+                  </span>
+                ) : null}
+              </span>
+              <span className="rotulo msg__meta">
+                <span className="num">{m.id}</span>
+                <span>{m.status}</span>
+                <span>{hora(m.criado_em)}</span>
+              </span>
+            </div>
+          ))}
+        </div>
+      )}
+
+      <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
+        Cotações
+      </h2>
+      {(dado.quotes ?? []).length === 0 ? (
+        <Vazio titulo="Nenhuma cotação">
+          Esta conversa não chegou a chamar a <code>/quote</code>.
+        </Vazio>
+      ) : (
+        (dado.quotes ?? []).map((q) => <LinhaDoTempoCotacao key={q.id} quote={q} />)
+      )}
+
+      {(dado.handoffs ?? []).length > 0 ? (
+        <>
+          <h2 className="secao__titulo" style={{ marginTop: "1.6rem" }}>
+            Handoffs
+          </h2>
+          {dado.handoffs.map((h) => (
+            <div className={`handoff handoff--${h.status}`} data-testid={`handoff-${h.id}`} key={h.id}>
+              <div className="handoff__topo">
+                <span className="selo selo--falha">{h.trigger}</span>
+                <span className="rotulo">disparado por {h.disparado_por}</span>
+                <span className="selo selo--neutro">{h.status}</span>
+              </div>
+              <p className="vazio__texto">{h.reason}</p>
+            </div>
+          ))}
+        </>
+      ) : null}
+    </section>
+  );
+}


=== DIFF: web/src/admin/PaginaHandoffs.tsx ===
@@ -0,0 +1,149 @@
+import { useState } from "react";
+import { ErroApi, api } from "../api/cliente";
+import type { FilaHandoffs, StatusHandoff } from "../api/tipos";
+import { Erro } from "../ui/Erro";
+import { Vazio } from "../ui/Vazio";
+import { instante } from "../ui/formatar";
+import { useRecurso } from "../ui/useRecurso";
+import { useEventos } from "./useEventos";
+
+/**
+ * Os **sete** gatilhos da tabela fechada (`DECISOES-FECHADAS.md` §3).
+ *
+ * `cotacao_recusada` não está aqui, e a ausência é a decisão: **recusa não vira
+ * handoff**. Ela é desfecho de negócio, registrado na conversa, sem prometer
+ * contato que ninguém fará.
+ */
+const GATILHO: Record<string, string> = {
+  assunto_sensivel: "assunto sensível",
+  guardrail: "guardrail",
+  lead_pediu: "o lead pediu uma pessoa",
+  cotacao_indisponivel: "cotação indisponível",
+  extracao_falhou: "extração falhou duas vezes",
+  objecao_fora_da_alcada: "objeção fora da alçada",
+  midia_sem_texto: "mídia sem texto",
+};
+
+/**
+ * Um gatilho determinístico e uma decisão do modelo produzem o mesmo sinal — e a
+ * fila distingue os dois, porque o operador precisa saber se está olhando uma
+ * regra que disparou ou um julgamento que pode ter errado.
+ */
+const ORIGEM: Record<string, string> = {
+  regra: "regra determinística",
+  modelo: "decisão do modelo",
+};
+
+const PROXIMOS: Record<StatusHandoff, StatusHandoff[]> = {
+  pendente: ["assumido", "resolvido"],
+  assumido: ["resolvido"],
+  // Terminal. Resolvido não volta para pendente — a tela nem oferece.
+  resolvido: [],
+};
+
+const ACAO: Record<StatusHandoff, string> = {
+  pendente: "Devolver",
+  assumido: "Assumir",
+  resolvido: "Resolver",
+};
+
+export function PaginaHandoffs() {
+  const [falhaNaTransicao, setFalhaNaTransicao] = useState<string | null>(null);
+  const fila = useRecurso<FilaHandoffs>(() => api.handoffs(), []);
+
+  /*
+   * O push **invalida e recarrega**; nunca sintetiza o item a partir do frame.
+   * Um item montado no cliente diverge do que o banco tem na primeira mudança de
+   * schema, e o admin existe para dizer a verdade sobre o banco.
+   */
+  useEventos((tipo) => {
+    if (tipo === "handoff.created" || tipo === "handoff.updated") fila.recarregar();
+  });
+
+  const transicionar = (id: string, status: StatusHandoff) => {
+    setFalhaNaTransicao(null);
+    void api
+      .transicionarHandoff(id, status)
+      .then(() => fila.recarregar())
+      .catch((e: unknown) => {
+        // O backend é a autoridade sobre o estado: em 409 a mensagem dele
+        // aparece e o item volta ao que o banco diz.
+        setFalhaNaTransicao(
+          e instanceof ErroApi ? e.message : "Não consegui aplicar essa transição.",
+        );
+        fila.recarregar();
+      });
+  };
+
+  if (fila.erro) return <Erro erro={fila.erro} aoTentarDeNovo={fila.recarregar} />;
+
+  const itens = fila.dado?.items ?? [];
+
+  return (
+    <section>
+      <div className="pagina__topo">
+        <div>
+          <h1 className="pagina__titulo">Fila de handoff</h1>
+          <p className="pagina__subtitulo">
+            Cada item mostra qual regra disparou — não uma frase gerada. A fila entra em
+            tempo real, sem recarregar a página.
+          </p>
+        </div>
+      </div>
+
+      {falhaNaTransicao !== null ? (
+        <div className="erro" role="alert">
+          <p className="erro__titulo">A transição não foi aplicada</p>
+          <p className="erro__texto">{falhaNaTransicao}</p>
+        </div>
+      ) : null}
+
+      {itens.length === 0 && !fila.carregando ? (
+        <Vazio titulo="Nenhum handoff na fila">
+          Nada pendente. Um caso novo aparece aqui sozinho, sem recarregar — os gatilhos
+          são os sete da tabela de decisões, e recusa de cotação não é um deles.
+        </Vazio>
+      ) : null}
+
+      {itens.map((h) => (
+        <article className={`handoff handoff--${h.status}`} data-testid={`handoff-${h.id}`} key={h.id}>
+          <div className="handoff__topo">
+            <span
+              className={
+                h.status === "pendente"
+                  ? "selo selo--falha"
+                  : h.status === "assumido"
+                    ? "selo selo--espera"
+                    : "selo selo--ok"
+              }
+            >
+              {h.status}
+            </span>
+            <strong>{GATILHO[h.trigger] ?? h.trigger}</strong>
+            <span className="selo selo--neutro" data-testid="disparado-por">
+              {ORIGEM[h.disparado_por] ?? h.disparado_por}
+            </span>
+            <a href={`/admin/conversas/${h.conversation_id}`}>{h.conversation_id}</a>
+            <span className="rotulo">{instante(h.criado_em)}</span>
+          </div>
+
+          {h.reason ? <p className="vazio__texto">{h.reason}</p> : null}
+          {h.summary ? <p className="vazio__texto">{h.summary}</p> : null}
+
+          <div className="handoff__acoes">
+            {PROXIMOS[h.status].map((proximo) => (
+              <button
+                key={proximo}
+                type="button"
+                className={proximo === "resolvido" ? "botao botao--discreto" : "botao"}
+                onClick={() => transicionar(h.id, proximo)}
+              >
+                {ACAO[proximo]}
+              </button>
+            ))}
+          </div>
+        </article>
+      ))}
+    </section>
+  );
+}


=== DIFF: tests/nucleo/test_espera.py ===
@@ -0,0 +1,139 @@
+"""A espera visível: aviso aos 6 s, reforço aos ~20 s.
+
+O relógio é o do **lead** — conta da chegada da mensagem dele —, e o disparo é de
+dentro da tool de cotação, não de um watchdog na camada de conversa.
+
+Estes testes usam limiares encurtados e a instância lenta real: o objetivo é provar
+**quando** o aviso sai, não simular o relógio.
+"""
+
+from __future__ import annotations
+
+import datetime as dt
+import os
+import time
+
+import httpx
+import pytest
+
+from app import textos
+from app.contracts.quote import QuoteRequest
+from app.quote import client
+from app.quote.breaker import resetar_breaker
+from app.quote.job import executar_job
+
+pytestmark = [pytest.mark.db, pytest.mark.live, pytest.mark.serial]
+
+LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
+FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
+LENTA = os.getenv("QUOTE_API_LENTA", "http://localhost:8003")
+
+REQ = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
+                   cep="[CEP]", data_inicio=dt.date(2026, 10, 17))
+
+
+@pytest.fixture(autouse=True)
+def bancada():
+    for url in (LIMPA, FALHA, LENTA):
+        try:
+            httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
+        except Exception:  # noqa: BLE001
+            pytest.skip(f"bancada indisponível: {url}")
+    resetar_breaker()
+    client.resetar_semaforo()
+    yield
+    resetar_breaker()
+    client.resetar_semaforo()
+
+
+class Coletor:
+    def __init__(self):
+        self.msgs: list[tuple[float, str]] = []
+        self.t0 = time.monotonic()
+
+    def __call__(self, texto: str) -> None:
+        self.msgs.append((time.monotonic() - self.t0, texto))
+
+    @property
+    def textos(self):
+        return [t for _, t in self.msgs]
+
+
+def _cfg(monkeypatch, url, **kw):
+    from app.config import get_settings
+
+    c = get_settings()
+    monkeypatch.setattr(c, "quote_api_url", url)
+    for k, v in kw.items():
+        monkeypatch.setattr(c, k, v)
+    return c
+
+
+def test_falha_rapida_com_retry_rapido_nao_avisa(sessao, conversa, monkeypatch):
+    """O 5xx volta em ~2 ms e o retry responde ~250 ms depois — o lead não percebe.
+
+    É por isso que o gatilho é por **tempo**, e não por falha de tentativa: um aviso
+    disparado pela falha cairia nessa janela e produziria "tô verificando…" seguido do
+    preço um quarto de segundo depois. Ruído, não cuidado.
+    """
+    _cfg(monkeypatch, FALHA, aviso_espera_s=6.0, reforco_espera_s=20.0,
+         quote_backoff_teto_s=0.01)
+    col = Coletor()
+    executar_job(sessao, conversa.id, REQ, avisar=col)
+    assert col.textos == []
+
+
+def test_aviso_sai_na_espera_longa(sessao, conversa, monkeypatch):
+    """Instância lenta: 8 s de sono. Com o limiar em 1 s, o aviso tem que sair."""
+    _cfg(monkeypatch, LENTA, aviso_espera_s=1.0, reforco_espera_s=99.0)
+    col = Coletor()
+    executar_job(sessao, conversa.id, REQ, avisar=col)
+    assert textos.AVISO_ESPERA in col.textos
+
+
+def test_aviso_e_reforco_na_ordem(sessao, conversa, monkeypatch):
+    _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
+         quote_backoff_teto_s=0.2)
+    col = Coletor()
+    executar_job(sessao, conversa.id, REQ, avisar=col)
+    assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]
+
+
+def test_cada_aviso_sai_uma_vez_so(sessao, conversa, monkeypatch):
+    """Três tentativas com o limiar baixo poderiam repetir o aviso a cada laço."""
+    _cfg(monkeypatch, FALHA, aviso_espera_s=0.01, reforco_espera_s=0.02,
+         quote_backoff_teto_s=0.2)
+    col = Coletor()
+    executar_job(sessao, conversa.id, REQ, avisar=col)
+    assert col.textos.count(textos.AVISO_ESPERA) == 1
+    assert col.textos.count(textos.REFORCO) == 1
+
+
+def test_relogio_e_o_do_lead_nao_o_da_tool(sessao, conversa, monkeypatch):
+    """O turno gasta a latência do modelo ANTES da tool. Contando do início da tool,
+    o lead ficaria 8 s no escuro antes do aviso."""
+    _cfg(monkeypatch, LIMPA, aviso_espera_s=2.0, reforco_espera_s=99.0)
+    col = Coletor()
+    # o lead escreveu 3 s atrás; a /quote limpa responde em milissegundos
+    executar_job(sessao, conversa.id, REQ,
+                 chegada_do_lead=time.monotonic() - 3.0, avisar=col)
+    assert textos.AVISO_ESPERA in col.textos
+
+
+def test_sucesso_rapido_nao_avisa(sessao, conversa, monkeypatch):
+    _cfg(monkeypatch, LIMPA, aviso_espera_s=6.0, reforco_espera_s=20.0)
+    col = Coletor()
+    executar_job(sessao, conversa.id, REQ, avisar=col)
+    assert col.textos == []
+
+
+def test_a_sequencia_degradada_completa(sessao, conversa, monkeypatch):
+    """O que o avaliador vai ler no transcript degradado: aviso, reforço, e o job
+    terminando `failed` — nunca um preço inventado."""
+    _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
+         quote_backoff_teto_s=0.2)
+    col = Coletor()
+    q = executar_job(sessao, conversa.id, REQ, avisar=col)
+    assert q.status == "failed"
+    assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]
+    assert not any("R$" in t for t in col.textos)


=== DIFF: app/quote/job.py ===
@@ -9,13 +9,25 @@ linha do tempo importa. É `quote_attempts` que responde, sem log nenhum: "tenta
 vezes, a 1ª deu 503 em 40 ms, a 2ª estourou o timeout aos 12 s, a 3ª voltou 200 aos
 8,01 s".
 
-Nesta fatia o job faz **uma** tentativa. Retry, backoff, semáforo e breaker entram na
-fatia 4.
+**O laço de retry.** Só `transient` e `timeout` retentam — 3 tentativas levam a 0,8% de
+falha residual, e a 4ª compraria 0,64 ponto percentual por mais um ciclo que pode ser
+de 12 s. `400` e `422`, nas duas formas, **nunca** retentam: retentá-los mascara defeito
+e queima tempo.
+
+**A espera é visível.** O relógio é o do lead — conta da chegada da mensagem dele, não
+de quando a tool começou —, e o disparo é daqui, não de um watchdog genérico na camada
+de conversa, que dispararia durante a geração do modelo.
+
+**O breaker é consultado antes da primeira tentativa.** Com o circuito aberto o job
+nasce `failed` **sem nenhuma tentativa** e com `circuito_aberto=True`: a tela precisa
+distinguir isso de "tentamos 3 vezes e falhou".
 """
 
 from __future__ import annotations
 
 import datetime as dt
+import threading
+import time
 import uuid
 
 from sqlalchemy.orm import Session
@@ -27,9 +39,11 @@ from app.contracts.quote import (
     QuotePayload,
     QuoteRequest,
 )
+from app.config import get_settings
 from app.persistence.models import Quote, QuoteAttempt
 from app.privacy.mascarar import mascarar
 from app.quote import client
+from app.quote.breaker import breaker_global
 
 
 def _id(p: str) -> str:
@@ -105,19 +119,116 @@ def finalizar(
     return q
 
 
-def executar_job(s: Session, conversation_id: str, req: QuoteRequest) -> Quote:
-    """Uma tentativa (fatia 3). O laço de retry entra na fatia 4."""
+def executar_job(
+    s: Session,
+    conversation_id: str,
+    req: QuoteRequest,
+    *,
+    chegada_do_lead: float | None = None,
+    avisar=None,
+) -> Quote:
+    """Executa o job até resolver, com retry, backoff e breaker.
+
+    `chegada_do_lead` é o `time.monotonic()` de quando a mensagem do lead entrou — o
+    **relógio do lead**. Se contássemos do início da tool, o aviso chegaria depois de o
+    lead já ter ficado 8 s no escuro, porque o turno gasta a latência do modelo antes.
+
+    `avisar(texto)` entrega uma mensagem ao lead durante a espera. É opcional para que
+    o job seja testável sem canal.
+    """
+    cfg = get_settings()
+    br = breaker_global()
+    t0 = chegada_do_lead if chegada_do_lead is not None else time.monotonic()
+
     q = criar_job(s, conversation_id, req)
-    resp = client.chamar(req)
-    erro = None if resp.ok else resp.erro()
-    gravar_tentativa(s, q.id, 1, resp, erro)
-
-    if resp.ok:
-        return finalizar(s, q, status=QuoteJobStatus.OK,
-                         payload=QuotePayload.model_validate(resp.corpo),
-                         latency_ms=resp.latency_ms)
-
-    status = {
-        QuoteOutcome.REFUSED: QuoteJobStatus.REFUSED,
-    }.get(erro.outcome, QuoteJobStatus.FAILED)
-    return finalizar(s, q, status=status, erro=erro, latency_ms=resp.latency_ms)
+
+    if not br.permite_chamada():
+        # Sem nenhuma tentativa: não chamamos a API, então não sabemos se este lead
+        # seria recusado. Afirmar recusa aqui seria adivinhar.
+        return finalizar(s, q, status=QuoteJobStatus.FAILED,
+                         erro=QuoteError(outcome=QuoteOutcome.TRANSIENT),
+                         circuito_aberto=True)
+
+    avisos = _Avisos(t0, avisar, cfg)
+    total = 0
+    erro: QuoteError | None = None
+
+    for tentativa in range(1, cfg.quote_max_attempts + 1):
+        resp = client.chamar(req)
+        total += resp.latency_ms
+        erro = None if resp.ok else resp.erro()
+        gravar_tentativa(s, q.id, tentativa, resp, erro)
+
+        if resp.ok:
+            br.registrar_sucesso()
+            avisos.cancelar()
+            return finalizar(s, q, status=QuoteJobStatus.OK,
+                             payload=QuotePayload.model_validate(resp.corpo),
+                             latency_ms=total)
+
+        if not erro.outcome.retentavel:
+            # 400 e 422 (nas duas formas): a API respondeu, e a resposta é final.
+            br.registrar_desfecho_de_negocio()
+            avisos.cancelar()
+            status = (QuoteJobStatus.REFUSED if erro.outcome is QuoteOutcome.REFUSED
+                      else QuoteJobStatus.FAILED)
+            return finalizar(s, q, status=status, erro=erro, latency_ms=total)
+
+        br.registrar_falha_transitoria()
+        if tentativa < cfg.quote_max_attempts:
+            time.sleep(client.calcular_backoff(tentativa))
+
+    avisos.cancelar()
+    return finalizar(s, q, status=QuoteJobStatus.FAILED, erro=erro, latency_ms=total)
+
+
+class _Avisos:
+    """Aviso aos 6 s e reforço aos ~20 s, contados do relógio do LEAD.
+
+    **São temporizadores, não verificações entre tentativas.** A primeira versão
+    checava o relógio no topo de cada volta do laço, e um teste pegou o furo: a
+    chamada lenta bloqueia 8 s numa tentativa só, então o aviso de 6 s só dispararia
+    **depois** de o preço já ter chegado. Inútil justamente nos 10% do tráfego que a
+    espera existe para cobrir.
+
+    O disparo continua sendo **da tool**, e não de um watchdog na camada de conversa:
+    o temporizador nasce e morre com o job, então ele só existe quando há de fato uma
+    cotação em voo — e nunca dispara durante a geração do modelo.
+    """
+
+    def __init__(self, t0: float, avisar, cfg) -> None:
+        self.avisar = avisar
+        self.enviados: list[str] = []
+        self._timers: list[threading.Timer] = []
+        if avisar is None:
+            return
+
+        from app import textos
+
+        # O relógio é o do lead: se ele já esperou 3 s antes de a tool começar, o
+        # aviso sai 3 s depois daqui, não 6.
+        decorrido = time.monotonic() - t0
+        for nome, limiar, texto in (
+            ("aviso", cfg.aviso_espera_s, textos.AVISO_ESPERA),
+            ("reforco", cfg.reforco_espera_s, textos.REFORCO),
+        ):
+            atraso = max(0.0, limiar - decorrido)
+            t = threading.Timer(atraso, self._disparar, args=(nome, texto))
+            t.daemon = True
+            t.start()
+            self._timers.append(t)
+
+    def _disparar(self, nome: str, texto: str) -> None:
+        # O aviso sempre precede o reforço, mesmo se os dois vencerem juntos: receber
+        # "ainda tô aqui" antes de "tô buscando" confundiria o lead.
+        if nome == "reforco" and "aviso" not in self.enviados:
+            return
+        if nome in self.enviados:
+            return
+        self.enviados.append(nome)
+        self.avisar(texto)
+
+    def cancelar(self) -> None:
+        """Chamado quando o job resolve: nada de aviso depois do preço."""
+        for t in self._timers:
+            t.cancel()


=== DIFF: web/src/chat/sessao.ts ===
@@ -0,0 +1,101 @@
+/**
+ * Sessão do lead: **retoma ao carregar, cria por botão**.
+ *
+ * `DECISOES-FECHADAS.md` §8: sempre-nova é o comportamento certo do botão, não
+ * do carregamento. A demonstração é uma janela de 37 s, e apertar F5 por
+ * impaciência é o gesto mais provável do mundo — um carregamento que sempre cria
+ * conversa destruiria exatamente o que se quer mostrar.
+ */
+
+import { ErroApi, ROTAS, api, post } from "../api/cliente";
+import type { Conversation, ConversationDetail } from "../api/tipos";
+
+export const CHAVE = "autoseguro.conversation_id";
+
+type Deps = {
+  post: (url: string, corpo: unknown) => Promise<{ id: string }>;
+  getConversa?: (id: string) => Promise<{ id: string } | null>;
+};
+
+function ler(): string | null {
+  try {
+    const v = localStorage.getItem(CHAVE);
+    return v && v.length > 0 ? v : null;
+  } catch {
+    // localStorage indisponível não pode quebrar a tela: a conversa segue,
+    // só não sobrevive ao reload.
+    return null;
+  }
+}
+
+function gravar(id: string): void {
+  try {
+    localStorage.setItem(CHAVE, id);
+  } catch {
+    /* idem */
+  }
+}
+
+function esquecer(): void {
+  try {
+    localStorage.removeItem(CHAVE);
+  } catch {
+    /* idem */
+  }
+}
+
+/**
+ * `external_ref` **nunca** é enviado daqui. O contrato avisa que ele não carrega
+ * telefone real, e este repositório é público: o jeito de garantir isso é não ter
+ * o campo, não confiar em quem preenche.
+ */
+export async function abrirOuRetomar(deps: Deps): Promise<string> {
+  const gravado = ler();
+  if (gravado !== null && deps.getConversa) {
+    const existente = await deps.getConversa(gravado);
+    // Se a gravada já não existe no backend (banco recriado), cria outra.
+    if (existente !== null && existente !== undefined) return gravado;
+  }
+  const criada = await deps.post(ROTAS.conversas(), { channel: "web" });
+  gravar(criada.id);
+  return criada.id;
+}
+
+export async function novaConversa(deps: Pick<Deps, "post">): Promise<string> {
+  esquecer();
+  const criada = await deps.post(ROTAS.conversas(), { channel: "web" });
+  gravar(criada.id);
+  return criada.id;
+}
+
+/**
+ * O que a tela usa. Ao retomar, o histórico vem de `GET /api/conversations/{id}`
+ * — já mascarado, já ordenado por `index` — **antes** de o socket abrir, e o
+ * `hello` sai com o `last_index` desse histórico: assim a reconexão não pede de
+ * volta o que a tela acabou de buscar.
+ */
+export async function abrirSessao(): Promise<{ id: string; detalhe: ConversationDetail | null }> {
+  let detalhe: ConversationDetail | null = null;
+
+  const id = await abrirOuRetomar({
+    post: (url, corpo) => post<Conversation>(url, corpo),
+    getConversa: async (gravado) => {
+      try {
+        detalhe = await api.conversa(gravado);
+        return detalhe;
+      } catch (e) {
+        if (e instanceof ErroApi && e.tipo === "nao_encontrado") {
+          detalhe = null;
+          return null;
+        }
+        throw e;
+      }
+    },
+  });
+
+  return { id, detalhe };
+}
+
+export async function reiniciarSessao(): Promise<string> {
+  return novaConversa({ post: (url, corpo) => post<Conversation>(url, corpo) });
+}


=== DIFF: web/src/admin/LinhaDoTempoCotacao.tsx ===
@@ -0,0 +1,99 @@
+import type { Outcome, Quote } from "../api/tipos";
+import { duracao } from "../ui/formatar";
+
+const CLASSE_OUTCOME: Record<Outcome, string> = {
+  ok: "selo selo--ok",
+  transient: "selo selo--falha",
+  timeout: "selo selo--falha",
+  refused: "selo selo--recusa",
+  bad_request: "selo selo--espera",
+};
+
+/**
+ * Enum **fechado** (`openapi.yaml`). Um `default` genérico esconderia um motivo
+ * novo, e é justamente um motivo novo que precisaria ser visto.
+ */
+const MOTIVO_RECUSA: Record<string, string> = {
+  idade_acima_do_limite: "Idade acima do limite de aceitação",
+  idade_abaixo_do_minimo: "Idade abaixo do mínimo",
+  veiculo_acima_de_20_anos: "Veículo acima de 20 anos",
+};
+
+/**
+ * A linha do tempo é a parte que prova que a instabilidade foi **tratada**, e
+ * não apenas sobrevivida: três tentativas com `outcome` diferente contam a
+ * política inteira sem uma linha de README.
+ */
+export function LinhaDoTempoCotacao({ quote }: { quote: Quote }) {
+  const maior = Math.max(1, ...quote.attempts.map((a) => a.latency_ms));
+
+  return (
+    <article className="cartao" data-testid={`quote-${quote.id}`} style={{ marginBottom: "0.7rem" }}>
+      <header className="handoff__topo">
+        <span className="rotulo">cotação {quote.id}</span>
+        <span
+          className={
+            quote.status === "ok"
+              ? "selo selo--ok"
+              : quote.status === "refused"
+                ? "selo selo--recusa"
+                : quote.status === "failed"
+                  ? "selo selo--falha"
+                  : "selo selo--espera"
+          }
+        >
+          {quote.status}
+        </span>
+        {quote.total_latency_ms !== null && quote.total_latency_ms !== undefined ? (
+          <span className="rotulo">total {duracao(quote.total_latency_ms)}</span>
+        ) : null}
+      </header>
+
+      {quote.status === "refused" && quote.motivo_recusa ? (
+        <p className="erro__texto" style={{ marginTop: "0.6rem" }}>
+          Recusa de negócio: <strong>{MOTIVO_RECUSA[quote.motivo_recusa] ?? quote.motivo_recusa}</strong>.
+          Recusa não gera handoff — é desfecho, não indisponibilidade.
+        </p>
+      ) : null}
+
+      {/*
+        O breaker impediu a chamada: o job é `failed` SEM nenhuma tentativa. Sem
+        esta distinção a tela sugere que a API foi chamada e não foi — e com o
+        breaker aberto não sabemos nada sobre este lead.
+      */}
+      {quote.circuito_aberto ? (
+        <p
+          className="selo selo--falha"
+          data-testid="selo-circuito-aberto"
+          style={{ marginTop: "0.6rem" }}
+        >
+          circuito aberto — não chamamos a /quote
+        </p>
+      ) : quote.attempts.length === 0 ? (
+        <p className="rotulo" style={{ marginTop: "0.6rem" }}>
+          sem tentativas registradas
+        </p>
+      ) : (
+        <div style={{ marginTop: "0.6rem" }}>
+          {quote.attempts.map((a) => (
+            <div className="tentativa" data-testid={`tentativa-${a.id}`} key={a.id}>
+              <span>#{a.attempt}</span>
+              {/* http_status nulo é "—", nunca "0": não houve resposta. */}
+              <span>{a.http_status === null || a.http_status === undefined ? "—" : a.http_status}</span>
+              <span>{duracao(a.latency_ms)}</span>
+              <span className="trilho">
+                <span
+                  className={
+                    a.outcome === "ok" ? "trilho__barra trilho__barra--ok" : "trilho__barra"
+                  }
+                  style={{ width: `${Math.max(4, (a.latency_ms / maior) * 100)}%` }}
+                />
+                <span className={CLASSE_OUTCOME[a.outcome]}>{a.outcome}</span>
+              </span>
+            </div>
+          ))}
+        </div>
+      )}
+    </article>
+  );
+}


=== DIFF: tests/web/e2e/ajuda/cenario.ts ===
@@ -0,0 +1,96 @@
+import { execFileSync } from "node:child_process";
+import { existsSync } from "node:fs";
+import type { BrowserContext, Page } from "@playwright/test";
+
+/**
+ * Os auxiliares que produzem **estado real**.
+ *
+ * Cada evidência declara o comando que a produz, e o teste falha se o estado não
+ * aparecer. Screenshot com dado de exemplo não vale: é a diferença entre provar
+ * e ilustrar.
+ *
+ * O restart do container da `/quote` não é zelo: o RNG do legado é um fluxo
+ * global e contínuo do **processo**, então sem `--force-recreate` a seed não
+ * significa nada (CLAUDE.md, reprodutibilidade).
+ */
+
+export type Cenario = "degradado" | "feliz";
+
+const AMBIENTE: Record<Cenario, Record<string, string>> = {
+  // 100 % das cotações falham: é o cenário que torna a degradação visível.
+  degradado: { QUOTE_FAILURE_RATE: "1.0", QUOTE_SLOW_RATE: "0", QUOTE_SEED: "42" },
+  feliz: { QUOTE_FAILURE_RATE: "0", QUOTE_SLOW_RATE: "0", QUOTE_SEED: "42" },
+};
+
+function compose(args: string[], env: Record<string, string> = {}): void {
+  execFileSync("docker", ["compose", ...args], {
+    stdio: "inherit",
+    env: { ...process.env, ...env },
+    timeout: 180_000,
+  });
+}
+
+async function esperarBackend(page: Page, tentativas = 60): Promise<void> {
+  for (let i = 0; i < tentativas; i += 1) {
+    try {
+      const r = await page.request.get("/api/health");
+      if (r.ok()) return;
+    } catch {
+      /* ainda subindo */
+    }
+    await page.waitForTimeout(1_000);
+  }
+  throw new Error("o backend não respondeu /api/health a tempo");
+}
+
+export async function subirCenario(cenario: Cenario, page?: Page): Promise<void> {
+  compose(["up", "-d", "--force-recreate", "quote-api"], AMBIENTE[cenario]);
+  if (page) await esperarBackend(page);
+}
+
+export async function recriarBancoVazio(page?: Page): Promise<void> {
+  compose(["down", "-v"]);
+  compose(["up", "-d"]);
+  if (page) await esperarBackend(page);
+}
+
+export function pararBackend(): void {
+  compose(["stop", "app"]);
+}
+
+export async function religarBackend(page?: Page): Promise<void> {
+  compose(["start", "app"]);
+  if (page) await esperarBackend(page);
+}
+
+/** Uma conversa real, conduzida pela UI. Nada aqui é injetado no banco. */
+export async function conversarUmaVez(page: Page, fala: string): Promise<void> {
+  await page.goto("/chat");
+  await page.getByRole("button", { name: /nova conversa/i }).click();
+  await page.getByRole("textbox").fill(fala);
+  await page.getByRole("textbox").press("Enter");
+}
+
+export async function dispararCotacoes(contexto: BrowserContext, quantas: number): Promise<void> {
+  // Em série, sempre: as suítes que dependem de QUOTE_SEED nunca rodam em
+  // paralelo, e o breaker conta falhas consecutivas.
+  for (let i = 0; i < quantas; i += 1) {
+    const p = await contexto.newPage();
+    await conversarUmaVez(p, "tenho 28 anos, carro 2019, plano completo, começo dia 17/10");
+    await p.waitForTimeout(2_000);
+    await p.close();
+  }
+}
+
+/**
+ * `scripts/seed_demo.sh` é dependência declarada do Núcleo e ainda não existe.
+ * Enquanto não existir, as telas são populadas do único jeito honesto: com
+ * conversas de verdade, conduzidas pela UI.
+ */
+export async function popularComDumpDeExemplo(contexto: BrowserContext): Promise<void> {
+  if (existsSync("scripts/seed_demo.sh")) {
+    execFileSync("bash", ["scripts/seed_demo.sh"], { stdio: "inherit", timeout: 180_000 });
+    return;
+  }
+  await dispararCotacoes(contexto, 2);
+}


=== DIFF: app/bootstrap.py ===
@@ -0,0 +1,93 @@
+"""Carregamento de ambiente e validação de credencial — explícito e testável.
+
+**O problema que isto resolve.** O `pydantic-settings` lê o `.env` para preencher os
+campos de `Settings`, com o prefixo `APP_`, mas **não exporta nada para `os.environ`**.
+O SDK da Anthropic, por outro lado, lê `ANTHROPIC_API_KEY` direto do ambiente do
+processo. Resultado: rodando local, a chave existe no arquivo e **não chega ao SDK**.
+
+O `docker compose` não tem esse problema — ele interpola `${ANTHROPIC_API_KEY}` do
+`.env` do diretório sozinho. Então o caminho que quebra é justamente o do
+desenvolvimento, e ele quebra tarde: uma exceção de autenticação no meio de outra
+coisa, e quinze minutos procurando no lugar errado.
+
+Duas funções, e as duas são chamadas em **todo** ponto de entrada:
+
+- `carregar_env()` põe no `os.environ` as variáveis sem prefixo que o `.env` declara,
+  sem nunca sobrescrever o que já veio do ambiente real;
+- `exigir_credenciais()` **falha alto no boot** se o provider configurado precisa de
+  credencial e ela não está lá, com uma mensagem que diz exatamente o que fazer.
+
+Mesmo princípio do catálogo: falhar no boot com mensagem clara é melhor que falhar no
+meio de uma conversa.
+"""
+
+from __future__ import annotations
+
+import os
+from pathlib import Path
+
+RAIZ = Path(__file__).resolve().parent.parent
+
+#: Variáveis que o SDK ou o legado leem direto do ambiente, sem passar por `Settings`.
+SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")
+
+
+class CredencialAusente(RuntimeError):
+    """Erra no boot, não no meio da conversa."""
+
+
+def carregar_env(caminho: Path | None = None) -> list[str]:
+    """Exporta para `os.environ` o que o `.env` declara sem prefixo.
+
+    **Nunca sobrescreve** o que já veio do ambiente real: quem exportou a variável no
+    shell mandou mais que o arquivo. Devolve os nomes carregados — nunca os valores.
+    """
+    arquivo = caminho or (RAIZ / ".env")
+    if not arquivo.exists():
+        return []
+    carregadas = []
+    for linha in arquivo.read_text().splitlines():
+        linha = linha.strip()
+        if not linha or linha.startswith("#") or "=" not in linha:
+            continue
+        chave, _, valor = linha.partition("=")
+        chave, valor = chave.strip(), valor.strip().strip('"').strip("'")
+        if not valor or chave in os.environ:
+            continue
+        if chave in SEM_PREFIXO or chave.startswith("QUOTE_"):
+            os.environ[chave] = valor
+            carregadas.append(chave)
+    return carregadas
+
+
+def exigir_credenciais(llm_model: str | None = None) -> None:
+    """Falha alto se o provider configurado precisa de credencial e ela não está lá."""
+    from app.config import get_settings
+
+    modelo = llm_model or get_settings().llm_model
+
+    if modelo.startswith("anthropic:") and not os.getenv("ANTHROPIC_API_KEY"):
+        raise CredencialAusente(
+            "APP_LLM_MODEL está em '%s', que exige ANTHROPIC_API_KEY, e ela não está "
+            "no ambiente do processo.\n"
+            "\n"
+            "  Como resolver:\n"
+            "    1. crie um .env na raiz com  ANTHROPIC_API_KEY=...  (o .gitignore já "
+            "o ignora), ou\n"
+            "    2. exporte a variável antes de rodar:  export ANTHROPIC_API_KEY=...\n"
+            "\n"
+            "  Atenção: o pydantic-settings lê o .env para os campos APP_*, mas NÃO "
+            "exporta nada para o os.environ — e o SDK da Anthropic lê a variável "
+            "direto do ambiente. Por isso este processo chama carregar_env() no "
+            "ponto de entrada. Se você está vendo esta mensagem, ou o .env não tem a "
+            "chave, ou carregar_env() não foi chamado.\n"
+            "\n"
+            "  Sem chave, use o outro provider validado:  "
+            "APP_LLM_MODEL=ollama:qwen2.5:7b" % modelo
+        )
+
+
+def bootstrap() -> None:
+    """Chamado por todo ponto de entrada: API, console e scripts."""
+    carregar_env()
+    exigir_credenciais()


=== DIFF: web/src/ui/Erro.tsx ===
@@ -0,0 +1,88 @@
+import { useId, useState } from "react";
+import { ErroApi, gravarToken } from "../api/cliente";
+
+/**
+ * Erro é estado de produto: uma tela em branco é a pior resposta possível a um
+ * backend parado, porque não distingue "não há nada" de "não consegui perguntar".
+ *
+ * Cada tipo diz **o que fazer**, não só que algo deu errado. O 401 em particular
+ * pede o `ADMIN_TOKEN` em vez de repetir a palavra "erro": o token é opcional e
+ * exigido quando definido (CLAUDE.md 14c), então quem tropeça nele já sabe que
+ * existe — falta só onde digitar.
+ */
+export function Erro({ erro, aoTentarDeNovo }: { erro: unknown; aoTentarDeNovo: () => void }) {
+  const idCampo = useId();
+  const [token, setToken] = useState("");
+  const api = erro instanceof ErroApi ? erro : null;
+  const tipo = api?.tipo ?? "erro";
+
+  if (tipo === "nao_autorizado") {
+    return (
+      <div className="erro" role="alert">
+        <p className="erro__titulo">Esta instalação exige um token de administração</p>
+        <p className="erro__texto">
+          O <code>ADMIN_TOKEN</code> está definido no backend. Ele fica guardado só neste
+          navegador e vai como cabeçalho em cada chamada.
+        </p>
+        <form
+          className="filtros"
+          onSubmit={(e) => {
+            e.preventDefault();
+            gravarToken(token.trim());
+            aoTentarDeNovo();
+          }}
+        >
+          <span className="campo">
+            <label className="rotulo" htmlFor={idCampo}>
+              ADMIN_TOKEN
+            </label>
+            <input
+              id={idCampo}
+              type="password"
+              value={token}
+              autoComplete="off"
+              onChange={(e) => setToken(e.target.value)}
+            />
+          </span>
+          <button type="submit" className="botao">
+            Tentar de novo
+          </button>
+        </form>
+      </div>
+    );
+  }
+
+  if (tipo === "nao_encontrado") {
+    return (
+      <div className="erro" role="alert">
+        <p className="erro__titulo">Não encontrado</p>
+        <p className="erro__texto">
+          {api?.message ?? "Esse registro não existe mais."} Se o banco foi recriado
+          (<code>docker compose down -v</code>), os ids anteriores não voltam.
+        </p>
+        <button type="button" className="botao botao--discreto" onClick={aoTentarDeNovo}>
+          Tentar de novo
+        </button>
+      </div>
+    );
+  }
+
+  return (
+    <div className="erro" role="alert">
+      <p className="erro__titulo">Backend indisponível</p>
+      <p className="erro__texto">
+        {tipo === "conflito" && api?.message ? (
+          api.message
+        ) : (
+          <>
+            Não consegui falar com a API. Confira se o serviço está no ar com{" "}
+            <code>docker compose ps</code> e tente de novo.
+          </>
+        )}
+      </p>
+      <button type="button" className="botao" onClick={aoTentarDeNovo}>
+        Tentar de novo
+      </button>
+    </div>
+  );
+}


=== DIFF: tests/nucleo/test_bootstrap.py ===
@@ -0,0 +1,80 @@
+"""Carregamento de ambiente e falha alta por credencial ausente.
+
+O modo de falha que isto previne é o pior tipo: o arquivo existe, a variável existe, e
+o SDK não a vê — porque o `pydantic-settings` não exporta para `os.environ`. O sintoma
+seria uma exceção de autenticação no meio de outra coisa.
+"""
+
+import os
+
+import pytest
+
+from app.bootstrap import CredencialAusente, carregar_env, exigir_credenciais
+
+
+def test_carrega_variavel_sem_prefixo(tmp_path, monkeypatch):
+    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
+    env = tmp_path / ".env"
+    env.write_text("ANTHROPIC_API_KEY=[REDIGIDO]\nAPP_LLM_MODEL=x\n")
+    assert carregar_env(env) == ["ANTHROPIC_API_KEY"]
+    assert os.environ["ANTHROPIC_API_KEY"] == "valor-de-teste"
+
+
+def test_nunca_sobrescreve_o_ambiente_real(tmp_path, monkeypatch):
+    """Quem exportou no shell mandou mais que o arquivo."""
+    monkeypatch.setenv("ANTHROPIC_API_KEY", "do-shell")
+    env = tmp_path / ".env"
+    env.write_text("ANTHROPIC_API_KEY=[REDIGIDO]\n")
+    carregar_env(env)
+    assert os.environ["ANTHROPIC_API_KEY"] == "do-shell"
+
+
+def test_nao_carrega_o_que_pertence_ao_settings(tmp_path, monkeypatch):
+    """`APP_*` é do pydantic-settings; duplicar aqui criaria dois caminhos para o
+    mesmo valor, e um deles ficaria para trás."""
+    monkeypatch.delenv("APP_DATABASE_URL", raising=False)
+    env = tmp_path / ".env"
+    env.write_text("APP_DATABASE_URL=postgres://x\n")
+    assert carregar_env(env) == []
+    assert "APP_DATABASE_URL" not in os.environ
+
+
+def test_env_ausente_nao_quebra(tmp_path):
+    assert carregar_env(tmp_path / "nao-existe") == []
+
+
+def test_valor_vazio_e_ignorado(tmp_path, monkeypatch):
+    """`.env.example` tem `ADMIN_TOKEN=` vazio; carregá-lo faria `admin_exigido`
+    virar verdadeiro com token vazio, que é pior que não ter."""
+    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
+    env = tmp_path / ".env"
+    env.write_text("ADMIN_TOKEN=\n")
+    assert carregar_env(env) == []
+
+
+def test_falha_alto_quando_anthropic_sem_chave(monkeypatch):
+    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
+    with pytest.raises(CredencialAusente) as e:
+        exigir_credenciais("anthropic:claude-opus-5")
+    msg = str(e.value)
+    # A mensagem diz exatamente o que fazer, incluindo a saída sem chave.
+    assert "ANTHROPIC_API_KEY" in msg
+    assert ".env" in msg
+    assert "ollama:qwen2.5:7b" in msg
+
+
+def test_ollama_nao_exige_chave(monkeypatch):
+    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
+    exigir_credenciais("ollama:qwen2.5:7b")   # não levanta
+
+
+def test_anthropic_com_chave_passa(monkeypatch):
+    monkeypatch.setenv("ANTHROPIC_API_KEY", "presente")
+    exigir_credenciais("anthropic:claude-opus-5")
+
+
+def test_a_mensagem_nao_vaza_o_valor_da_chave(monkeypatch):
+    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
+    with pytest.raises(CredencialAusente) as e:
+        exigir_credenciais("anthropic:claude-opus-5")
+    assert "sk-" not in str(e.value)


=== DIFF: web/src/admin/useEventos.ts ===
@@ -0,0 +1,80 @@
+/**
+ * **Um** socket `/api/events` para a sessão inteira, não um por tela.
+ *
+ * Um socket por tela faria o badge de pendentes piscar a cada navegação e o push
+ * sumir justamente enquanto o avaliador troca de aba. Por isso a conexão vive
+ * fora do ciclo de vida de qualquer componente: um singleton de módulo com
+ * contagem de assinantes.
+ *
+ * O que chega é usado só pelo `type`. O corpo do frame é ignorado de propósito:
+ * a tela **invalida e recarrega** do endpoint em vez de sintetizar o item, porque
+ * um item montado no cliente diverge do banco na primeira mudança de schema — e
+ * o admin existe para dizer a verdade sobre o banco.
+ */
+
+import { useEffect, useRef, useState } from "react";
+import { conectarEventos, type Sessao, type StatusConexao } from "../api/ws";
+import type { TipoEventoAdmin } from "../api/tipos";
+
+type Ouvinte = (tipo: TipoEventoAdmin) => void;
+
+let sessao: Sessao | null = null;
+let ouvintes = new Set<Ouvinte>();
+let ouvintesDeStatus = new Set<(s: StatusConexao) => void>();
+let statusAtual: StatusConexao = "conectando";
+
+function garantirSessao(): void {
+  if (sessao !== null) return;
+  sessao = conectarEventos({
+    aoEvento: (evento) => {
+      const tipo = evento.type;
+      for (const o of ouvintes) o(tipo);
+    },
+    aoStatus: (s) => {
+      statusAtual = s;
+      for (const o of ouvintesDeStatus) o(s);
+    },
+  });
+}
+
+function liberar(): void {
+  if (ouvintes.size > 0 || ouvintesDeStatus.size > 0) return;
+  sessao?.fechar();
+  sessao = null;
+  statusAtual = "conectando";
+}
+
+/** Só para o teste: derruba o singleton entre casos. */
+export function _reiniciarEventos(): void {
+  sessao?.fechar();
+  sessao = null;
+  ouvintes = new Set();
+  ouvintesDeStatus = new Set();
+  statusAtual = "conectando";
+}
+
+/**
+ * Assina o push. `aoEvento` recebe só o tipo — é tudo que a UI usa, e é tudo que
+ * o Núcleo precisa garantir no envelope.
+ */
+export function useEventos(aoEvento?: (tipo: TipoEventoAdmin) => void): StatusConexao {
+  const [status, setStatus] = useState<StatusConexao>(statusAtual);
+  const ref = useRef(aoEvento);
+  ref.current = aoEvento;
+
+  useEffect(() => {
+    const ouvinte: Ouvinte = (tipo) => ref.current?.(tipo);
+    const deStatus = (s: StatusConexao) => setStatus(s);
+    ouvintes.add(ouvinte);
+    ouvintesDeStatus.add(deStatus);
+    garantirSessao();
+    setStatus(statusAtual);
+    return () => {
+      ouvintes.delete(ouvinte);
+      ouvintesDeStatus.delete(deStatus);
+      liberar();
+    };
+  }, []);
+
+  return status;
+}


=== DIFF: web/src/admin/LayoutAdmin.tsx ===
@@ -0,0 +1,71 @@
+import type { ReactNode } from "react";
+import { api } from "../api/cliente";
+import type { FilaHandoffs } from "../api/tipos";
+import { useRecurso } from "../ui/useRecurso";
+import { useEventos } from "./useEventos";
+
+const ABAS = [
+  { href: "/admin/conversas", nome: "Conversas" },
+  { href: "/admin/status", nome: "Status" },
+  { href: "/admin/handoffs", nome: "Handoffs" },
+] as const;
+
+/**
+ * O layout carrega o badge de pendentes e mantém o socket de eventos. O badge é
+ * visível de **qualquer** tela — é o que faz a fila ser operada em vez de
+ * consultada.
+ *
+ * Duas ausências deliberadas:
+ *
+ * 1. **Não existe link `admin → chat`** (`DECISOES-FECHADAS.md` §8). Por ele o
+ *    avaliador assumiria o lugar do lead numa conversa que já tem handoff, e
+ *    isso não tem resposta boa. O inverso existe e é a demonstração inteira da
+ *    rastreabilidade. Há um teste negativo para isto, porque é o tipo de link
+ *    que alguém adiciona "por simetria" seis meses depois.
+ * 2. **Zero não vira badge.** Um "0" ali é ruído, não informação.
+ */
+export function LayoutAdmin({ rota, children }: { rota: string; children?: ReactNode }) {
+  const fila = useRecurso<FilaHandoffs>(() => api.handoffs({ limit: 1 }), []);
+
+  // Um admin que perdeu o push e não avisa é pior que um admin sem push: o
+  // operador passa a confiar numa fila parada.
+  const conexao = useEventos((tipo) => {
+    if (tipo === "handoff.created" || tipo === "handoff.updated") fila.recarregar();
+  });
+
+  const pendentes = fila.dado?.pendentes ?? 0;
+
+  return (
+    <div className="admin">
+      <header className="admin__barra">
+        <p className="admin__marca">AutoSeguro</p>
+        <nav className="admin__nav" aria-label="Telas de operação">
+          {ABAS.map((aba) => (
+            <a
+              key={aba.href}
+              href={aba.href}
+              aria-current={rota.startsWith(aba.href) ? "page" : undefined}
+            >
+              {aba.nome}
+            </a>
+          ))}
+        </nav>
+        {pendentes > 0 ? (
+          <span className="badge-pendentes" data-testid="badge-pendentes">
+            {pendentes}
+            <span className="so-leitor"> handoffs pendentes</span>
+          </span>
+        ) : null}
+        <span
+          className={
+            conexao === "conectado" ? "admin__conexao pilula" : "admin__conexao pilula pilula--atencao"
+          }
+          data-testid="conexao-eventos"
+        >
+          {conexao === "conectado" ? "recebendo em tempo real" : "sem conexão em tempo real"}
+        </span>
+      </header>
+      <div className="admin__conteudo">{children}</div>
+    </div>
+  );
+}


=== DIFF: web/src/ui/formatar.ts ===
@@ -0,0 +1,66 @@
+/**
+ * Formatação de exibição. **Nenhum valor monetário de cotação passa por aqui** —
+ * o bloco da cotação chega pronto do renderer, e formatar preço no front abriria
+ * uma segunda origem.
+ */
+
+/**
+ * O `??` proibido escrito em código.
+ *
+ * `cache_read` nulo é **"n/a", nunca "0 %"** (CLAUDE.md 26, migração 0002). Um
+ * zero ali diria "o cache não acertou" onde a verdade é "não existe cache neste
+ * caminho" — o Ollama não popula o campo. `formatarOuNa(v, f)` é a única porta:
+ * devolve "n/a" para `null | undefined` e formata o resto.
+ */
+export const NA = "n/a";
+
+export function formatarOuNa<T>(
+  valor: T | null | undefined,
+  formatador: (v: T) => string,
+): string {
+  if (valor === null || valor === undefined) return NA;
+  return formatador(valor);
+}
+
+export const inteiro = (n: number): string => n.toLocaleString("pt-BR");
+
+export const percentual = (v: number): string =>
+  `${(v * 100).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} %`;
+
+/** Custo em dólar da nossa própria base, já calculado pelo backend. */
+export const dolar = (v: number): string =>
+  `US$ ${v.toLocaleString("pt-BR", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
+
+/** Milissegundos legíveis: abaixo de 1 s em ms, acima em segundos. */
+export const duracao = (ms: number): string =>
+  ms < 1000
+    ? `${ms.toLocaleString("pt-BR")} ms`
+    : `${(ms / 1000).toLocaleString("pt-BR", {
+        minimumFractionDigits: 1,
+        maximumFractionDigits: 1,
+      })} s`;
+
+export function instante(iso: string | null | undefined): string {
+  if (!iso) return NA;
+  const d = new Date(iso);
+  if (Number.isNaN(d.getTime())) return iso;
+  return d.toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" });
+}
+
+export function hora(iso: string | null | undefined): string {
+  if (!iso) return NA;
+  const d = new Date(iso);
+  if (Number.isNaN(d.getTime())) return iso;
+  return d.toLocaleTimeString("pt-BR", { hour12: false });
+}
+
+/**
+ * O CEP aparece no admin **mascarado**: o perfil serve para mostrar progresso da
+ * qualificação, e o prefixo é o que importa ali.
+ */
+export function cepMascarado(cep: string | null | undefined): string {
+  if (!cep) return NA;
+  const digitos = cep.replace(/\D/g, "");
+  if (digitos.length < 5) return "•••••-•••";
+  return `${digitos.slice(0, 2)}•••-•••`;
+}


=== DIFF: web/src/ui/useRecurso.ts ===
@@ -0,0 +1,54 @@
+import { useCallback, useEffect, useRef, useState } from "react";
+
+/**
+ * Leitura de um endpoint com os três estados que importam: carregando, erro e
+ * dado. Não existe um quarto — "vazio" é uma decisão de cada tela sobre o dado,
+ * e confundir vazio com erro é o defeito que a fatia 8 mais persegue.
+ */
+export function useRecurso<T>(
+  carregar: () => Promise<T>,
+  deps: readonly unknown[] = [],
+): {
+  dado: T | null;
+  erro: unknown;
+  carregando: boolean;
+  recarregar: () => void;
+} {
+  const [dado, setDado] = useState<T | null>(null);
+  const [erro, setErro] = useState<unknown>(null);
+  const [carregando, setCarregando] = useState(true);
+  const [gatilho, setGatilho] = useState(0);
+  const fn = useRef(carregar);
+  fn.current = carregar;
+
+  /*
+   * A guarda contra `setState` depois do desmonte é o `cancelado` local desta
+   * execução, e só ele. Sob StrictMode o React monta, desmonta e remonta, então
+   * um segundo sinalizador em ref só acrescentaria um ciclo de vida para errar.
+   */
+  useEffect(() => {
+    let cancelado = false;
+    setCarregando(true);
+    fn.current()
+      .then((r) => {
+        if (cancelado) return;
+        setDado(r);
+        setErro(null);
+      })
+      .catch((e: unknown) => {
+        if (cancelado) return;
+        setErro(e);
+      })
+      .finally(() => {
+        if (cancelado) return;
+        setCarregando(false);
+      });
+    return () => {
+      cancelado = true;
+    };
+    // eslint-disable-next-line react-hooks/exhaustive-deps
+  }, [gatilho, ...deps]);
+
+  const recarregar = useCallback(() => setGatilho((g) => g + 1), []);
+  return { dado, erro, carregando, recarregar };
+}


=== DIFF: web/src/App.tsx ===
@@ -0,0 +1,53 @@
+import { useEffect, useState } from "react";
+import { Admin } from "./admin/Admin";
+import { PaginaChat } from "./chat/PaginaChat";
+
+/**
+ * Roteador mínimo, de propósito.
+ *
+ * São cinco rotas e nenhuma delas precisa de nested layouts, loaders ou data
+ * routers. Uma dependência de roteamento aqui pagaria em superfície de API e em
+ * um `<Router>` obrigatório em volta de todo teste de componente — que é o tipo
+ * de acoplamento que faz um teste de unidade deixar de ser de unidade.
+ */
+function useRota(): string {
+  const [rota, setRota] = useState(
+    () => globalThis.location?.pathname ?? "/chat",
+  );
+
+  useEffect(() => {
+    const aoVoltar = () => setRota(globalThis.location.pathname);
+    window.addEventListener("popstate", aoVoltar);
+
+    // Navegação interna sem recarregar: o admin mantém um socket por sessão, e
+    // um reload a cada clique o derrubaria — que é justamente o que a evidência
+    // de push em tempo real precisa não acontecer.
+    const aoClicar = (e: MouseEvent) => {
+      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey) return;
+      const alvo = (e.target as HTMLElement | null)?.closest("a");
+      if (!alvo) return;
+      const href = alvo.getAttribute("href");
+      if (!href || !href.startsWith("/") || alvo.target === "_blank") return;
+      e.preventDefault();
+      history.pushState(null, "", href);
+      setRota(globalThis.location.pathname);
+    };
+    document.addEventListener("click", aoClicar);
+
+    return () => {
+      window.removeEventListener("popstate", aoVoltar);
+      document.removeEventListener("click", aoClicar);
+    };
+  }, []);
+
+  return rota;
+}
+
+export function App() {
+  const rota = useRota();
+
+  if (rota.startsWith("/admin")) return <Admin rota={rota} />;
+  if (rota.startsWith("/chat")) return <PaginaChat />;
+
+  return <PaginaChat />;
+}


=== DIFF: web/src/chat/BlocoCotacao.tsx ===
@@ -0,0 +1,43 @@
+import type { Mensagem } from "./useConversa";
+
+/**
+ * **Este componente não formata número nenhum.**
+ *
+ * O bloco chega pronto do `quote/renderer.py`, que é a origem única do texto com
+ * valor monetário. Formatar moeda aqui abriria uma segunda origem de preço — e o
+ * invariante é que o preço nunca vem de outro lugar que não a `/quote`.
+ *
+ * A tela faz só duas coisas: preserva as quebras de linha e destaca a linha da
+ * carência, que já vem marcada do template. A carência é a ressalva que gera
+ * reclamação depois se passar batida, então ela tem tratamento próprio.
+ */
+export function BlocoCotacao({ mensagem }: { mensagem: Mensagem }) {
+  const linhas = mensagem.conteudo.split("\n");
+
+  return (
+    <div
+      className="cotacao"
+      data-testid="bloco-cotacao"
+      data-quote-id={mensagem.quote_id ?? ""}
+    >
+      {linhas.map((linha, i) => {
+        const vazia = linha.trim() === "";
+        const carencia = linha.includes("⚠️");
+        const classe = vazia
+          ? "cotacao__linha cotacao__linha--vazia"
+          : carencia
+            ? "cotacao__linha cotacao__linha--carencia"
+            : "cotacao__linha";
+        return (
+          // A ordem das linhas é fixa e vem do template: o índice é a identidade.
+          <p key={`${mensagem.id}-${i}`} className={classe}>
+            {linha}
+          </p>
+        );
+      })}
+      <div className="cotacao__rodape">
+        <span className="rotulo">cotação {mensagem.quote_id}</span>
+      </div>
+    </div>
+  );
+}


=== DIFF: web/tsconfig.json ===
@@ -0,0 +1,39 @@
+{
+  "compilerOptions": {
+    "target": "ES2022",
+    "lib": ["ES2022", "DOM", "DOM.Iterable"],
+    "module": "ESNext",
+    "moduleResolution": "bundler",
+    // A suíte mora em ../tests/web, fora deste pacote: sem isto o TypeScript não
+    // acha `web/node_modules` a partir de lá (mesmo motivo dos aliases do vitest).
+    "baseUrl": ".",
+    "paths": {
+      "react/jsx-runtime": ["./node_modules/@types/react/jsx-runtime"],
+      "react/jsx-dev-runtime": ["./node_modules/@types/react/jsx-dev-runtime"],
+      "*": ["./node_modules/@types/*", "./node_modules/*"]
+    },
+    "jsx": "react-jsx",
+    // A augmentação do jest-dom entra pelo import em tests/web/setup.ts, que faz
+    // parte do programa — pôr o pacote aqui traria a variante de Jest e quebraria
+    // o `.not` do vitest.
+    "types": ["node"],
+
+    "strict": true,
+    "noUncheckedIndexedAccess": true,
+    "noImplicitOverride": true,
+    "noUnusedLocals": true,
+    "noUnusedParameters": true,
+    "noFallthroughCasesInSwitch": true,
+    "exactOptionalPropertyTypes": false,
+    "verbatimModuleSyntax": true,
+    "isolatedModules": true,
+
+    "allowImportingTsExtensions": false,
+    "resolveJsonModule": true,
+    "skipLibCheck": true,
+    "esModuleInterop": true,
+    "forceConsistentCasingInFileNames": true,
+    "noEmit": true
+  },
+  "include": ["src", "scripts", "vite.config.ts", "vitest.config.ts", "playwright.config.ts", "../tests/web"]
+}


=== DIFF: web/scripts/baixar-openapi.mjs ===
@@ -0,0 +1,38 @@
+#!/usr/bin/env node
+/**
+ * Baixa o `openapi.json` que o backend **gera** e grava o snapshot que o teste de
+ * deriva compara com o `docs/openapi.yaml` **congelado**.
+ *
+ * O arquivo gerado não é versionado: ele é derivado do processo no ar, e um
+ * derivado no Git envelhece em silêncio. O teste de deriva confere isso.
+ *
+ * Uso, com o backend no ar:
+ *   npm --prefix web run openapi:baixar
+ */
+
+import { mkdirSync, writeFileSync } from "node:fs";
+import { dirname, resolve } from "node:path";
+import { fileURLToPath } from "node:url";
+
+const RAIZ = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
+const DESTINO = resolve(RAIZ, "tests/web/.openapi-gerado.json");
+const URL_PADRAO = process.env.OPENAPI_URL ?? "http://127.0.0.1:8080/openapi.json";
+
+try {
+  const resposta = await fetch(URL_PADRAO);
+  if (!resposta.ok) {
+    console.error(`[openapi] ${URL_PADRAO} respondeu ${resposta.status}`);
+    process.exit(1);
+  }
+  const spec = await resposta.json();
+  mkdirSync(dirname(DESTINO), { recursive: true });
+  writeFileSync(DESTINO, `${JSON.stringify(spec, null, 2)}\n`, "utf8");
+  const rotas = Object.keys(spec.paths ?? {}).length;
+  console.log(`[openapi] ${rotas} caminhos gravados em tests/web/.openapi-gerado.json`);
+} catch (erro) {
+  console.error(
+    `[openapi] não consegui falar com ${URL_PADRAO}. Suba o backend (docker compose up -d) e tente de novo.`,
+  );
+  console.error(`[openapi] ${erro instanceof Error ? erro.message : String(erro)}`);
+  process.exit(1);
+}


Investigate per the method in your instructions, then return the findings list.

### Claude

Looking at this large change, I'll focus on the security-critical files. The most concerning entry point is the WebSocket authentication in `web/src/api/ws.ts`, which departs from the header-based auth used elsewhere.

Let me verify by reading the key files.

### Claude

→ **Read**  `{"file_path": "/home/<usuario>/repo/web/src/api/ws.ts"}`

### Mateus

```
File does not exist. Note: your current working directory is <repo>.
```

### Claude

→ **Bash**  `{"command": "ls <repo>/", "description": "List repo root"}`

### Mateus

```
ai-logs
app
CLAUDE.md
config
db
docker-compose.yml
docs
node_modules
pyproject.toml
qa
README.md
scripts
tests
uv.lock
web
```

### Claude

→ **Bash**  `{"command": "ls <repo>/web/src/api/ 2>/dev/null; ls <repo>/app/", "description": "List key dirs"}`

### Mateus

```
cliente.ts
tipos.ts
ws.ts
agent
api
bootstrap.py
channels
config.py
contracts
conversa.py
handoff
__init__.py
main.py
persistence
privacy
__pycache__
quote
textos.py
```

### Claude

→ **Read**  `{"file_path": "<repo>/web/src/api/ws.ts"}`

### Mateus

```
1	/**
2	 * O transporte: `hello`/replay, reconexão com backoff e nada mais.
3	 *
4	 * A reconexão não é robustez extra. Com uma janela de até 37 s de socket aberto,
5	 * uma troca de rede ou um proxy impaciente apagariam justamente o aviso de espera
6	 * e o reforço — as duas mensagens que provam o comportamento sob falha.
7	 *
8	 * O protocolo de retomada: ao abrir (inclusive na primeira vez) o cliente manda
9	 * `{"type":"hello","last_index":N}` com o maior `index` que ele já tem (`-1`
10	 * quando não tem nenhum). O servidor responde com replay **do banco**, em ordem
11	 * de `index`. Como o reducer é idempotente por `id`, repetir não duplica — e é
12	 * por isso que o `hello` pode ser reenviado sem medo em toda reabertura.
13	 */
14	
15	import { ROTAS, lerToken } from "./cliente";
16	import { TIPOS_EVENTO_ADMIN, TIPOS_EVENTO_CHAT } from "./tipos";
17	import type { EventoAdmin, EventoChat } from "./tipos";
18	
19	export type StatusConexao = "conectando" | "conectado" | "reconectando" | "fechado";
20	
21	const BASE_MS = 500;
22	const TETO_MS = 10_000;
23	
24	export type Sessao = {
25	  fechar: () => void;
26	  enviar: (dado: unknown) => boolean;
27	  /** Delay do próximo reconnec
… [+4892 caracteres]
```

### Claude

→ **Grep**  `{"pattern": "token", "path": "<repo>/app/api", "output_mode": "files_with_matches"}`

### Mateus

```
Found 2 files
app/api/consultas.py
app/api/schemas.py
```

### Claude

→ **Grep**  `{"pattern": "token|ADMIN|websocket|WebSocket", "path": "<repo>/app/api/consultas.py", "output_mode": "content", "-n": true}`

### Mateus

```
78:    tokens_in_cacheaveis = sum(u.tokens_in for u in com_cache)
80:    if com_cache and (cache_read + tokens_in_cacheaveis) > 0:
81:        # A Anthropic reporta `input_tokens` já SEM os lidos de cache.
82:        taxa = cache_read / (cache_read + tokens_in_cacheaveis)
87:        "tokens_in": sum(u.tokens_in for u in linhas),
88:        "tokens_out": sum(u.tokens_out for u in linhas),
```

### Claude

→ **Grep**  `{"pattern": "admin_token|x-admin-token|ADMIN_TOKEN|WebSocket|websocket|/api/chat|/api/events", "path": "<repo>/app", "output_mode": "content", "-n": true, "head_limit": 50}`

### Mateus

```
app/bootstrap.py:32:SEM_PREFIXO = ("ANTHROPIC_API_KEY", "OLLAMA_API_KEY", "ADMIN_TOKEN")
app/main.py:12:- `ADMIN_TOKEN` é opcional: definido ⇒ exigido; ausente ⇒ sobe e avisa no log. Existe
app/main.py:59:            "ADMIN_TOKEN não definido: /api/* está sem autenticação. "
app/main.py:61:            "Defina ADMIN_TOKEN para exigir o cabeçalho X-Admin-Token."
app/main.py:86:def exigir_admin(x_admin_token: str | None = Header(default=None)) -> None:
app/main.py:87:    """Exigido **apenas** quando `ADMIN_TOKEN` está definido."""
app/main.py:89:    if cfg.admin_exigido and x_admin_token != cfg.admin_token:
app/main.py:195:# ─── websockets ──────────────────────────────────────────────────────────────
app/main.py:197:from app.channels.web import registrar_websockets  # noqa: E402
app/main.py:199:registrar_websockets(app)
app/config.py:31:    admin_token: str | None = None
app/config.py:75:        return self.admin_token is not None
app/channels/web.py:1:"""Adaptador `web` da porta `ChannelAdapter`, sobre WebSocket.
app/channels/web.py:8:O WebSocket não é request/response, então não há acoplamento a desfazer: quem chama
app/channels/web.py:39:from fastapi import FastAPI, WebSocket, Web
… [+1005 caracteres]
```

### Claude

→ **Read**  `{"file_path": "<repo>/app/channels/web.py", "offset": 100, "limit": 80}`

### Mateus

```
100	    for ws in _admin:
101	        try:
102	            await ws.send_text(frame)
103	        except Exception:  # noqa: BLE001
104	            mortos.append(ws)
105	    for ws in mortos:
106	        _admin.discard(ws)
107	
108	
109	def registrar_websockets(app: FastAPI) -> None:
110	    @app.websocket("/api/chat/{conversation_id}")
111	    async def chat(ws: WebSocket, conversation_id: str) -> None:
112	        await ws.accept()
113	        adaptador = WebChannelAdapter(ws)
114	        fabrica = sessao_factory()
115	
116	        with fabrica() as s:
117	            if repo.obter_conversa(s, conversation_id) is None:
118	                await ws.close(code=4404)
119	                return
120	
121	        try:
122	            while True:
123	                bruto = await ws.receive_text()
124	                msg = json.loads(bruto)
125	
126	                if msg.get("type") == "hello":
127	                    # Replay a partir do BANCO: o que saiu durante uma queda de socket
128	                    # numa janela de 37 s não pode se perder.
129	                    ultimo = int(msg.get("last_index", -1))
130	                    with fabrica() as s:
131	                        for
… [+1593 caracteres]
```

### Claude

I've confirmed the WebSocket auth model. The admin token is unconditionally appended as a query string parameter to **both** WebSocket URLs — the admin `/api/events` (which does validate it) AND the lead's `/api/chat/{id}` (which doesn't authenticate at all). Query-string tokens are a well-known credential-exposure pattern.

Now let me quickly check the other high-risk areas — bootstrap env loading and the retry/timer logic:

### Claude

→ **Read**  `{"file_path": "<repo>/app/quote/job.py", "offset": 115, "limit": 115}`

### Mateus

```
115	        q.erro_outcome = str(erro.outcome)
116	        if status is QuoteJobStatus.REFUSED and erro.motivo_recusa:
117	            q.motivo_recusa = str(erro.motivo_recusa)
118	    s.flush()
119	    return q
120	
121	
122	def executar_job(
123	    s: Session,
124	    conversation_id: str,
125	    req: QuoteRequest,
126	    *,
127	    chegada_do_lead: float | None = None,
128	    avisar=None,
129	) -> Quote:
130	    """Executa o job até resolver, com retry, backoff e breaker.
131	
132	    `chegada_do_lead` é o `time.monotonic()` de quando a mensagem do lead entrou — o
133	    **relógio do lead**. Se contássemos do início da tool, o aviso chegaria depois de o
134	    lead já ter ficado 8 s no escuro, porque o turno gasta a latência do modelo antes.
135	
136	    `avisar(texto)` entrega uma mensagem ao lead durante a espera. É opcional para que
137	    o job seja testável sem canal.
138	    """
139	    cfg = get_settings()
140	    br = breaker_global()
141	    t0 = chegada_do_lead if chegada_do_lead is not None else time.monotonic()
142	
143	    q = criar_job(s, conversation_id, req)
144	
145	    if not br.permite_chamada():
146	        # Sem nenhuma tentativa: não chamamos a API, 
… [+3784 caracteres]
```

### Claude

I have enough information. The main confirmed finding is the admin token being placed in WebSocket URL query strings — this ends up in server access logs, browser history, and any proxy logs, and it's applied even to the lead's `/api/chat/{id}` socket where the server doesn't authenticate at all (so the token exposure has no compensating benefit there).

The other changed files (bootstrap env loading, retry/timer logic, HTTP client, React reducers) don't introduce security vulnerabilities that I could substantiate as source→sink with no mitigation. The env loader is allowlisted, retry/backoff is not attacker-influenced, and the HTTP client uses proper headers.

### Claude

→ **StructuredOutput**  `{"findings": [{"filePath": "web/src/api/ws.ts", "category": "credential-exposure", "vulnerableCode": "const token = lerToken();\nconst query = token === null ? \"\" : `?token=${encodeURIComponent(token)}`;\nreturn `${esquema}//${host}${caminho}${query}`;", "explanation": "The admin credential (the s
… [+2212 caracteres]`

### Mateus

```
Structured output provided successfully
```
