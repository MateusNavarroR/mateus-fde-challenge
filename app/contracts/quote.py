"""Contratos da cotação — a fronteira entre o agente e o legado instável.

Estes tipos são o **contrato congelado da Fase 0**: mais de uma frente depende deles,
então eles vivem num pacote próprio e mudam por decisão, não por conveniência de quem
está implementando.

Duas ideias organizam este módulo:

1. **Normalizar antes de chamar.** Três campos erram *sem status HTTP* na `/quote`:
   `plano_id` vazio cota `essencial` calado, um CEP de 7 dígitos zera o agravo de 30%,
   e `data_inicio` fora do ISO vira 400. Por isso `QuoteRequest` normaliza e valida na
   construção — é impossível montar uma requisição malformada.

2. **Classificar por corpo, não por status.** O status HTTP da `/quote` não determina
   sozinho o que fazer nem o que dizer ao lead: o 422 carrega dois erros de naturezas
   opostas, e dentro da recusa há casos que são bug nosso disfarçado. A classificação
   vive em `classificar_erro()`, com uma classe para cada ação distinta.

Referência medida: docs/API-COTACAO.md
"""

from __future__ import annotations

import datetime as dt
import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PlanoId = Literal["essencial", "completo", "premium"]

PLANOS: tuple[PlanoId, ...] = ("essencial", "completo", "premium")

#: Prefixos de CEP com agravo de 1.30 (docs/API-COTACAO.md §5.3).
#: Duplicado aqui de propósito: serve para *avisar* durante a qualificação. O valor
#: cobrado é sempre o que a /quote devolve, nunca o que calculamos por este conjunto.
PREFIXOS_CEP_ALTO_RISCO = frozenset({"07", "08", "21", "26", "59"})


# ─────────────────────────────────────────────────────────────────────────────
# Entrada
# ─────────────────────────────────────────────────────────────────────────────


class QuoteRequest(BaseModel):
    """Requisição já normalizada para `POST /quote`.

    Construir esta classe é a única forma permitida de chamar a `/quote`. Os
    validadores abaixo existem porque a API aceita lixo nestes campos sem devolver
    erro — ela simplesmente cota outra coisa.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plano_id: PlanoId
    idade: Annotated[int, Field(ge=0, le=200)]
    veiculo_ano: Annotated[int, Field(ge=1950, le=2100)]
    cep: str | None = None
    data_inicio: dt.date | None = None

    @field_validator("cep", mode="before")
    @classmethod
    def _normalizar_cep(cls, v: object) -> str | None:
        """8 dígitos ou nada.

        `"7000-000"` (zero à esquerda perdido — erro de digitação corriqueiro) é lido
        pela API como prefixo `"70"` e **perde o agravo de 30% em silêncio**. Um CEP
        que não tem exatamente 8 dígitos não é um CEP: vira `None` e reperguntamos.
        """
        if v is None:
            return None
        digitos = re.sub(r"\D", "", str(v))
        return digitos if len(digitos) == 8 else None

    @property
    def cep_alto_risco(self) -> bool:
        return bool(self.cep) and self.cep[:2] in PREFIXOS_CEP_ALTO_RISCO

    def to_api_payload(self) -> dict[str, object]:
        """Corpo exato do `POST /quote`. `None` é omitido, nunca enviado vazio."""
        payload: dict[str, object] = {
            "plano_id": self.plano_id,
            "idade": self.idade,
            "veiculo_ano": self.veiculo_ano,
        }
        if self.cep:
            payload["cep"] = self.cep
        if self.data_inicio:
            payload["data_inicio"] = self.data_inicio.isoformat()
        return payload


# ─────────────────────────────────────────────────────────────────────────────
# Saída — o corpo 200 da /quote
# ─────────────────────────────────────────────────────────────────────────────


class Carencia(BaseModel):
    """Sempre presente nas respostas 200, nos três planos. Nunca omitir ao lead."""

    model_config = ConfigDict(frozen=True)

    coberturas: list[str]
    dias: int
    observacao: str


class ProRata(BaseModel):
    """Só existe quando enviamos `data_inicio` com dia ≠ 1."""

    model_config = ConfigDict(frozen=True)

    dias_no_mes: int
    dias_cobrados: int
    valor_primeiro_pagamento: float


class Multiplicadores(BaseModel):
    model_config = ConfigDict(frozen=True)

    faixa_etaria: float
    idade_veiculo: float
    regiao: float


class QuotePayload(BaseModel):
    """Corpo 200 da `/quote`, validado.

    É a **única** origem legítima de qualquer número que chegue ao lead. O renderer
    determinístico lê daqui; o modelo nunca escreve preço.
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    plano_id: PlanoId
    plano_nome: str
    premio_mensal: float
    franquia: int
    coberturas: list[str]
    multiplicadores: Multiplicadores
    carencia: Carencia
    moeda: str
    primeiro_pagamento_pro_rata: ProRata | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Taxonomia de erro
