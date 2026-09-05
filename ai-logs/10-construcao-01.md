# Sessão de construção 01

> Exportado por `scripts/exportar_ai_logs.py`, com redação de segredo,
> caminho absoluto e PII **na escrita**. 11 turnos; o `jsonl` de
> origem tinha 216 KB, majoritariamente saída de
> ferramenta, truncada em 1200 caracteres por bloco.

### Mateus

Review this change for security vulnerabilities.

Changed files (you may Read these and any other file in the repo):
  - app/contracts/channel.py
  - app/contracts/conversa.py
  - app/contracts/quote.py
  - config/model_pricing.yaml
  - db/migrations/0001_inicial.sql
  - db/migrations/0002_turn_usage.sql
  - docs/openapi.yaml
  - pyproject.toml
  - tests/test_contratos.py

Unified diff (only + lines are new):

=== DIFF: app/contracts/channel.py ===
@@ -0,0 +1,84 @@
+"""A porta `ChannelAdapter` — o agente é agnóstico de canal.
+
+Dois adaptadores são entregues, ambos **sem credencial**:
+
+| Adaptador | Papel |
+|---|---|
+| `console` | CLI determinístico. Gera o log de execução completa e roda no CI. |
+| `web`     | Interface que simula o WhatsApp, sobre WebSocket. |
+
+WhatsApp Cloud API e Baileys **não são entregues**, e isso é decisão de escopo, não
+omissão: nenhum critério de avaliação depende do canal, ambos exigiriam credencial e
+webhook público que quem clona não tem, e o tempo foi para o que é avaliado. O contrato
+que cada um cumpriria está documentado em `docs/ARQUITETURA.md`.
+
+O desenho da porta é o que torna essa afirmação verificável: os dois adaptadores
+entregues são maximamente diferentes — um é síncrono e in-process, o outro é
+assíncrono, multi-cliente e com estado de conexão. O que sobrevive aos dois é o que
+uma implementação Meta ou Baileys também cumpriria.
+"""
+
+from __future__ import annotations
+
+from collections.abc import AsyncIterator
+from typing import Protocol, runtime_checkable
+
+from app.contracts.conversa import TipoMidia
+
+
+class InboundMessage(Protocol):
+    """Mensagem que entra pelo canal.
+
+    `external_id` é o identificador do canal (o `wamid` no WhatsApp, o índice da linha
+    no console). É por ele que se deduplica: o mesmo `external_id` entregue duas vezes
+    produz **um** turno. Canais reais reentregam; o console não, mas o contrato é o
+    mesmo para que o teste do console prove o caminho.
+    """
+
+    conversation_id: str
+    external_id: str
+    tipo: TipoMidia
+    texto: str
+
+
+@runtime_checkable
+class ChannelAdapter(Protocol):
+    """Porta de canal.
+
+    Três operações, e só três. `typing` está aqui — e não é enfeite — porque é o que
+    torna a degradação da `/quote` **visível** ao lead: quando a cotação demora, o
+    "digitando…" e o aviso de espera acontecem no canal enquanto o job continua.
+    Um canal que não sabe sinalizar espera não consegue expressar o comportamento que
+    o desafio avalia.
+    """
+
+    name: str
+
+    async def send(
+        self,
+        conversation_id: str,
+        text: str,
+        *,
+        message_id: str,
+        quote_id: str | None = None,
+    ) -> str:
+        """Envia uma mensagem e devolve o `external_id` atribuído pelo canal.
+
+        `message_id` é **nosso** e vem de fora: a linha em `messages` é criada com
+        status `pending` antes do envio e passa a `sent` com o retorno daqui. Assim
+        uma falha de canal deixa rastro em vez de sumir.
+
+        `quote_id` acompanha a mensagem que carrega uma cotação. É o guardrail
+        auditável: mensagem com valor monetário sem `quote_id` é bug.
+        """
+        ...
+
+    async def typing(self, conversation_id: str, *, ativo: bool) -> None:
+        """Liga/desliga o indicador de digitação. Idempotente, e falhar aqui **nunca**
+        interrompe o turno — é sinalização, não conteúdo."""
+        ...
+
+    def receive(self) -> AsyncIterator[InboundMessage]:
+        """Fluxo de mensagens que chegam. O runtime consome; o adaptador não decide
+        nada sobre a conversa."""
+        ...


=== DIFF: app/contracts/conversa.py ===
@@ -0,0 +1,203 @@
+"""Contratos da conversa — lead, turno, estado e sinal de handoff.
+
+Congelado na Fase 0. Ver `app/contracts/quote.py` para o motivo de os contratos
+viverem num pacote próprio.
+"""
+
+from __future__ import annotations
+
+import datetime as dt
+from enum import StrEnum
+from typing import Annotated, Literal
+
+from pydantic import BaseModel, ConfigDict, Field
+
+from app.contracts.quote import PlanoId, QuoteRequest
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Perfil do lead
+# ─────────────────────────────────────────────────────────────────────────────
+
+#: Os cinco campos da qualificação, na ordem em que são perguntados.
+#: Cada um está aqui porque muda o resultado ou destrava um campo da resposta:
+#: idade e ano do veículo definem multiplicador *e* aceitação; CEP vale até 30% de
+#: agravo; data de início destrava o pro-rata; plano define a base.
+CAMPOS_QUALIFICACAO: tuple[str, ...] = (
+    "idade",
+    "veiculo_ano",
+    "cep",
+    "data_inicio",
+    "plano_id",
+)
+
+
+class LeadProfile(BaseModel):
+    """O que sabemos do lead. Todo campo é opcional porque a conversa é incremental.
+
+    Guarda também o **texto de origem** de cada extração: quando a `/quote` devolve
+    `bad_request`, é a origem que diz se reperguntamos ou se o bug é do extrator — e
+    é o que a tela de rastreabilidade mostra ao operador.
+    """
+
+    model_config = ConfigDict(extra="forbid")
+
+    idade: Annotated[int, Field(ge=0, le=200)] | None = None
+    veiculo_ano: Annotated[int, Field(ge=1950, le=2100)] | None = None
+    #: Sempre 8 dígitos, sem máscara. Ver `QuoteRequest._normalizar_cep`.
+    cep: Annotated[str, Field(pattern=r"^\d{8}$")] | None = None
+    data_inicio: dt.date | None = None
+    plano_id: PlanoId | None = None
+
+    #: Texto livre de onde veio cada campo, para auditoria. Chave = nome do campo.
+    #: **Mascarado antes de persistir** — pode conter CPF e CEP crus.
+    origem: dict[str, str] = Field(default_factory=dict)
+
+    #: Quantas vezes já reperguntamos cada campo. Alimenta o gatilho de handoff por
+    #: falha de extração repetida.
+    tentativas_extracao: dict[str, int] = Field(default_factory=dict)
+
+    @property
+    def campos_faltantes(self) -> tuple[str, ...]:
+        return tuple(c for c in CAMPOS_QUALIFICACAO if getattr(self, c) is None)
+
+    @property
+    def completo(self) -> bool:
+        return not self.campos_faltantes
+
+    def to_quote_request(self) -> QuoteRequest:
+        """Só é chamável com o perfil completo — cotar com campo faltando é
+        exatamente o erro que a `/quote` não reporta (`plano_id: ""` cota
+        `essencial` calado)."""
+        if not self.completo:
+            raise ValueError(
+                f"perfil incompleto: faltam {', '.join(self.campos_faltantes)}"
+            )
+        return QuoteRequest(
+            plano_id=self.plano_id,
+            idade=self.idade,
+            veiculo_ano=self.veiculo_ano,
+            cep=self.cep,
+            data_inicio=self.data_inicio,
+        )
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Turno e mensagem
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class Autor(StrEnum):
+    LEAD = "lead"
+    AGENTE = "agente"
+    #: Mensagem gerada pelo sistema sem passar pelo modelo — o texto da cotação
+    #: renderizado por template, o aviso de espera, o texto de recusa.
+    SISTEMA = "sistema"
+    OPERADOR = "operador"
+
+
+class MessageStatus(StrEnum):
+    """Estado de entrega de uma mensagem. Critério declarado: *cada mensagem com id
+    e status*."""
+
+    RECEIVED = "received"     # do lead, aceita
+    PENDING = "pending"       # nossa, ainda não entregue ao canal
+    SENT = "sent"
+    FAILED = "failed"
+    DISCARDED = "discarded"   # duplicada ou fora de janela
+
+
+TipoMidia = Literal["text", "image", "audio", "document"]
+
+
+class Turn(BaseModel):
+    """Uma mensagem da conversa. Unidade de persistência e de exibição.
+
+    `conteudo` é sempre a versão **mascarada**. O texto cru não é persistido nem
+    trafega para log, trace ou UI.
+    """
+
+    model_config = ConfigDict(frozen=True)
+
+    message_id: str
+    conversation_id: str
+    #: Ordem canônica dentro da conversa. É por ela que se ordena, nunca por timestamp.
+    index: Annotated[int, Field(ge=0)]
+    autor: Autor
+    tipo: TipoMidia = "text"
+    conteudo: str
+    status: MessageStatus
+    criado_em: dt.datetime
+    #: `quote_id` quando esta mensagem carrega uma cotação. É o guardrail auditável:
+    #: nenhum valor monetário sai numa mensagem sem este vínculo.
+    quote_id: str | None = None
+
+
+class ConversationState(StrEnum):
+    """Máquina de estados da conversa.
+
+    ```
+    novo → qualificando → cotando → cotado → fechado
+              │              │         │
+              └──────────────┴─────────┴──────► encaminhado
+    ```
+
+    `encaminhado` é alcançável de qualquer estado — é a saída de todos os gatilhos.
+    """
+
+    NOVO = "novo"
+    QUALIFICANDO = "qualificando"
+    COTANDO = "cotando"
+    COTADO = "cotado"
+    FECHADO = "fechado"
+    ENCAMINHADO = "encaminhado"
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Handoff
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class HandoffTrigger(StrEnum):
+    """Gatilhos de handoff, como dados e não como `if` espalhado.
+
+    ⚠️ **Conjunto provisório.** A tabela definitiva — quais gatilhos, qual precedência
+    e o que o bot diz em cada um — é uma das quatro decisões abertas do usuário
+    (`docs/DECISOES-ABERTAS.md`). Este enum existe para que as outras frentes tenham
+    contra o que compilar; ele é substituído pela decisão fechada.
+    """
+
+    LEAD_PEDIU = "lead_pediu_atendente"
+    COTACAO_INDISPONIVEL = "cotacao_indisponivel"
+    COTACAO_RECUSADA = "cotacao_recusada"
+    EXTRACAO_FALHOU = "extracao_falhou"
+    ASSUNTO_SENSIVEL = "assunto_sensivel"
+    OBJECAO_FORA_DA_ALCADA = "objecao_fora_da_alcada"
+    MIDIA_SEM_TEXTO = "midia_sem_texto"
+    GUARDRAIL = "guardrail"
+
+
+class HandoffStatus(StrEnum):
+    PENDENTE = "pendente"
+    ASSUMIDO = "assumido"
+    RESOLVIDO = "resolvido"
+
+
+class HandoffSignal(BaseModel):
+    """Sinal de handoff no padrão **write-back**: a tool do agente só registra a
+    intenção; quem executa é o backend.
+
+    Isso mantém o comportamento testável e impede o modelo de causar efeito colateral
+    direto — e é o que permite que um gatilho determinístico (breaker aberto, 422 de
+    recusa) produza exatamente o mesmo sinal que uma decisão do modelo.
+    """
+
+    model_config = ConfigDict(frozen=True)
+
+    trigger: HandoffTrigger
+    #: Motivo legível para o operador. Nunca é o texto cru da API nem do lead.
+    reason: str
+    summary: str | None = None
+    #: Última cotação tentada, quando houver — a fila mostra o desfecho dela.
+    quote_id: str | None = None
+    #: Preenchido pelo backend, não pelo modelo.
+    disparado_por: Literal["regra", "modelo"] = "regra"


