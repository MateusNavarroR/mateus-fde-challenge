"""Contratos da conversa — lead, turno, estado e sinal de handoff.

Congelado na Fase 0. Ver `app/contracts/quote.py` para o motivo de os contratos
viverem num pacote próprio.
"""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.quote import PlanoId, QuoteRequest

# ─────────────────────────────────────────────────────────────────────────────
# Perfil do lead
# ─────────────────────────────────────────────────────────────────────────────

#: Os cinco campos da qualificação, na ordem em que são perguntados.
#: Cada um está aqui porque muda o resultado ou destrava um campo da resposta:
#: idade e ano do veículo definem multiplicador *e* aceitação; CEP vale até 30% de
#: agravo; data de início destrava o pro-rata; plano define a base.
CAMPOS_QUALIFICACAO: tuple[str, ...] = (
    "idade",
    "veiculo_ano",
    "cep",
    "data_inicio",
    "plano_id",
)


class LeadProfile(BaseModel):
    """O que sabemos do lead. Todo campo é opcional porque a conversa é incremental.

    Guarda também o **texto de origem** de cada extração: quando a `/quote` devolve
    `bad_request`, é a origem que diz se reperguntamos ou se o bug é do extrator — e
    é o que a tela de rastreabilidade mostra ao operador.
    """

    model_config = ConfigDict(extra="forbid")

    idade: Annotated[int, Field(ge=0, le=200)] | None = None
    veiculo_ano: Annotated[int, Field(ge=1950, le=2100)] | None = None
    #: Sempre 8 dígitos, sem máscara. Ver `QuoteRequest._normalizar_cep`.
    cep: Annotated[str, Field(pattern=r"^\d{8}$")] | None = None
    data_inicio: dt.date | None = None
    plano_id: PlanoId | None = None

    #: Texto livre de onde veio cada campo, para auditoria. Chave = nome do campo.
    #: **Mascarado antes de persistir** — pode conter CPF e CEP crus.
    origem: dict[str, str] = Field(default_factory=dict)

    #: Quantas vezes já reperguntamos cada campo. Alimenta o gatilho de handoff por
    #: falha de extração repetida.
    tentativas_extracao: dict[str, int] = Field(default_factory=dict)

    @property
    def campos_faltantes(self) -> tuple[str, ...]:
        return tuple(c for c in CAMPOS_QUALIFICACAO if getattr(self, c) is None)

    @property
    def completo(self) -> bool:
        return not self.campos_faltantes

    def to_quote_request(self) -> QuoteRequest:
        """Só é chamável com o perfil completo — cotar com campo faltando é
        exatamente o erro que a `/quote` não reporta (`plano_id: ""` cota
        `essencial` calado)."""
        if not self.completo:
            raise ValueError(
                f"perfil incompleto: faltam {', '.join(self.campos_faltantes)}"
            )
        return QuoteRequest(
            plano_id=self.plano_id,
            idade=self.idade,
            veiculo_ano=self.veiculo_ano,
            cep=self.cep,
            data_inicio=self.data_inicio,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Turno e mensagem
# ─────────────────────────────────────────────────────────────────────────────


class Autor(StrEnum):
    LEAD = "lead"
    AGENTE = "agente"
    #: Mensagem gerada pelo sistema sem passar pelo modelo — o texto da cotação
    #: renderizado por template, o aviso de espera, o texto de recusa.
    SISTEMA = "sistema"
    OPERADOR = "operador"


class MessageStatus(StrEnum):
    """Estado de entrega de uma mensagem. Critério declarado: *cada mensagem com id
    e status*."""

    RECEIVED = "received"     # do lead, aceita
    PENDING = "pending"       # nossa, ainda não entregue ao canal
    SENT = "sent"
    FAILED = "failed"
    DISCARDED = "discarded"   # duplicada ou fora de janela


TipoMidia = Literal["text", "image", "audio", "document"]


class Turn(BaseModel):
    """Uma mensagem da conversa. Unidade de persistência e de exibição.

    `conteudo` é sempre a versão **mascarada**. O texto cru não é persistido nem
    trafega para log, trace ou UI.
    """

    model_config = ConfigDict(frozen=True)

    message_id: str
    conversation_id: str
    #: Ordem canônica dentro da conversa. É por ela que se ordena, nunca por timestamp.
    index: Annotated[int, Field(ge=0)]
    autor: Autor
    tipo: TipoMidia = "text"
    conteudo: str
    status: MessageStatus
    criado_em: dt.datetime
    #: `quote_id` quando esta mensagem carrega uma cotação. É o guardrail auditável:
    #: nenhum valor monetário sai numa mensagem sem este vínculo.
    quote_id: str | None = None


class ConversationState(StrEnum):
    """Máquina de estados da conversa.

    ```
    novo → qualificando → cotando → cotado → fechado
              │              │         │
              └──────────────┴─────────┴──────► encaminhado
    ```

    `encaminhado` é alcançável de qualquer estado — é a saída de todos os gatilhos.
    """

    NOVO = "novo"
    QUALIFICANDO = "qualificando"
    COTANDO = "cotando"
    COTADO = "cotado"
    FECHADO = "fechado"
    ENCAMINHADO = "encaminhado"


# ─────────────────────────────────────────────────────────────────────────────
# Handoff
# ─────────────────────────────────────────────────────────────────────────────


class HandoffTrigger(StrEnum):
    """Os sete gatilhos de handoff, como dados e não como `if` espalhado.

    **A ordem da declaração É a precedência.** Quando dois disparam no mesmo turno,
    o primeiro vence e os demais são gravados como secundários — a fila mostra um
    gatilho, o operador vê o quadro completo.

    O critério é **o custo de o agente errar ali**: custo alto encaminha na hora e
    sem tentar; custo baixo tenta e encaminha na segunda vez.

    ⚠️ `COTACAO_RECUSADA` **foi removido**. Ele existia na Fase 0, antes de a decisão
    3 fechar, e é justamente o que `DECISOES-FECHADAS.md` §3 lista sob "não são
    gatilhos": recusa não cria handoff, porque um humano releria a mesma regra fixa
    em `plans.json` e daria o mesmo "não". Encaminhar 30% do tráfego para isso
    encheria a fila com casos sem saída.
    """

    #: custo alto — encaminha imediato, sem tentar responder
    ASSUNTO_SENSIVEL = "assunto_sensivel"
    #: custo alto — encerra e registra
    GUARDRAIL = "guardrail"
    #: pedido explícito
    LEAD_PEDIU = "lead_pediu_atendente"
    #: custo alto — o job de cotação terminou `failed`
    COTACAO_INDISPONIVEL = "cotacao_indisponivel"
    #: custo médio — 2ª falha de extração no MESMO campo
    EXTRACAO_FALHOU = "extracao_falhou"
    #: custo baixo — o lead REPETE a objeção de preço
    OBJECAO_FORA_DA_ALCADA = "objecao_fora_da_alcada"
    #: custo baixo — o lead INSISTE em mídia depois de pedirmos texto
    MIDIA_SEM_TEXTO = "midia_sem_texto"


class HandoffStatus(StrEnum):
    PENDENTE = "pendente"
    ASSUMIDO = "assumido"
    RESOLVIDO = "resolvido"


class HandoffSignal(BaseModel):
    """Sinal de handoff no padrão **write-back**: a tool do agente só registra a
    intenção; quem executa é o backend.

    Isso mantém o comportamento testável e impede o modelo de causar efeito colateral
    direto — e é o que permite que um gatilho determinístico (breaker aberto, 422 de
    recusa) produza exatamente o mesmo sinal que uma decisão do modelo.
    """

    model_config = ConfigDict(frozen=True)

    trigger: HandoffTrigger
    #: Motivo legível para o operador. Nunca é o texto cru da API nem do lead.
    reason: str
    summary: str | None = None
    #: Última cotação tentada, quando houver — a fila mostra o desfecho dela.
    quote_id: str | None = None
    #: Preenchido pelo backend, não pelo modelo.
    disparado_por: Literal["regra", "modelo"] = "regra"