# ─────────────────────────────────────────────────────────────────────────────


class QuoteOutcome(StrEnum):
    """Desfecho de **uma tentativa** HTTP.

    Cada valor implica uma ação diferente, e é por isso que são cinco e não três.
    """

    OK = "ok"
    #: 5xx da instabilidade simulada → retenta.
    TRANSIENT = "transient"
    #: nosso timeout ou erro de conexão → retenta.
    TIMEOUT = "timeout"
    #: 422 `cotacao_recusada` com motivo que é de fato uma recusa → o lead ouve o motivo.
    REFUSED = "refused"
    #: 400, 422 `detail`, ou 422 recusa que na verdade é dado nosso errado → o lead
    #: nunca vê isto; é bug de extração.
    BAD_REQUEST = "bad_request"

    @property
    def retentavel(self) -> bool:
        return self in (QuoteOutcome.TRANSIENT, QuoteOutcome.TIMEOUT)


class MotivoRecusa(StrEnum):
    """Recusas reais, normalizadas a partir do texto do `motivo` da API.

    Só estas três viram mensagem de recusa para o lead. As outras duas coisas que a
    API chama de `cotacao_recusada` — `plano_id` inexistente e veículo com ano futuro —
    são defeito nosso e caem em `BAD_REQUEST`: dizer a quem informou 2027 que "seu
    veículo não é aceito" é mentir para ele.
    """

    IDADE_ACIMA = "idade_acima_do_limite"      # ≥ 76 anos
    IDADE_ABAIXO = "idade_abaixo_do_minimo"    # < 18 anos
    VEICULO_ANTIGO = "veiculo_acima_de_20_anos"


class QuoteError(BaseModel):
    """Erro classificado de uma tentativa, com o suficiente para agir e para auditar."""

    model_config = ConfigDict(frozen=True)

    outcome: QuoteOutcome
    http_status: int | None = None
    #: Motivo de recusa normalizado — preenchido apenas quando `outcome == REFUSED`.
    motivo_recusa: MotivoRecusa | None = None
    #: Texto cru da API, para o log e a tela de rastreabilidade. **Nunca vai ao lead**:
    #: o texto de recusa vem de um mapa fixo nosso, não da API nem do modelo.
    detalhe_bruto: str | None = None