=== DIFF: app/contracts/quote.py ===
@@ -0,0 +1,322 @@
+"""Contratos da cotação — a fronteira entre o agente e o legado instável.
+
+Estes tipos são o **contrato congelado da Fase 0**: mais de uma frente depende deles,
+então eles vivem num pacote próprio e mudam por decisão, não por conveniência de quem
+está implementando.
+
+Duas ideias organizam este módulo:
+
+1. **Normalizar antes de chamar.** Três campos erram *sem status HTTP* na `/quote`:
+   `plano_id` vazio cota `essencial` calado, um CEP de 7 dígitos zera o agravo de 30%,
+   e `data_inicio` fora do ISO vira 400. Por isso `QuoteRequest` normaliza e valida na
+   construção — é impossível montar uma requisição malformada.
+
+2. **Classificar por corpo, não por status.** O status HTTP da `/quote` não determina
+   sozinho o que fazer nem o que dizer ao lead: o 422 carrega dois erros de naturezas
+   opostas, e dentro da recusa há casos que são bug nosso disfarçado. A classificação
+   vive em `classificar_erro()`, com uma classe para cada ação distinta.
+
+Referência medida: docs/API-COTACAO.md
+"""
+
+from __future__ import annotations
+
+import datetime as dt
+import re
+from enum import StrEnum
+from typing import Annotated, Literal
+
+from pydantic import BaseModel, ConfigDict, Field, field_validator
+
+PlanoId = Literal["essencial", "completo", "premium"]
+
+PLANOS: tuple[PlanoId, ...] = ("essencial", "completo", "premium")
+
+#: Prefixos de CEP com agravo de 1.30 (docs/API-COTACAO.md §5.3).
+#: Duplicado aqui de propósito: serve para *avisar* durante a qualificação. O valor
+#: cobrado é sempre o que a /quote devolve, nunca o que calculamos por este conjunto.
+PREFIXOS_CEP_ALTO_RISCO = frozenset({"07", "08", "21", "26", "59"})
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Entrada
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class QuoteRequest(BaseModel):
+    """Requisição já normalizada para `POST /quote`.
+
+    Construir esta classe é a única forma permitida de chamar a `/quote`. Os
+    validadores abaixo existem porque a API aceita lixo nestes campos sem devolver
+    erro — ela simplesmente cota outra coisa.
+    """
+
+    model_config = ConfigDict(frozen=True, extra="forbid")
+
+    plano_id: PlanoId
+    idade: Annotated[int, Field(ge=0, le=200)]
+    veiculo_ano: Annotated[int, Field(ge=1950, le=2100)]
+    cep: str | None = None
+    data_inicio: dt.date | None = None
+
+    @field_validator("cep", mode="before")
+    @classmethod
+    def _normalizar_cep(cls, v: object) -> str | None:
+        """8 dígitos ou nada.
+
+        `"7000-000"` (zero à esquerda perdido — erro de digitação corriqueiro) é lido
+        pela API como prefixo `"70"` e **perde o agravo de 30% em silêncio**. Um CEP
+        que não tem exatamente 8 dígitos não é um CEP: vira `None` e reperguntamos.
+        """
+        if v is None:
+            return None
+        digitos = re.sub(r"\D", "", str(v))
+        return digitos if len(digitos) == 8 else None
+
+    @property
+    def cep_alto_risco(self) -> bool:
+        return bool(self.cep) and self.cep[:2] in PREFIXOS_CEP_ALTO_RISCO
+
+    def to_api_payload(self) -> dict[str, object]:
+        """Corpo exato do `POST /quote`. `None` é omitido, nunca enviado vazio."""
+        payload: dict[str, object] = {
+            "plano_id": self.plano_id,
+            "idade": self.idade,
+            "veiculo_ano": self.veiculo_ano,
+        }
+        if self.cep:
+            payload["cep"] = self.cep
+        if self.data_inicio:
+            payload["data_inicio"] = self.data_inicio.isoformat()
+        return payload
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Saída — o corpo 200 da /quote
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class Carencia(BaseModel):
+    """Sempre presente nas respostas 200, nos três planos. Nunca omitir ao lead."""
+
+    model_config = ConfigDict(frozen=True)
+
+    coberturas: list[str]
+    dias: int
+    observacao: str
+
+
+class ProRata(BaseModel):
+    """Só existe quando enviamos `data_inicio` com dia ≠ 1."""
+
+    model_config = ConfigDict(frozen=True)
+
+    dias_no_mes: int
+    dias_cobrados: int
+    valor_primeiro_pagamento: float
+
+
+class Multiplicadores(BaseModel):
+    model_config = ConfigDict(frozen=True)
+
+    faixa_etaria: float
+    idade_veiculo: float
+    regiao: float
+
+
+class QuotePayload(BaseModel):
+    """Corpo 200 da `/quote`, validado.
+
+    É a **única** origem legítima de qualquer número que chegue ao lead. O renderer
+    determinístico lê daqui; o modelo nunca escreve preço.
+    """
+
+    model_config = ConfigDict(frozen=True, extra="allow")
+
+    plano_id: PlanoId
+    plano_nome: str
+    premio_mensal: float
+    franquia: int
+    coberturas: list[str]
+    multiplicadores: Multiplicadores
+    carencia: Carencia
+    moeda: str
+    primeiro_pagamento_pro_rata: ProRata | None = None
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# Taxonomia de erro
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class QuoteOutcome(StrEnum):
+    """Desfecho de **uma tentativa** HTTP.
+
+    Cada valor implica uma ação diferente, e é por isso que são cinco e não três.
+    """
+
+    OK = "ok"
+    #: 5xx da instabilidade simulada → retenta.
+    TRANSIENT = "transient"
+    #: nosso timeout ou erro de conexão → retenta.
+    TIMEOUT = "timeout"
+    #: 422 `cotacao_recusada` com motivo que é de fato uma recusa → o lead ouve o motivo.
+    REFUSED = "refused"
+    #: 400, 422 `detail`, ou 422 recusa que na verdade é dado nosso errado → o lead
+    #: nunca vê isto; é bug de extração.
+    BAD_REQUEST = "bad_request"
+
+    @property
+    def retentavel(self) -> bool:
+        return self in (QuoteOutcome.TRANSIENT, QuoteOutcome.TIMEOUT)
+
+
+class MotivoRecusa(StrEnum):
+    """Recusas reais, normalizadas a partir do texto do `motivo` da API.
+
+    Só estas três viram mensagem de recusa para o lead. As outras duas coisas que a
+    API chama de `cotacao_recusada` — `plano_id` inexistente e veículo com ano futuro —
+    são defeito nosso e caem em `BAD_REQUEST`: dizer a quem informou 2027 que "seu
+    veículo não é aceito" é mentir para ele.
+    """
+
+    IDADE_ACIMA = "idade_acima_do_limite"      # ≥ 76 anos
+    IDADE_ABAIXO = "idade_abaixo_do_minimo"    # < 18 anos
+    VEICULO_ANTIGO = "veiculo_acima_de_20_anos"
+
+
+class QuoteError(BaseModel):
+    """Erro classificado de uma tentativa, com o suficiente para agir e para auditar."""
+
+    model_config = ConfigDict(frozen=True)
+
+    outcome: QuoteOutcome
+    http_status: int | None = None
+    #: Motivo de recusa normalizado — preenchido apenas quando `outcome == REFUSED`.
+    motivo_recusa: MotivoRecusa | None = None
+    #: Texto cru da API, para o log e a tela de rastreabilidade. **Nunca vai ao lead**:
+    #: o texto de recusa vem de um mapa fixo nosso, não da API nem do modelo.
+    detalhe_bruto: str | None = None
+
+
+def classificar_erro(
+    http_status: int | None,
+    corpo: dict[str, object] | None,
+    *,
+    timeout: bool = False,
+) -> QuoteError:
+    """Classifica uma resposta não-200 da `/quote`.
+
+    A ordem das checagens é a ordem da precedência real do servidor
+    (docs/API-COTACAO.md §7.2).
+    """
+    if timeout or http_status is None:
+        return QuoteError(outcome=QuoteOutcome.TIMEOUT, http_status=http_status)
+
+    if http_status >= 500:
+        return QuoteError(
+            outcome=QuoteOutcome.TRANSIENT,
+            http_status=http_status,
+            detalhe_bruto=str((corpo or {}).get("message")) if corpo else None,
+        )
+
+    corpo = corpo or {}
+    erro = corpo.get("error")
+
+    # 422 do Pydantic: `{"detail": [...]}` — bug nosso, e o corpo ecoa o payload
+    # (idade, CEP do lead), então `detalhe_bruto` fica de fora aqui.
+    if http_status == 422 and "detail" in corpo:
+        return QuoteError(outcome=QuoteOutcome.BAD_REQUEST, http_status=422)
+
+    if http_status == 422 and erro == "cotacao_recusada":
+        motivo = str(corpo.get("motivo", ""))
+        normalizado = _normalizar_motivo(motivo)
+        if normalizado is None:
+            # `plano_id` inexistente ou veículo com ano futuro: vestido de recusa,
+            # mas é defeito nosso.
+            return QuoteError(
+                outcome=QuoteOutcome.BAD_REQUEST, http_status=422, detalhe_bruto=motivo
+            )
+        return QuoteError(
+            outcome=QuoteOutcome.REFUSED,
+            http_status=422,
+            motivo_recusa=normalizado,
+            detalhe_bruto=motivo,
+        )
+
+    if http_status == 400 and erro == "payload_invalido":
+        return QuoteError(
+            outcome=QuoteOutcome.BAD_REQUEST,
+            http_status=400,
+            detalhe_bruto=str(corpo.get("detalhe", "")),
+        )
+
+    # 404, 405 e qualquer forma não prevista: nossa, e não se retenta.
+    return QuoteError(outcome=QuoteOutcome.BAD_REQUEST, http_status=http_status)
+
+
+def _normalizar_motivo(motivo: str) -> MotivoRecusa | None:
+    """Texto do `motivo` → recusa real, ou `None` se for defeito nosso.
+
+    Casamento por trecho estável do texto da API. Um `motivo` desconhecido devolve
+    `None` de propósito: na dúvida, não afirmamos ao lead que ele foi recusado.
+    """
+    m = motivo.lower()
+    if "acima do limite de aceitacao" in m:
+        return MotivoRecusa.IDADE_ACIMA
+    if "idade fora das faixas" in m:
+        return MotivoRecusa.IDADE_ABAIXO
+    if "mais de 20 anos" in m:
+        return MotivoRecusa.VEICULO_ANTIGO
+    return None
+
+
+# ─────────────────────────────────────────────────────────────────────────────
+# A cotação como job
+# ─────────────────────────────────────────────────────────────────────────────
+
+
+class QuoteJobStatus(StrEnum):
+    """O pior caso da política de retry (~40s) não cabe num turno de conversa.
+
+    Por isso a cotação é um job com estado: o agente fala antes de ter o preço e o
+    valor chega depois, como mensagem nova.
+    """
+
+    PENDING = "pending"
+    OK = "ok"
+    REFUSED = "refused"
+    FAILED = "failed"
+
+
+class QuoteAttempt(BaseModel):
+    """Uma tentativa HTTP. É a linha de `quote_attempts` — a prova de rastreabilidade."""
+
+    model_config = ConfigDict(frozen=True)
+
+    attempt: Annotated[int, Field(ge=1)]
+    http_status: int | None
+    latency_ms: int
+    outcome: QuoteOutcome
+    error: QuoteError | None = None
+
+
+class QuoteResult(BaseModel):
+    """Resultado consolidado de um job de cotação, com todas as tentativas.
+
+    Invariante: `payload is not None` **se e somente se** `status == OK`. É o que
+    sustenta o guardrail "nenhum valor no texto sem `quote_id` com status `ok`".
+    """
+
+    model_config = ConfigDict(frozen=True)
+
+    quote_id: str
+    status: QuoteJobStatus
+    request: QuoteRequest
+    payload: QuotePayload | None = None
+    error: QuoteError | None = None
+    attempts: list[QuoteAttempt] = Field(default_factory=list)
+    total_latency_ms: int = 0
+    #: Verdadeiro quando o breaker impediu a chamada — o desfecho é `FAILED` sem
+    #: nenhuma tentativa registrada, e a tela de status precisa distinguir isso.
+    circuito_aberto: bool = False


