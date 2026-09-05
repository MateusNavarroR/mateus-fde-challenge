"""Modelos de resposta da API — espelho do `docs/openapi.yaml` congelado.

O contrato foi congelado na Fase 0 para destravar a frente de Frontend antes de o
backend existir. Isso só é seguro com o **teste de deriva** (`tests/nucleo/
test_contrato_openapi.py`), que compara nos dois sentidos: toda rota do congelado
existe no gerado, e toda rota do gerado existe no congelado. O segundo é o que pega
superfície não documentada.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field


class Conversation(BaseModel):
    id: str
    channel: str
    state: str
    criado_em: dt.datetime


class LeadProfileOut(BaseModel):
    idade: int | None = None
    veiculo_ano: int | None = None
    #: 8 dígitos. Mascarado na exibição pela própria origem: a UI não tem versão crua.
    cep: str | None = None
    data_inicio: dt.date | None = None
    plano_id: str | None = None
    campos_faltantes: list[str] = Field(default_factory=list)


class MessageOut(BaseModel):
    id: str
    index: int
    autor: str
    tipo: str
    #: Sempre a versão mascarada. Não existe endpoint que devolva a crua.
    conteudo: str
    status: str
    quote_id: str | None = None
    criado_em: dt.datetime


class QuoteAttemptOut(BaseModel):
    id: str
    attempt: int
    #: Nulo quando não houve resposta: timeout de leitura ou erro de conexão.
    http_status: int | None = None
    latency_ms: int
    outcome: str
    criado_em: dt.datetime


class QuoteResultadoOut(BaseModel):
    premio_mensal: float
    franquia: int
    moeda: str
    coberturas: list[str]
    carencia: dict
    pro_rata: dict | None = None


class QuoteOut(BaseModel):
    id: str
    status: str
    request: dict
    resultado: QuoteResultadoOut | None = None
    motivo_recusa: str | None = None
    erro_outcome: str | None = None
    #: O job nasceu `failed` sem nenhuma tentativa. A tela precisa distinguir isso de
    #: "tentamos 3 vezes e falhou" — são situações diferentes para quem opera.
    circuito_aberto: bool = False
    total_latency_ms: int | None = None
    attempts: list[QuoteAttemptOut] = Field(default_factory=list)
    criado_em: dt.datetime


class HandoffOut(BaseModel):
    id: str
    conversation_id: str
    trigger: str
    reason: str
    summary: str | None = None
    disparado_por: str
    quote_id: str | None = None
    ultima_cotacao: QuoteOut | None = None
    status: str
    criado_em: dt.datetime
    assumido_em: dt.datetime | None = None
    resolved_at: dt.datetime | None = None


class ConversationSummary(Conversation):
    total_mensagens: int
    atualizado_em: dt.datetime
    ultima_mensagem: str | None = None
    handoff_pendente: bool = False
    ultima_cotacao_status: str | None = None


class ConversationDetail(Conversation):
    perfil: LeadProfileOut
    #: Ordenado por `index`. Nunca por timestamp.
    messages: list[MessageOut]
    quotes: list[QuoteOut]
    handoffs: list[HandoffOut]


class UsageAgregado(BaseModel):
    tokens_in: int
    tokens_out: int
    #: **Nulo, não zero**, quando o provider não reporta caching — o Ollama não
    #: reporta. Um zero diria "o cache não acertou" onde a verdade é "não existe
    #: cache neste caminho".
    cache_read: int | None = None
    cache_write: int | None = None
    taxa_acerto_cache: float | None = None
    custo_usd: float | None = None
    pricing_vigencia: dt.date | None = None
    latency_p50_ms: int | None = None


class UsagePorProvider(UsageAgregado):
    provider: str


class UsagePorConversa(UsageAgregado):
    conversation_id: str
    turnos: int


class Usage(BaseModel):
    total: UsageAgregado
    por_provider: list[UsagePorProvider]
    por_conversa: list[UsagePorConversa]


class Breaker(BaseModel):
    estado: str
    falhas_consecutivas: int
    aberto_desde: dt.datetime | None = None
    reabre_em: dt.datetime | None = None


class Janela(BaseModel):
    total: int
    sucesso: int
    taxa_sucesso: float
    p50_ms: int
    #: Inclui as chamadas lentas de 8 s — é justamente o que se quer ver.
    p95_ms: int
    por_outcome: dict[str, int] = Field(default_factory=dict)


class UpstreamHealth(BaseModel):
    status: str
    latency_ms: int | None = None
    #: Lembrete exibido na tela: o `/health` do legado responde 200 mesmo com 100%
    #: das cotações falhando. Confundir os dois é como se produz um monitor que mente.
    nota: str | None = None


class TentativaComOrigem(QuoteAttemptOut):
    quote_id: str
    conversation_id: str


class QuoteHealth(BaseModel):
    upstream_health: UpstreamHealth
    janela: Janela
    breaker: Breaker
    ultimas_tentativas: list[TentativaComOrigem]


class Erro(BaseModel):
    error: str
    message: str


class CacheDoPrompt(BaseModel):
    """`fracao_do_cache` é anulável de propósito: sem turno medido não há fração, e
    0% diria que o cache falhou onde a verdade é que não houve o que medir."""

    turnos_medidos: int
    tokens_do_cache: int
    tokens_enviados: int
    fracao_do_cache: float | None
    turnos_sem_cache: int


class EvalsResumo(BaseModel):
    """O que os módulos NATIVOS do Agno gravaram em `ai.eval_runs`.

    O recorte por tipo não é enfeite: os dois avaliadores medem coisas incomparáveis.
    `reliability` confere por CÁLCULO que as tools esperadas foram chamadas com os
    argumentos esperados; `juiz` é um modelo julgando a nossa redação de recusa. Somar
    os dois num total só produziria um número que não responde a pergunta nenhuma.
    """

    total: int
    passaram: int
    reliability: int = 0
    juiz: int = 0
    #: Quando a última avaliação rodou. `None` = nenhuma até agora — e o painel diz
    #: isso com palavras, porque um zero aqui é indistinguível de "avaliou e reprovou".
    ultimo: str | None = None


class Resumo(BaseModel):
    """Os números do painel. Cada campo é um recorte declarado, não uma agregação
    genérica — ver `consultas.resumo_operacao` para o porquê de cada um."""

    conversas: int
    conversas_encaminhadas: int
    mensagens_enviadas: int
    mensagens_recebidas: int
    cotacoes_ok: int
    cotacoes_recusadas: int
    cotacoes_falhas: int
    handoffs_pendentes: int
    handoffs_total: int
    cache: CacheDoPrompt
    evals: EvalsResumo