def classificar_erro(
    http_status: int | None,
    corpo: dict[str, object] | None,
    *,
    timeout: bool = False,
) -> QuoteError:
    """Classifica uma resposta não-200 da `/quote`.

    A ordem das checagens é a ordem da precedência real do servidor
    (docs/API-COTACAO.md §7.2).
    """
    if timeout or http_status is None:
        return QuoteError(outcome=QuoteOutcome.TIMEOUT, http_status=http_status)

    if http_status >= 500:
        return QuoteError(
            outcome=QuoteOutcome.TRANSIENT,
            http_status=http_status,
            detalhe_bruto=str((corpo or {}).get("message")) if corpo else None,
        )

    corpo = corpo or {}
    erro = corpo.get("error")

    # 422 do Pydantic: `{"detail": [...]}` — bug nosso, e o corpo ecoa o payload
    # (idade, CEP do lead), então `detalhe_bruto` fica de fora aqui.
    if http_status == 422 and "detail" in corpo:
        return QuoteError(outcome=QuoteOutcome.BAD_REQUEST, http_status=422)

    if http_status == 422 and erro == "cotacao_recusada":
        motivo = str(corpo.get("motivo", ""))
        normalizado = _normalizar_motivo(motivo)
        if normalizado is None:
            # `plano_id` inexistente ou veículo com ano futuro: vestido de recusa,
            # mas é defeito nosso.
            return QuoteError(
                outcome=QuoteOutcome.BAD_REQUEST, http_status=422, detalhe_bruto=motivo
            )
        return QuoteError(
            outcome=QuoteOutcome.REFUSED,
            http_status=422,
            motivo_recusa=normalizado,
            detalhe_bruto=motivo,
        )

    if http_status == 400 and erro == "payload_invalido":
        return QuoteError(
            outcome=QuoteOutcome.BAD_REQUEST,
            http_status=400,
            detalhe_bruto=str(corpo.get("detalhe", "")),
        )

    # 404, 405 e qualquer forma não prevista: nossa, e não se retenta.
    return QuoteError(outcome=QuoteOutcome.BAD_REQUEST, http_status=http_status)


def _normalizar_motivo(motivo: str) -> MotivoRecusa | None:
    """Texto do `motivo` → recusa real, ou `None` se for defeito nosso.

    Casamento por trecho estável do texto da API. Um `motivo` desconhecido devolve
    `None` de propósito: na dúvida, não afirmamos ao lead que ele foi recusado.
    """
    m = motivo.lower()
    if "acima do limite de aceitacao" in m:
        return MotivoRecusa.IDADE_ACIMA
    if "idade fora das faixas" in m:
        return MotivoRecusa.IDADE_ABAIXO
    if "mais de 20 anos" in m:
        return MotivoRecusa.VEICULO_ANTIGO
    return None


# ─────────────────────────────────────────────────────────────────────────────
# A cotação como job
# ─────────────────────────────────────────────────────────────────────────────


class QuoteJobStatus(StrEnum):
    """O pior caso da política de retry (~40s) não cabe num turno de conversa.

    Por isso a cotação é um job com estado: o agente fala antes de ter o preço e o
    valor chega depois, como mensagem nova.
    """

    PENDING = "pending"
    OK = "ok"
    REFUSED = "refused"
    FAILED = "failed"


class QuoteAttempt(BaseModel):
    """Uma tentativa HTTP. É a linha de `quote_attempts` — a prova de rastreabilidade."""

    model_config = ConfigDict(frozen=True)

    attempt: Annotated[int, Field(ge=1)]
    http_status: int | None
    latency_ms: int
    outcome: QuoteOutcome
    error: QuoteError | None = None


class QuoteResult(BaseModel):
    """Resultado consolidado de um job de cotação, com todas as tentativas.

    Invariante: `payload is not None` **se e somente se** `status == OK`. É o que
    sustenta o guardrail "nenhum valor no texto sem `quote_id` com status `ok`".
    """

    model_config = ConfigDict(frozen=True)

    quote_id: str
    status: QuoteJobStatus
    request: QuoteRequest
    payload: QuotePayload | None = None
    error: QuoteError | None = None
    attempts: list[QuoteAttempt] = Field(default_factory=list)
    total_latency_ms: int = 0
    #: Verdadeiro quando o breaker impediu a chamada — o desfecho é `FAILED` sem
    #: nenhuma tentativa registrada, e a tela de status precisa distinguir isso.
    circuito_aberto: bool = False