=== DIFF: config/model_pricing.yaml ===
@@ -0,0 +1,66 @@
+# Tabela de preço por modelo — insumo de `turn_usage.cost_usd`.
+#
+# Por que este arquivo existe e o preço não está embutido no código:
+#
+#   1. Preço muda, e código com número mágico envelhece em silêncio. Aqui a mudança
+#      é uma linha nova com outra vigência, e o custo histórico continua auditável
+#      porque `turn_usage.pricing_vigencia` grava qual entrada foi usada.
+#   2. O Agno **não** preenche o campo `cost` para a Anthropic — a tabela de
+#      disponibilidade por provider da documentação oficial mostra `cost` populado
+#      apenas para OpenAI Chat e Meta Llama (OpenAI). Calcular do nosso lado não é
+#      preferência de design, é a única opção.
+#
+# ⚠️ Estes valores foram consultados em 2026-09-04 a partir de um snapshot de
+#    2026-06-24. Preço de API muda sem aviso. Antes de usar este número para
+#    qualquer decisão real, reconfirme em https://www.anthropic.com/pricing e
+#    acrescente uma entrada nova com a vigência da consulta — não edite as antigas.
+
+moeda: USD
+unidade: por 1.000.000 de tokens
+
+fonte:
+  url: https://www.anthropic.com/pricing
+  consultado_em: 2026-09-04
+  snapshot_em: 2026-06-24
+
+# Multiplicadores de cache da Anthropic, aplicados sobre o preço de entrada:
+#   leitura de cache  ≈ 0,10 ×  (é daí que vem a economia)
+#   escrita de cache  ≈ 1,25 ×  (TTL padrão de 5 min; TTL de 1 h custa ≈ 2,00 ×)
+# Os valores abaixo já estão expandidos para não deixar a conta implícita.
+
+modelos:
+
+  - id: anthropic:claude-opus-5
+    provider: anthropic
+    vigencia_a_partir_de: 2026-06-24
+    input: 5.00
+    output: 25.00
+    cache_read: 0.50    # 0,10 × input
+    cache_write: 6.25   # 1,25 × input, TTL de 5 min
+
+  - id: anthropic:claude-sonnet-5
+    provider: anthropic
+    vigencia_a_partir_de: 2026-06-24
+    input: 2.00
+    output: 10.00
+    cache_read: 0.20
+    cache_write: 2.50
+
+  - id: anthropic:claude-haiku-4-5
+    provider: anthropic
+    vigencia_a_partir_de: 2026-06-24
+    input: 1.00
+    output: 5.00
+    cache_read: 0.10
+    cache_write: 1.25
+
+  # Inferência local não tem preço por token. O custo existe — hardware e energia —
+  # mas não é atribuível por turno, e fingir que é daria um número falso.
+  # `cost_usd` fica NULL para estes turnos, e o painel mostra "n/a", não "R$ 0,00".
+  - id: ollama:*
+    provider: ollama
+    vigencia_a_partir_de: 2026-06-24
+    input: null
+    output: null
+    cache_read: null    # o Ollama não reporta cache; ver db/migrations/0002
+    cache_write: null


=== DIFF: db/migrations/0001_inicial.sql ===
@@ -0,0 +1,255 @@
+-- 0001_inicial.sql — modelo de dados da AutoSeguro
+--
+-- O critério declarado é literal: "dá pra rastrear o que aconteceu? (cada mensagem /
+-- cotação, com id e status)". Este esquema é a resposta a ele, e é desenhado para
+-- responder a quatro perguntas do operador sem consultar log nenhum:
+--
+--   1. o que foi dito nesta conversa, em que ordem, e o que saiu de fato?  → messages
+--   2. quantas vezes tentamos cotar, com que status e em quanto tempo?     → quote_attempts
+--   3. qual foi o número apresentado ao lead, e de onde ele veio?          → quotes
+--   4. por que esta conversa foi para um humano, e por qual regra?         → handoffs
+--
+-- Invariante central: nenhuma mensagem com valor monetário existe sem uma linha em
+-- `quotes` com status `ok`. É o guardrail "o preço nunca vem do modelo", auditável em SQL.
+--
+-- PII: nenhuma coluna aqui guarda texto cru do lead. `messages.conteudo` é a versão
+-- mascarada, que é também a versão exibida na UI — a tela mostra o comportamento
+-- correto, não uma versão especial para screenshot.
+
+BEGIN;
+
+-- ─────────────────────────────────────────────────────────────────────────────
+-- Tipos
+-- ─────────────────────────────────────────────────────────────────────────────
+
+CREATE TYPE conversation_state AS ENUM (
+    'novo', 'qualificando', 'cotando', 'cotado', 'fechado', 'encaminhado'
+);
+
+CREATE TYPE message_autor AS ENUM ('lead', 'agente', 'sistema', 'operador');
+
+CREATE TYPE message_status AS ENUM (
+    'received', 'pending', 'sent', 'failed', 'discarded'
+);
+
+CREATE TYPE message_tipo AS ENUM ('text', 'image', 'audio', 'document');
+
+-- Desfecho de UMA tentativa HTTP. Cinco valores porque cada um implica ação distinta
+-- (docs/API-COTACAO.md §7): os dois primeiros retentam, os três últimos nunca.
+CREATE TYPE quote_outcome AS ENUM (
+    'transient',    -- 500/502/503 da instabilidade simulada
+    'timeout',      -- nosso timeout de leitura, ou erro de conexão
+    'ok',
+    'refused',      -- 422 cotacao_recusada com motivo que é recusa de verdade
+    'bad_request'   -- 400, 422 detail, ou 422 "recusa" que é dado nosso errado
+);
+
+CREATE TYPE quote_job_status AS ENUM ('pending', 'ok', 'refused', 'failed');
+
+CREATE TYPE handoff_status AS ENUM ('pendente', 'assumido', 'resolvido');
+
+-- ─────────────────────────────────────────────────────────────────────────────
+-- conversations
+-- ─────────────────────────────────────────────────────────────────────────────
+
+CREATE TABLE conversations (
+    id              TEXT PRIMARY KEY,
+    channel         TEXT NOT NULL,          -- 'console' | 'web'
+    -- Identificador do lead no canal. Nunca é telefone real: no console é o nome da
+    -- sessão, no web o id do socket. Repositório público.
+    external_ref    TEXT NOT NULL,
+    state           conversation_state NOT NULL DEFAULT 'novo',
+
+    -- Perfil de qualificação, desnormalizado de propósito: são cinco campos, sempre
+    -- lidos juntos, e uma tabela à parte só adicionaria um join a toda leitura.
+    idade           SMALLINT CHECK (idade BETWEEN 0 AND 200),
+    veiculo_ano     SMALLINT CHECK (veiculo_ano BETWEEN 1950 AND 2100),
+    cep             CHAR(8)  CHECK (cep ~ '^[0-9]{8}$'),  -- 8 dígitos: ver §5.3
+    data_inicio     DATE,
+    plano_id        TEXT     CHECK (plano_id IN ('essencial','completo','premium')),
+
+    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
+    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now(),
+
+    UNIQUE (channel, external_ref)
+);
+
+CREATE INDEX conversations_state_idx ON conversations (state, atualizado_em DESC);
+
+-- ─────────────────────────────────────────────────────────────────────────────
+-- messages — "cada mensagem, com id e status"
+-- ─────────────────────────────────────────────────────────────────────────────
+
+CREATE TABLE messages (
+    id              TEXT PRIMARY KEY,
+    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
+
+    -- Ordem canônica. É por ela que se ordena e se pagina, NUNCA por timestamp:
+    -- no dataset do desafio 99,8% das conversas têm timestamp fora de ordem, e a
+    -- lição vale para o nosso lado — relógio não é ordem.
+    index           INTEGER NOT NULL CHECK (index >= 0),
+
+    autor           message_autor NOT NULL,
+    tipo            message_tipo NOT NULL DEFAULT 'text',
+
+    -- SEMPRE mascarado. É a coluna exibida na UI e no transcript entregue.
+    conteudo        TEXT NOT NULL,
+
+    status          message_status NOT NULL,
+
+    -- Id atribuído pelo canal. Deduplicação de entrada: o mesmo external_id entregue
+    -- duas vezes produz uma linha só.
+    external_id     TEXT,
+
+    -- O guardrail, materializado: uma mensagem que apresenta preço aponta para a
+    -- cotação que o produziu. FK adiada porque `quotes` é criada depois.
+    quote_id        TEXT,
+
+    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
+
+    UNIQUE (conversation_id, index)
+);
+
+CREATE UNIQUE INDEX messages_external_id_uidx
+    ON messages (conversation_id, external_id)
+    WHERE external_id IS NOT NULL;
+
+CREATE INDEX messages_conversation_idx ON messages (conversation_id, index);
+
+-- ─────────────────────────────────────────────────────────────────────────────
+-- quotes — o job de cotação
+-- ─────────────────────────────────────────────────────────────────────────────
+
+CREATE TABLE quotes (
+    id              TEXT PRIMARY KEY,
+    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
+    status          quote_job_status NOT NULL DEFAULT 'pending',
+
+    -- Requisição EXATA enviada, já normalizada. Guardada para que uma cotação seja
+    -- reproduzível anos depois, mesmo que o perfil da conversa mude.
+    req_plano_id    TEXT NOT NULL,
+    req_idade       SMALLINT NOT NULL,
+    req_veiculo_ano SMALLINT NOT NULL,
+    req_cep         CHAR(8),
+    req_data_inicio DATE,
+
+    -- Resultado. Preenchidos se e somente se status = 'ok' (CHECK abaixo).
+    premio_mensal   NUMERIC(10,2),
+    franquia        INTEGER,
+    carencia_dias   SMALLINT,
+    -- NULL quando a data de início cai no dia 1 — ausência é informação, e a
+    -- mensagem ao lead precisa dizer "o primeiro mês já é integral".
+    pro_rata_valor  NUMERIC(10,2),
+    pro_rata_dias   SMALLINT,
+    -- Corpo 200 completo, para auditoria e para o renderer. Sem PII: a /quote não
+    -- devolve nada do lead além dos multiplicadores.
+    payload         JSONB,
+
+    -- Preenchidos quando status <> 'ok'.
+    motivo_recusa   TEXT,     -- normalizado: idade_acima_do_limite | ... | NULL
+    erro_outcome    quote_outcome,
+    circuito_aberto BOOLEAN NOT NULL DEFAULT FALSE,
+
+    total_latency_ms INTEGER,
+    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
+    finalizado_em   TIMESTAMPTZ,
+
+    -- O invariante do guardrail, imposto pelo banco e não pela boa vontade do código:
+    -- só existe prêmio quando o job deu certo, e nunca existe job 'ok' sem prêmio.
+    CONSTRAINT quotes_premio_sse_ok CHECK (
+        (status = 'ok'  AND premio_mensal IS NOT NULL AND payload IS NOT NULL)
+        OR
+        (status <> 'ok' AND premio_mensal IS NULL)
+    ),
+    -- Recusa tem motivo; o que não é recusa não tem.
+    CONSTRAINT quotes_motivo_sse_refused CHECK (
+        (status = 'refused' AND motivo_recusa IS NOT NULL)
+        OR
+        (status <> 'refused' AND motivo_recusa IS NULL)
+    )
+);
+
+CREATE INDEX quotes_conversation_idx ON quotes (conversation_id, criado_em DESC);
+CREATE INDEX quotes_status_idx ON quotes (status, criado_em DESC);
+
+ALTER TABLE messages
+    ADD CONSTRAINT messages_quote_fk
+    FOREIGN KEY (quote_id) REFERENCES quotes (id) ON DELETE SET NULL;
+
+-- ─────────────────────────────────────────────────────────────────────────────
+-- quote_attempts — uma linha por tentativa HTTP
+-- ─────────────────────────────────────────────────────────────────────────────
+--
+-- Esta tabela é a evidência de C2. Ela é o que permite responder, sem log:
+-- "tentamos 3 vezes, a 1ª deu 503 em 40ms, a 2ª estourou o timeout aos 12s, a 3ª
+-- voltou 200 aos 8,01s" — e é a origem da linha do tempo em /admin/conversas e das
+-- métricas de p50/p95 e do estado do breaker em /admin/status.
+
+CREATE TABLE quote_attempts (
+    id              TEXT PRIMARY KEY,
+    quote_id        TEXT NOT NULL REFERENCES quotes (id) ON DELETE CASCADE,
+    attempt         SMALLINT NOT NULL CHECK (attempt >= 1),
+
+    -- NULL quando não houve resposta: timeout de leitura ou erro de conexão.
+    http_status     SMALLINT,
+    latency_ms      INTEGER NOT NULL,
+    outcome         quote_outcome NOT NULL,
+
+    -- Texto cru devolvido pela API, para diagnóstico. NUNCA é exibido ao lead.
+    -- O corpo do 422 do Pydantic ecoa o payload enviado (idade, CEP), então este
+    -- campo passa pelo mascaramento antes de gravar, como qualquer outro texto.
+    detalhe         TEXT,
+
+    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
+
+    UNIQUE (quote_id, attempt),
+    -- Sem resposta é timeout, e timeout não tem status. Impede a linha incoerente
+    -- que faria a tela de status mentir.
+    CONSTRAINT attempts_timeout_sem_status CHECK (
+        (outcome = 'timeout' AND http_status IS NULL)
+        OR
+        (outcome <> 'timeout' AND http_status IS NOT NULL)
+    )
+);
+
+CREATE INDEX quote_attempts_recentes_idx ON quote_attempts (criado_em DESC);
+
+-- ─────────────────────────────────────────────────────────────────────────────
+-- handoffs — a fila operável
+-- ─────────────────────────────────────────────────────────────────────────────
+
+CREATE TABLE handoffs (
+    id              TEXT PRIMARY KEY,
+    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
+
+    -- Qual REGRA disparou. É o que torna o critério "explícito e defensável":
+    -- a fila mostra o gatilho, não uma frase gerada. O conjunto de valores é fechado
+    -- pela decisão aberta nº1 e vira CHECK quando ela fechar.
+    trigger         TEXT NOT NULL,
+    -- Motivo legível para o operador. Nunca é o texto cru da API nem do lead.
+    reason          TEXT NOT NULL,
+    summary         TEXT,
+
+    -- 'regra' | 'modelo' — um gatilho determinístico (breaker aberto, 422 de recusa)
+    -- e uma decisão do modelo produzem o mesmo sinal, e a fila distingue os dois.
+    disparado_por   TEXT NOT NULL DEFAULT 'regra'
+                    CHECK (disparado_por IN ('regra','modelo')),
+
+    -- Última cotação tentada. É o que o operador precisa ver primeiro ao assumir.
+    quote_id        TEXT REFERENCES quotes (id) ON DELETE SET NULL,
+
+    status          handoff_status NOT NULL DEFAULT 'pendente',
+    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
+    assumido_em     TIMESTAMPTZ,
+    resolved_at     TIMESTAMPTZ,
+
+    CONSTRAINT handoffs_resolvido_tem_data CHECK (
+        (status = 'resolvido') = (resolved_at IS NOT NULL)
+    )
+);
+
+-- Sustenta o badge de pendentes visível de qualquer tela.
+CREATE INDEX handoffs_pendentes_idx ON handoffs (status, criado_em DESC);
+CREATE INDEX handoffs_conversation_idx ON handoffs (conversation_id);
+
+COMMIT;


=== DIFF: db/migrations/0002_turn_usage.sql ===
@@ -0,0 +1,73 @@
+-- 0002_turn_usage.sql — custo e uso de tokens por turno
+--
+-- Substitui o Langfuse (ver docs/DECISOES-FECHADAS.md §5). Sustenta duas coisas que
+-- de outra forma seriam alegação em vez de evidência:
+--
+--   1. **O prompt caching funciona.** `cache_read` maior que zero a partir do segundo
+--      turno é a prova. Sem número, "usamos prompt caching" é uma frase no README.
+--   2. **Quanto custa uma conversa.** Custo por conversa, acumulado, taxa de acerto de
+--      cache, Anthropic e Ollama lado a lado — no admin, para quem rodar a aplicação.
+--
+-- Granularidade: um turno = uma execução do agente = um `RunOutput` do Agno, cujo
+-- `metrics` é um `RunMetrics`. Não é por chamada de API ao modelo (isso seria
+-- `MessageMetrics`): um turno com tool call faz várias chamadas, e o que interessa
+-- aqui é o custo do turno.
+--
+-- Por que `cost_usd` é calculado por nós e não lido do Agno: a tabela de
+-- disponibilidade por provider da documentação do Agno mostra que a Anthropic **não
+-- popula** o campo `cost` de `BaseMetrics`. Calcular do nosso lado não é preferência,
+-- é a única opção — e traz o benefício de o preço ficar auditável.
+
+BEGIN;
+
+CREATE TABLE turn_usage (
+    id              TEXT PRIMARY KEY,
+
+    -- O turno é identificado pela mensagem do agente que ele produziu.
+    message_id      TEXT NOT NULL REFERENCES messages (id) ON DELETE CASCADE,
+    -- Desnormalizado: o painel agrega por conversa, e este é o join que ele evitaria
+    -- fazer em toda linha.
+    conversation_id TEXT NOT NULL REFERENCES conversations (id) ON DELETE CASCADE,
+
+    -- Model-string do Agno, como configurada: "anthropic:claude-sonnet-4-5-[CEP]",
+    -- "ollama:qwen2.5:7b". Guardada inteira porque é ela que identifica o preço.
+    model           TEXT NOT NULL,
+    -- Derivado do prefixo, para o painel comparar providers sem parsear string em SQL.
+    provider        TEXT NOT NULL,
+
+    tokens_in       INTEGER NOT NULL DEFAULT 0,
+    tokens_out      INTEGER NOT NULL DEFAULT 0,
+
+    -- NULL, e não 0, quando o provider não reporta caching. O Ollama não popula estes
+    -- campos, e um zero ali mentiria: diria "o cache não acertou" onde a verdade é
+    -- "não existe cache neste caminho". A taxa de acerto do painel ignora os NULL.
+    cache_read      INTEGER,
+    cache_write     INTEGER,
+
+    latency_ms      INTEGER NOT NULL,
+
+    -- Calculado por nós a partir de config/model_pricing.yaml.
+    cost_usd        NUMERIC(12,6),
+    -- Data de vigência da entrada de preço usada. Sem isto, um custo histórico deixa
+    -- de ser auditável assim que a tabela de preços muda — e ela muda.
+    pricing_vigencia DATE,
+
+    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
+
+    -- Um turno por mensagem do agente.
+    UNIQUE (message_id),
+    CONSTRAINT turn_usage_tokens_nao_negativos CHECK (
+        tokens_in >= 0 AND tokens_out >= 0
+        AND (cache_read IS NULL OR cache_read >= 0)
+        AND (cache_write IS NULL OR cache_write >= 0)
+    ),
+    -- Custo sem vigência é um número sem procedência.
+    CONSTRAINT turn_usage_custo_tem_vigencia CHECK (
+        (cost_usd IS NULL) = (pricing_vigencia IS NULL)
+    )
+);
+
+CREATE INDEX turn_usage_conversation_idx ON turn_usage (conversation_id, criado_em);
+CREATE INDEX turn_usage_provider_idx ON turn_usage (provider, criado_em DESC);
+
+COMMIT;


=== DIFF: docs/openapi.yaml ===
@@ -0,0 +1,633 @@
+openapi: 3.1.0
+
+info:
+  title: AutoSeguro — backend do agente
+  version: "0.1.0"
+  description: |
+    Contrato congelado na Fase 0. O frontend é construído contra este documento, não
+    contra a implementação — é o que permite que a frente de UI e a de backend rodem
+    sem se pisarem.
+
+    **Como ler.** São quatro superfícies, uma por tela, e elas se ligam por id:
+
+    | Superfície | Tela | Critério |
+    |---|---|---|
+    | conversa (WS `/api/chat`) | `/chat` | E1 · C2 |
+    | histórico (`/api/conversations`) | `/admin/conversas` | C4 |
+    | saúde da `/quote` (`/api/quote-health`) | `/admin/status` | C2 · C4 |
+    | fila de handoff (`/api/handoffs`) | `/admin/handoffs` | C3 · C4 |
+
+    De um handoff se salta para a conversa que o gerou; de uma tentativa falha se
+    entende o estado do breaker. É a navegação que demonstra rastreabilidade.
+
+    **Duas invariantes atravessam o documento:**
+
+    1. Toda mensagem que apresenta um valor monetário tem `quote_id` não-nulo,
+       apontando para uma cotação com `status: ok`. Uma mensagem com preço e
+       `quote_id: null` é bug, e a UI a marca como tal.
+    2. Todo texto que sai daqui já passou pelo mascaramento de PII. Não existe
+       endpoint que devolva a versão crua — inclusive porque a tela precisa mostrar
+       o comportamento correto, não uma versão especial para screenshot.
+
+    Autenticação não faz parte do escopo: o backend só é exposto em rede local pelo
+    `docker compose`. Ver `docs/ARQUITETURA.md` para o que isso implica se for ao ar.
+
+servers:
+  - url: http://localhost:8080
+    description: backend local (docker compose)
+
+tags:
+  - name: chat
+    description: o canal do lead — adaptador `web` da porta ChannelAdapter
+  - name: rastreabilidade
+    description: conversas, mensagens e tentativas de cotação
+  - name: operacao
+    description: saúde da /quote e fila de handoff
+
+paths:
+
+  /api/health:
+    get:
+      tags: [operacao]
+      summary: Saúde do backend
+      description: |
+        Saúde **deste** serviço. Deliberadamente não reflete a saúde da `/quote`: o
+        `/health` do legado responde 200 mesmo com 100% das cotações falhando, e
+        confundir os dois é como se produz um monitor que mente. Para a saúde real da
+        cotação, use `/api/quote-health`.
+      responses:
+        "200":
+          description: ok
+          content:
+            application/json:
+              schema:
+                type: object
+                required: [status, db]
+                properties:
+                  status: { type: string, enum: [ok] }
+                  db: { type: string, enum: [ok, degraded] }
+
+  /api/conversations:
+    post:
+      tags: [chat]
+      summary: Abre uma conversa
+      description: Chamado pela tela `/chat` antes de conectar o WebSocket.
+      requestBody:
+        required: true
+        content:
+          application/json:
+            schema:
+              type: object
+              required: [channel]
+              properties:
+                channel: { type: string, enum: [console, web] }
+                external_ref:
+                  type: string
+                  description: |
+                    Identificador do lead no canal. Nunca um telefone real — no console
+                    é o nome da sessão, no web o id do socket. Repositório público.
+      responses:
+        "201":
+          description: criada
+          content:
+            application/json:
+              schema: { $ref: "#/components/schemas/Conversation" }
+
+    get:
+      tags: [rastreabilidade]
+      summary: Lista conversas
+      parameters:
+        - { name: state, in: query, schema: { $ref: "#/components/schemas/ConversationState" } }
+        - { name: limit, in: query, schema: { type: integer, default: 50, maximum: 200 } }
+        - { name: cursor, in: query, schema: { type: string } }
+      responses:
+        "200":
+          description: página de conversas
+          content:
+            application/json:
+              schema:
+                type: object
+                required: [items]
+                properties:
+                  items:
+                    type: array
+                    items: { $ref: "#/components/schemas/ConversationSummary" }
+                  next_cursor: { type: [string, "null"] }
+
+  /api/conversations/{conversation_id}:
+    get:
+      tags: [rastreabilidade]
+      summary: Detalhe da conversa — mensagens e linha do tempo das cotações
+      description: |
+        É a resposta ao critério C4 numa chamada só: cada mensagem com id e status, e
+        cada cotação com todas as suas tentativas (`attempt`, `http_status`,
+        `latency_ms`, `outcome`).
+
+        `messages` vem ordenado por `index`, **nunca por timestamp**.
+      parameters:
+        - { name: conversation_id, in: path, required: true, schema: { type: string } }
+      responses:
+        "200":
+          description: conversa completa
+          content:
+            application/json:
+              schema: { $ref: "#/components/schemas/ConversationDetail" }
+        "404": { $ref: "#/components/responses/NaoEncontrado" }
+
+  /api/quote-health:
+    get:
+      tags: [operacao]
+      summary: Saúde real da /quote
+      description: |
+        Alimenta `/admin/status`. Mostra mais que verde/vermelho, porque verde/vermelho
+        não prova que a instabilidade foi tratada:
+
+        - `upstream_health`: o `/health` do legado — que sempre diz ok;
+        - `janela`: taxa de sucesso e latências das últimas N tentativas **reais**;
+        - `breaker`: fechado / aberto / meia-abertura, com quando reabre;
+        - `ultimas_tentativas`: as N últimas, com desfecho e a conversa de origem.
+
+        `p95` inclui as chamadas lentas de 8s — é justamente o que se quer ver.
+      parameters:
+        - { name: janela, in: query, schema: { type: integer, default: 50, maximum: 500 } }
+      responses:
+        "200":
+          description: estado da integração
+          content:
+            application/json:
+              schema: { $ref: "#/components/schemas/QuoteHealth" }
+
+  /api/usage:
+    get:
+      tags: [operacao]
+      summary: Custo e uso de tokens
+      description: |
+        Alimenta o painel de custo do admin, a partir da tabela `turn_usage`.
+
+        Substitui o Langfuse (`docs/DECISOES-FECHADAS.md` §5): a informação fica na
+        própria base da aplicação, disponível para quem rodar `docker compose up`, em
+        vez de exigir seis containers e ~5,6 GB de imagens para ser conferida.
+
+        Prova duas coisas com número, não com frase: que o prompt caching funciona
+        (`cache_read` > 0 a partir do segundo turno) e quanto custa uma conversa.
+      parameters:
+        - { name: conversation_id, in: query, schema: { type: string } }
+        - { name: limit, in: query, schema: { type: integer, default: 50, maximum: 200 } }
+      responses:
+        "200":
+          description: uso agregado e por conversa
+          content:
+            application/json:
+              schema: { $ref: "#/components/schemas/Usage" }
+
+  /api/handoffs:
+    get:
+      tags: [operacao]
+      summary: Fila de handoff
+      parameters:
+        - { name: status, in: query, schema: { $ref: "#/components/schemas/HandoffStatus" } }
+        - { name: limit, in: query, schema: { type: integer, default: 50, maximum: 200 } }
+      responses:
+        "200":
+          description: fila
+          content:
+            application/json:
+              schema:
+                type: object
+                required: [items, pendentes]
+                properties:
+                  items:
+                    type: array
+                    items: { $ref: "#/components/schemas/Handoff" }
+                  pendentes:
+                    type: integer
+                    description: Alimenta o badge visível de qualquer tela.
+
+  /api/handoffs/{handoff_id}:
+    patch:
+      tags: [operacao]
+      summary: Assume ou resolve um handoff
+      description: |
+        Sem isto a fila não é operável — é só uma lista que cresce. As transições
+        válidas são `pendente → assumido → resolvido` e `pendente → resolvido`.
+      parameters:
+        - { name: handoff_id, in: path, required: true, schema: { type: string } }
+      requestBody:
+        required: true
+        content:
+          application/json:
+            schema:
+              type: object
+              required: [status]
+              properties:
+                status: { $ref: "#/components/schemas/HandoffStatus" }
+      responses:
+        "200":
+          description: atualizado
+          content:
+            application/json:
+              schema: { $ref: "#/components/schemas/Handoff" }
+        "404": { $ref: "#/components/responses/NaoEncontrado" }
+        "409":
+          description: transição de estado inválida
+          content:
+            application/json:
+              schema: { $ref: "#/components/schemas/Erro" }
+
+  /api/chat/{conversation_id}:
+    get:
+      tags: [chat]
+      summary: "WebSocket: o canal do lead"
+      description: |
+        **Upgrade para WebSocket.** É a implementação `web` da porta `ChannelAdapter`,
+        e é onde a degradação da `/quote` fica visível: quando a cotação demora, o
+        servidor emite `typing` e o aviso de espera, e o valor chega depois como
+        `message` nova — não como um texto que apareceu por mágica no lugar do "…".
+
+        Cliente → servidor: `{"type":"message","text":"..."}`
+        Servidor → cliente: `MessageEvent` | `TypingEvent` | `StateEvent`
+
+        Um `MessageEvent` com valor monetário sempre traz `quote_id`.
+      parameters:
+        - { name: conversation_id, in: path, required: true, schema: { type: string } }
+      responses:
+        "101": { description: protocolos trocados }
+        "404": { $ref: "#/components/responses/NaoEncontrado" }
+
+  /api/events:
+    get:
+      tags: [operacao]
+      summary: "WebSocket: push para o admin"
+      description: |
+        Empurra `handoff.created`, `handoff.updated` e `quote.attempt` para as telas de
+        administração. É o que faz um handoff criado no backend aparecer na fila **sem
+        recarregar a página** — comportamento que a evidência de UI precisa provar.
+      responses:
+        "101": { description: protocolos trocados }
+
+components:
+
+  responses:
+    NaoEncontrado:
+      description: não encontrado
+      content:
+        application/json:
+          schema: { $ref: "#/components/schemas/Erro" }
+
+  schemas:
+
+    Erro:
+      type: object
+      required: [error, message]
+      properties:
+        error: { type: string }
+        message: { type: string }
+
+    ConversationState:
+      type: string
+      enum: [novo, qualificando, cotando, cotado, fechado, encaminhado]
+      description: |
+        `encaminhado` é alcançável de qualquer estado — é a saída de todos os gatilhos
+        de handoff.
+
+    MessageStatus:
+      type: string
+      enum: [received, pending, sent, failed, discarded]
+
+    QuoteOutcome:
+      type: string
+      enum: [ok, transient, timeout, refused, bad_request]
+      description: |
+        Desfecho de **uma tentativa** HTTP. Cinco valores porque cada um implica uma
+        ação distinta: `transient` e `timeout` retentam; `refused` é um "não" do
+        negócio que o lead ouve com o motivo; `bad_request` é defeito nosso, que o
+        lead nunca vê. Ver `docs/API-COTACAO.md` §7.
+
+    QuoteJobStatus:
+      type: string
+      enum: [pending, ok, refused, failed]
+
+    HandoffStatus:
+      type: string
+      enum: [pendente, assumido, resolvido]
+
+    Conversation:
+      type: object
+      required: [id, channel, state, criado_em]
+      properties:
+        id: { type: string }
+        channel: { type: string, enum: [console, web] }
+        state: { $ref: "#/components/schemas/ConversationState" }
+        criado_em: { type: string, format: date-time }
+
+    LeadProfile:
+      type: object
+      description: |
+        Os cinco campos da qualificação. Todos anuláveis porque a conversa é
+        incremental; `campos_faltantes` é o que a UI mostra como progresso.
+      properties:
+        idade: { type: [integer, "null"] }
+        veiculo_ano: { type: [integer, "null"] }
+        cep:
+          type: [string, "null"]
+          description: 8 dígitos, sem máscara. Mascarado na exibição.
+        data_inicio: { type: [string, "null"], format: date }
+        plano_id: { type: [string, "null"], enum: [essencial, completo, premium, null] }
+        campos_faltantes:
+          type: array
+          items: { type: string }
+
+    ConversationSummary:
+      allOf:
+        - $ref: "#/components/schemas/Conversation"
+        - type: object
+          required: [total_mensagens, atualizado_em]
+          properties:
+            total_mensagens: { type: integer }
+            atualizado_em: { type: string, format: date-time }
+            ultima_mensagem: { type: [string, "null"] }
+            handoff_pendente: { type: boolean }
+            ultima_cotacao_status:
+              oneOf:
+                - $ref: "#/components/schemas/QuoteJobStatus"
+                - type: "null"
+
+    ConversationDetail:
+      allOf:
+        - $ref: "#/components/schemas/Conversation"
+        - type: object
+          required: [perfil, messages, quotes, handoffs]
+          properties:
+            perfil: { $ref: "#/components/schemas/LeadProfile" }
+            messages:
+              type: array
+              description: Ordenado por `index`. Nunca por timestamp.
+              items: { $ref: "#/components/schemas/Message" }
+            quotes:
+              type: array
+              items: { $ref: "#/components/schemas/Quote" }
+            handoffs:
+              type: array
+              items: { $ref: "#/components/schemas/Handoff" }
+
+    Message:
+      type: object
+      required: [id, index, autor, tipo, conteudo, status, criado_em]
+      properties:
+        id: { type: string }
+        index: { type: integer, minimum: 0 }
+        autor: { type: string, enum: [lead, agente, sistema, operador] }
+        tipo: { type: string, enum: [text, image, audio, document] }
+        conteudo:
+          type: string
+          description: Sempre a versão **mascarada**. Não existe endpoint com a crua.
+        status: { $ref: "#/components/schemas/MessageStatus" }
+        quote_id:
+          type: [string, "null"]
+          description: |
+            Não-nulo quando a mensagem apresenta uma cotação. É o guardrail auditável:
+            texto com valor monetário e `quote_id` nulo é bug.
+        criado_em: { type: string, format: date-time }
+
+    Quote:
+      type: object
+      required: [id, status, request, attempts, criado_em]
+      properties:
+        id: { type: string }
+        status: { $ref: "#/components/schemas/QuoteJobStatus" }
+        request:
+          type: object
+          description: A requisição exata enviada, já normalizada.
+          required: [plano_id, idade, veiculo_ano]
+          properties:
+            plano_id: { type: string, enum: [essencial, completo, premium] }
+            idade: { type: integer }
+            veiculo_ano: { type: integer }
+            cep: { type: [string, "null"] }
+            data_inicio: { type: [string, "null"], format: date }
+        resultado:
+          description: Presente **se e somente se** `status = ok`.
+          oneOf:
+            - $ref: "#/components/schemas/QuoteResultado"
+            - type: "null"
+        motivo_recusa:
+          type: [string, "null"]
+          enum: [idade_acima_do_limite, idade_abaixo_do_minimo, veiculo_acima_de_20_anos, null]
+          description: Presente se e somente se `status = refused`.
+        erro_outcome:
+          oneOf:
+            - $ref: "#/components/schemas/QuoteOutcome"
+            - type: "null"
+        circuito_aberto:
+          type: boolean
+          description: |
+            O breaker impediu a chamada. O job é `failed` **sem nenhuma tentativa** —
+            e a tela precisa distinguir isso de "tentamos 3 vezes e falhou".
+        total_latency_ms: { type: [integer, "null"] }
+        attempts:
+          type: array
+          items: { $ref: "#/components/schemas/QuoteAttempt" }
+        criado_em: { type: string, format: date-time }
+
+    QuoteResultado:
+      type: object
+      required: [premio_mensal, franquia, moeda, coberturas, carencia]
+      properties:
+        premio_mensal: { type: number }
+        franquia: { type: integer }
+        moeda: { type: string }
+        coberturas: { type: array, items: { type: string } }
+        carencia:
+          type: object
+          description: Vem em 100% das respostas 200. Nunca omitida ao lead.
+          required: [coberturas, dias]
+          properties:
+            coberturas: { type: array, items: { type: string } }
+            dias: { type: integer }
+        pro_rata:
+          description: |
+            Nulo quando a vigência começa no dia 1 — e a ausência é informação: a
+            mensagem diz que o primeiro mês já é integral, não silencia.
+          oneOf:
+            - type: object
+              required: [dias_no_mes, dias_cobrados, valor_primeiro_pagamento]
+              properties:
+                dias_no_mes: { type: integer }
+                dias_cobrados: { type: integer }
+                valor_primeiro_pagamento: { type: number }
+            - type: "null"
+
+    QuoteAttempt:
+      type: object
+      required: [id, attempt, latency_ms, outcome, criado_em]
+      properties:
+        id: { type: string }
+        attempt: { type: integer, minimum: 1 }
+        http_status:
+          type: [integer, "null"]
+          description: Nulo quando não houve resposta (timeout ou erro de conexão).
+        latency_ms: { type: integer }
+        outcome: { $ref: "#/components/schemas/QuoteOutcome" }
+        criado_em: { type: string, format: date-time }
+
+    QuoteHealth:
+      type: object
+      required: [upstream_health, janela, breaker, ultimas_tentativas]
+      properties:
+        upstream_health:
+          type: object
+          required: [status]
+          properties:
+            status: { type: string, enum: [ok, unreachable] }
+            latency_ms: { type: [integer, "null"] }
+            nota:
+              type: string
+              description: |
+                Lembrete exibido na tela: o `/health` do legado responde 200 mesmo com
+                100% das cotações falhando.
+        janela:
+          type: object
+          required: [total, sucesso, taxa_sucesso, p50_ms, p95_ms]
+          properties:
+            total: { type: integer }
+            sucesso: { type: integer }
+            taxa_sucesso: { type: number, minimum: 0, maximum: 1 }
+            p50_ms: { type: integer }
+            p95_ms:
+              type: integer
+              description: Inclui as chamadas lentas de 8s — é o que se quer ver.
+            por_outcome:
+              type: object
+              additionalProperties: { type: integer }
+        breaker:
+          type: object
+          required: [estado, falhas_consecutivas]
+          properties:
+            estado: { type: string, enum: [fechado, aberto, meia_abertura] }
+            falhas_consecutivas: { type: integer }
+            aberto_desde: { type: [string, "null"], format: date-time }
+            reabre_em: { type: [string, "null"], format: date-time }
+        ultimas_tentativas:
+          type: array
+          items:
+            allOf:
+              - $ref: "#/components/schemas/QuoteAttempt"
+              - type: object
+                properties:
+                  quote_id: { type: string }
+                  conversation_id:
+                    type: string
+                    description: Link para a conversa que originou a tentativa.
+
+    Handoff:
+      type: object
+      required: [id, conversation_id, trigger, reason, status, disparado_por, criado_em]
+      properties:
+        id: { type: string }
+        conversation_id: { type: string }
+        trigger:
+          type: string
+          description: |
+            Qual **regra** disparou. É o que torna o critério explícito e defensável:
+            a fila mostra o gatilho, não uma frase gerada. O conjunto de valores é
+            fechado pela decisão aberta nº1.
+        reason: { type: string }
+        summary: { type: [string, "null"] }
+        disparado_por:
+          type: string
+          enum: [regra, modelo]
+          description: |
+            Um gatilho determinístico (breaker aberto, 422 de recusa) e uma decisão do
+            modelo produzem o mesmo sinal — e a fila distingue os dois.
+        quote_id:
+          type: [string, "null"]
+          description: Última cotação tentada. É o que o operador vê primeiro ao assumir.
+        ultima_cotacao:
+          oneOf:
+            - $ref: "#/components/schemas/Quote"
+            - type: "null"
+        status: { $ref: "#/components/schemas/HandoffStatus" }
+        criado_em: { type: string, format: date-time }
+        assumido_em: { type: [string, "null"], format: date-time }
+        resolved_at: { type: [string, "null"], format: date-time }
+
+    Usage:
+      type: object
+      required: [total, por_provider, por_conversa]
+      properties:
+        total:
+          $ref: "#/components/schemas/UsageAgregado"
+        por_provider:
+          type: array
+          description: Anthropic e Ollama lado a lado.
+          items:
+            allOf:
+              - type: object
+                required: [provider]
+                properties:
+                  provider: { type: string }
+              - $ref: "#/components/schemas/UsageAgregado"
+        por_conversa:
+          type: array
+          items:
+            allOf:
+              - type: object
+                required: [conversation_id]
+                properties:
+                  conversation_id: { type: string }
+                  turnos: { type: integer }
+              - $ref: "#/components/schemas/UsageAgregado"
+
+    UsageAgregado:
+      type: object
+      required: [tokens_in, tokens_out]
+      properties:
+        tokens_in: { type: integer }
+        tokens_out: { type: integer }
+        cache_read:
+          type: [integer, "null"]
+          description: |
+            **Nulo, não zero**, quando o provider não reporta caching — o Ollama não
+            reporta. Um zero aqui diria "o cache não acertou" onde a verdade é "não
+            existe cache neste caminho".
+        cache_write: { type: [integer, "null"] }
+        taxa_acerto_cache:
+          type: [number, "null"]
+          description: Nula quando não há dado de cache na amostra. A UI mostra "n/a".
+        custo_usd:
+          type: [number, "null"]
+          description: |
+            Nulo para inferência local, que não tem preço por token. Calculado por nós
+            a partir de `config/model_pricing.yaml` — o Agno não popula `cost` para a
+            Anthropic.
+        pricing_vigencia:
+          type: [string, "null"]
+          format: date
+          description: Vigência da tabela de preço usada, para o custo ser auditável.
+        latency_p50_ms: { type: [integer, "null"] }
+
+    MessageEvent:
+      type: object
+      description: Servidor → cliente, no WebSocket de chat.
+      required: [type, message]
+      properties:
+        type: { type: string, enum: [message] }
+        message: { $ref: "#/components/schemas/Message" }
+
+    TypingEvent:
+      type: object
+      description: |
+        Servidor → cliente. Não é enfeite: é como a espera da `/quote` fica visível
+        para o lead enquanto o job continua.
+      required: [type, ativo]
+      properties:
+        type: { type: string, enum: [typing] }
+        ativo: { type: boolean }
+
+    StateEvent:
+      type: object
+      description: Servidor → cliente, na mudança de estado da conversa.
+      required: [type, state]
+      properties:
+        type: { type: string, enum: [state] }
+        state: { $ref: "#/components/schemas/ConversationState" }


=== DIFF: pyproject.toml ===
@@ -0,0 +1,23 @@
+[project]
+name = "autoseguro-agente"
+version = "0.1.0"
+description = "Agente de cotacao de seguro auto — desafio FDE Namastex"
+requires-python = ">=3.11"
+dependencies = [
+    "pydantic>=2.6",
+]
+
+[dependency-groups]
+dev = [
+    "pytest>=8.0",
+]
+
+[tool.pytest.ini_options]
+testpaths = ["tests"]
+pythonpath = ["."]
+markers = [
+    "live: exige a /quote rodando (QUOTE_API_URL, default http://localhost:8001)",
+]
+
+[tool.uv]
+package = false


=== DIFF: tests/test_contratos.py ===
@@ -0,0 +1,275 @@
+"""Testes dos contratos da Fase 0.
+
+Provam três coisas que o resto da entrega assume:
+
+1. `QuoteRequest` torna **impossível** montar uma requisição que a `/quote` aceitaria
+   errado sem devolver erro (`plano_id` vazio, CEP de 7 dígitos).
+2. `classificar_erro` separa as quatro classes de erro pela *forma do corpo*, não só
+   pelo status — inclusive os dois casos que a API chama de recusa mas são bug nosso.
+3. `QuotePayload` valida o corpo 200 **real** da API rodando, não um exemplo colado.
+
+Os testes marcados `live` batem na `/quote` em `QUOTE_API_URL` (default
+`http://localhost:8001`, a instância sem instabilidade). Sem ela, pulam.
+"""
+
+from __future__ import annotations
+
+import datetime as dt
+import json
+import os
+import urllib.error
+import urllib.request
+
+import pytest
+from pydantic import ValidationError
+
+from app.contracts.channel import ChannelAdapter
+from app.contracts.conversa import (
+    Autor,
+    HandoffSignal,
+    HandoffTrigger,
+    LeadProfile,
+    MessageStatus,
+    Turn,
+)
+from app.contracts.quote import (
+    MotivoRecusa,
+    QuoteOutcome,
+    QuotePayload,
+    QuoteRequest,
+    classificar_erro,
+)
+
+QUOTE_API_URL = os.getenv("QUOTE_API_URL", "http://localhost:8001")
+
+
+# ─── QuoteRequest: normalização na fronteira ────────────────────────────────
+
+
+def test_cep_mascarado_vira_oito_digitos():
+    r = QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2022, cep="[CEP]")
+    assert r.cep == "[CEP]"
+
+
+def test_cep_de_sete_digitos_e_descartado():
+    """`"7000-000"` seria lido pela API como prefixo `"70"` e perderia o agravo de
+    30% em silêncio. Vira `None` para que o agente repergunte."""
+    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022, cep="7000-000")
+    assert r.cep is None
+
+
+@pytest.mark.parametrize(
+    ("cep", "esperado"),
+    [("[CEP]", True), ("[CEP]", True), ("[CEP]", True), ("[CEP]", False), (None, False)],
+)
+def test_deteccao_de_cep_de_alto_risco(cep, esperado):
+    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022, cep=cep)
+    assert r.cep_alto_risco is esperado
+
+
+@pytest.mark.parametrize("plano_id", ["", "ouro", "COMPLETO", None])
+def test_plano_id_invalido_e_rejeitado_na_construcao(plano_id):
+    """`plano_id: ""` faz a API cotar `essencial` com status 200 — o erro mais
+    perigoso, porque não aparece em nenhum status HTTP."""
+    with pytest.raises(ValidationError):
+        QuoteRequest(plano_id=plano_id, idade=35, veiculo_ano=2022)
+
+
+def test_payload_omite_opcionais_em_vez_de_enviar_vazio():
+    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022)
+    assert r.to_api_payload() == {"plano_id": "essencial", "idade": 35, "veiculo_ano": 2022}
+
+
+def test_payload_completo():
+    r = QuoteRequest(
+        plano_id="completo", idade=35, veiculo_ano=2022,
+        cep="[CEP]", data_inicio=dt.date(2026, 7, 15),
+    )
+    assert r.to_api_payload() == {
+        "plano_id": "completo", "idade": 35, "veiculo_ano": 2022,
+        "cep": "[CEP]", "data_inicio": "2026-07-15",
+    }
+
+
+# ─── Taxonomia de erro ──────────────────────────────────────────────────────
+
+CORPO_5XX = {"error": "upstream_unavailable", "message": "Servico temporariamente indisponivel."}
+
+
+def _recusa(motivo: str) -> dict:
+    return {"error": "cotacao_recusada", "motivo": motivo}
+
+
+@pytest.mark.parametrize(
+    ("status", "corpo", "timeout", "outcome", "motivo"),
+    [
+        (503, CORPO_5XX, False, QuoteOutcome.TRANSIENT, None),
+        (500, CORPO_5XX, False, QuoteOutcome.TRANSIENT, None),
+        (502, CORPO_5XX, False, QuoteOutcome.TRANSIENT, None),
+        (None, None, True, QuoteOutcome.TIMEOUT, None),
+        # Recusas de verdade — o lead ouve o motivo.
+        (422, _recusa("Idade acima do limite de aceitacao (75 anos)."), False,
+         QuoteOutcome.REFUSED, MotivoRecusa.IDADE_ACIMA),
+        (422, _recusa("Idade fora das faixas aceitas."), False,
+         QuoteOutcome.REFUSED, MotivoRecusa.IDADE_ABAIXO),
+        (422, _recusa("Veiculo com mais de 20 anos nao e aceito."), False,
+         QuoteOutcome.REFUSED, MotivoRecusa.VEICULO_ANTIGO),
+        # Vestidos de recusa, mas são bug nosso: o lead informou um ano futuro, e o
+        # `plano_id` fomos nós que escolhemos. Dizer "você foi recusado" seria mentir.
+        (422, _recusa("Idade do veiculo fora das faixas aceitas."), False,
+         QuoteOutcome.BAD_REQUEST, None),
+        (422, _recusa("Plano 'ouro' inexistente. Opcoes: essencial, completo, premium"), False,
+         QuoteOutcome.BAD_REQUEST, None),
+        # Validação do Pydantic e parsing interno: bug nosso, o lead nunca vê.
+        (422, {"detail": [{"type": "missing", "loc": ["body", "idade"]}]}, False,
+         QuoteOutcome.BAD_REQUEST, None),
+        (400, {"error": "payload_invalido", "detalhe": "Invalid isoformat string: '15/07/2026'"},
+         False, QuoteOutcome.BAD_REQUEST, None),
+        (405, None, False, QuoteOutcome.BAD_REQUEST, None),
+        (404, None, False, QuoteOutcome.BAD_REQUEST, None),
+    ],
+)
+def test_classificacao_de_erro(status, corpo, timeout, outcome, motivo):
+    e = classificar_erro(status, corpo, timeout=timeout)
+    assert e.outcome is outcome
+    assert e.motivo_recusa is motivo
+
+
+@pytest.mark.parametrize(
+    ("outcome", "retentavel"),
+    [
+        (QuoteOutcome.TRANSIENT, True),
+        (QuoteOutcome.TIMEOUT, True),
+        (QuoteOutcome.OK, False),
+        (QuoteOutcome.REFUSED, False),
+        (QuoteOutcome.BAD_REQUEST, False),
+    ],
+)
+def test_so_transitorio_e_timeout_retentam(outcome, retentavel):
+    assert outcome.retentavel is retentavel
+
+
+def test_422_do_pydantic_nao_propaga_detalhe():
+    """O corpo do 422 de validação ecoa o payload enviado — idade e CEP do lead.
+    Ele não pode viajar para log nem para a tela."""
+    e = classificar_erro(422, {"detail": [{"input": {"idade": 80, "cep": "[CEP]"}}]})
+    assert e.detalhe_bruto is None
+
+
+def test_motivo_desconhecido_nao_vira_recusa():
+    """Na dúvida, não afirmamos ao lead que ele foi recusado."""
+    e = classificar_erro(422, _recusa("Motivo que a API ainda não tinha em 2026."))
+    assert e.outcome is QuoteOutcome.BAD_REQUEST
+
+
+# ─── LeadProfile ────────────────────────────────────────────────────────────
+
+
+def test_campos_faltantes_seguem_a_ordem_de_qualificacao():
+    assert LeadProfile(idade=35).campos_faltantes == ("veiculo_ano", "cep", "data_inicio", "plano_id")
+
+
+def test_perfil_incompleto_nao_cota():
+    with pytest.raises(ValueError, match="perfil incompleto"):
+        LeadProfile(idade=35).to_quote_request()
+
+
+def test_perfil_completo_produz_a_requisicao():
+    lp = LeadProfile(
+        idade=35, veiculo_ano=2022, cep="[CEP]",
+        data_inicio=dt.date(2026, 7, 15), plano_id="completo",
+    )
+    assert lp.completo
+    assert lp.to_quote_request() == QuoteRequest(
+        plano_id="completo", idade=35, veiculo_ano=2022,
+        cep="[CEP]", data_inicio=dt.date(2026, 7, 15),
+    )
+
+
+def test_lead_profile_rejeita_cep_fora_de_oito_digitos():
+    with pytest.raises(ValidationError):
+        LeadProfile(cep="7000000")
+
+
+# ─── Turno, handoff e porta ─────────────────────────────────────────────────
+
+
+def test_mensagem_com_preco_carrega_quote_id():
+    t = Turn(
+        message_id="m1", conversation_id="c1", index=0, autor=Autor.SISTEMA,
+        conteudo="Ficou R$ 209,90/mês.", status=MessageStatus.SENT,
+        criado_em=dt.datetime(2026, 9, 4, 12, 0), quote_id="q1",
+    )
+    assert t.quote_id == "q1"
+
+
+def test_handoff_e_disparado_por_regra_ate_prova_em_contrario():
+    h = HandoffSignal(trigger=HandoffTrigger.COTACAO_INDISPONIVEL, reason="3 tentativas sem resposta")
+    assert h.disparado_por == "regra"
+
+
+def test_adaptador_minimo_satisfaz_a_porta():
+    class Fake:
+        name = "fake"
+
+        async def send(self, conversation_id, text, *, message_id, quote_id=None):
+            return "x"
+
+        async def typing(self, conversation_id, *, ativo): ...
+
+        def receive(self): ...
+
+    assert isinstance(Fake(), ChannelAdapter)
+
+
+# ─── Contra a API rodando ───────────────────────────────────────────────────
+
+
+def _post(payload: dict) -> dict:
+    req = urllib.request.Request(
+        f"{QUOTE_API_URL}/quote",
+        data=json.dumps(payload).encode(),
+        headers={"content-type": "application/json"},
+    )
+    with urllib.request.urlopen(req, timeout=15) as resp:
+        return json.load(resp)
+
+
+@pytest.fixture(scope="module")
+def api_viva() -> None:
+    try:
+        with urllib.request.urlopen(f"{QUOTE_API_URL}/health", timeout=3):
+            return
+    except (urllib.error.URLError, OSError):
+        pytest.skip(f"/quote indisponível em {QUOTE_API_URL}")
+
+
+@pytest.mark.live
+def test_payload_valida_o_corpo_200_real(api_viva):
+    r = QuoteRequest(
+        plano_id="completo", idade=35, veiculo_ano=2022,
+        cep="[CEP]", data_inicio=dt.date(2026, 7, 15),
+    )
+    p = QuotePayload.model_validate(_post(r.to_api_payload()))
+    assert p.premio_mensal == 209.90
+    assert p.carencia.dias == 30
+    assert p.carencia.coberturas == ["roubo", "furto"]
+    assert p.primeiro_pagamento_pro_rata is not None
+
+
+@pytest.mark.live
+@pytest.mark.parametrize("plano_id", ["essencial", "completo", "premium"])
+def test_carencia_vem_nos_tres_planos(api_viva, plano_id):
+    """Ela é incondicional na resposta — por isso entra no template, e não fica a
+    critério do modelo lembrar."""
+    p = QuotePayload.model_validate(
+        _post(QuoteRequest(plano_id=plano_id, idade=35, veiculo_ano=2022).to_api_payload())
+    )
+    assert p.carencia.dias == 30
+
+
+@pytest.mark.live
+def test_pro_rata_some_no_dia_primeiro(api_viva):
+    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022,
+                     data_inicio=dt.date(2026, 10, 1))
+    assert QuotePayload.model_validate(_post(r.to_api_payload())).primeiro_pagamento_pro_rata is None


Investigate per the method in your instructions, then return the findings list.

### Claude

Looking at this change, it's a Phase 0 contracts-only introduction: Pydantic models, SQL DDL migrations, an OpenAPI spec (documentation, no implementation), a pricing YAML, and tests. Let me verify by checking for any implementation code that would consume these contracts.

### Claude

→ **Glob**  `{"pattern": "app/**/*.py"}`

### Mateus

```
app/contracts/__init__.py
app/__init__.py
app/contracts/quote.py
app/contracts/conversa.py
app/contracts/channel.py
```

### Claude

→ **Glob**  `{"pattern": "**/*.py"}`

### Mateus

```
.venv/lib/python3.13/site-packages/pluggy/_callers.py
.venv/lib/python3.13/site-packages/pluggy/__init__.py
.venv/lib/python3.13/site-packages/pluggy/_hooks.py
.venv/lib/python3.13/site-packages/pluggy/_tracing.py
.venv/lib/python3.13/site-packages/pluggy/_result.py
.venv/lib/python3.13/site-packages/pluggy/_manager.py
.venv/lib/python3.13/site-packages/pluggy/_version.py
.venv/lib/python3.13/site-packages/pluggy/_warnings.py
.venv/lib/python3.13/site-packages/iniconfig/__init__.py
.venv/lib/python3.13/site-packages/iniconfig/_parse.py
.venv/lib/python3.13/site-packages/iniconfig/_version.py
.venv/lib/python3.13/site-packages/iniconfig/exceptions.py
app/contracts/__init__.py
app/__init__.py
app/contracts/quote.py
app/contracts/conversa.py
app/contracts/channel.py
tests/test_contratos.py
.venv/bin/activate_this.py
.venv/lib/python3.13/site-packages/_virtualenv.py
.venv/lib/python3.13/site-packages/typing_inspection/__init__.py
.venv/lib/python3.13/site-packages/typing_inspection/typing_objects.py
.venv/lib/python3.13/site-packages/typing_inspection/introspection.py
.venv/lib/python3.13/site-packages/annotated_types/__init__.py
.venv/lib/python3.13/site-packages/annotated_types/test_
… [+4375 caracteres]
```

### Claude

I've read every changed file in full and cross-checked the repo for any downstream consumers.

**What's in this change:**
- `app/contracts/*.py`: Pure Pydantic model definitions and a `Protocol` port. No I/O, no exec, no filesystem, no template rendering.
- `db/migrations/*.sql`: Pure DDL (BEGIN/COMMIT with CREATE TYPE/TABLE/INDEX and CHECK constraints). No dynamic SQL construction.
- `docs/openapi.yaml`: Documentation only; no server implementation exists in the repo.
- `config/model_pricing.yaml`: Static data.
- `pyproject.toml`: Deps (pydantic>=2.6, pytest>=8.0).
- `tests/test_contratos.py`: Tests. HTTP calls only in `@pytest.mark.live` tests to a URL from `QUOTE_API_URL` env var (test-scope only).

**Sink map for the diff:**
- Shell/exec/subprocess: none.
- Dynamic SQL: none — only DDL.
- Filesystem: none.
- Outbound HTTP: only in `live` tests to an env-configured URL (developer-controlled).
- Deserialization: `json.load` on the API's response in a test — trusted local test fixture.
- Templates/HTML render: none.
- Logging of PII: none — models are defined, but no code writes to logs/traces here.
- AuthZ: no handlers implemented; OpenAPI documents "no auth, local only" as an intentional scope decision, not a new gate this diff bypasses.

**Data-flow checks against the +lines:**
- `QuoteRequest._normalizar_cep` strips non-digits and drops anything ≠ 8 digits (fail-closed). Python's `\d`/`\D` is Unicode-aware, so exotic digit scripts could produce an 8-char string that's not ASCII; but the only consumer of `.cep` (a) is the property-based `cep_alto_risco` (marketing warning, not price — price is authoritative from the /quote server) and (b) the outgoing API payload, which the /quote server itself will reject or classify. No security-relevant sink is reached.
- `classificar_erro`: purely reads dict fields into a `QuoteError`; the raw `detalhe_bruto` string is documented as "never shown to the lead" and there's no consumer yet to check for leaks against.
- SQL migrations: CHECK constraints tighten invariants (`quotes_premio_sse_ok`, `attempts_timeout_sem_status`, `handoffs_resolvido_tem_data`, `turn_usage_*`). These are fail-closed at the DB.
- `ON DELETE CASCADE` on `conversations → messages/quotes/handoffs`, and `messages_quote_fk ON DELETE SET NULL` — standard referential design; no privilege boundary crossed.
- OpenAPI PATCH /api/handoffs is unauthenticated — but no implementation, and the doc explicitly declares "local-only, no auth" as scope. Not a regression from a prior gate.

No source → sink path with a missing mitigation exists in this diff. Every `+` line is either a type declaration, a schema constraint that tightens invariants, or documentation.

### Claude

→ **StructuredOutput**  `{"findings": {"findings": []}}`

### Mateus

```
Output does not match required schema: /findings: must be array
```

### Claude

→ **StructuredOutput**  `{"findings": []}`

### Mateus

```
Structured output provided successfully
```
