"""A cotação como **job com estado**.

Não é preferência de design; é aritmética. O pior caso da política de retry é
~37 s — três tentativas de 12 s mais backoff — e isso não cabe dentro de um turno de
conversa. Ou o agente fala antes de ter o preço, ou fica mudo por meio minuto.

O job grava **toda** tentativa, inclusive as que falham — que é justamente quando a
linha do tempo importa. É `quote_attempts` que responde, sem log nenhum: "tentamos 3
vezes, a 1ª deu 503 em 40 ms, a 2ª estourou o timeout aos 12 s, a 3ª voltou 200 aos
8,01 s".

Nesta fatia o job faz **uma** tentativa. Retry, backoff, semáforo e breaker entram na
fatia 4.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.contracts.quote import (
    QuoteError,
    QuoteJobStatus,
    QuoteOutcome,
    QuotePayload,
    QuoteRequest,
)
from app.persistence.models import Quote, QuoteAttempt
from app.privacy.mascarar import mascarar
from app.quote import client


def _id(p: str) -> str:
    return f"{p}_{uuid.uuid4().hex[:16]}"


def criar_job(s: Session, conversation_id: str, req: QuoteRequest) -> Quote:
    """O job nasce `pending` e com id **antes** da primeira tentativa: assim ele
    existe para ser referenciado mesmo que tudo dê errado."""
    q = Quote(
        id=_id("q"), conversation_id=conversation_id, status="pending",
        req_plano_id=req.plano_id, req_idade=req.idade,
        req_veiculo_ano=req.veiculo_ano, req_cep=req.cep,
        req_data_inicio=req.data_inicio,
    )
    s.add(q)
    s.flush()
    return q


def gravar_tentativa(
    s: Session, quote_id: str, attempt: int, resp: client.Resposta,
    erro: QuoteError | None,
) -> QuoteAttempt:
    outcome = QuoteOutcome.OK if resp.ok else (erro.outcome if erro else QuoteOutcome.BAD_REQUEST)

    detalhe = None
    if erro is not None and erro.detalhe_bruto:
        # O corpo do 400 ecoa o valor mal formatado que MANDAMOS, e o do 422 do
        # Pydantic ecoa o payload inteiro. `quote_attempts` alimenta /admin/status,
        # que é superfície visível — então o detalhe passa pelo mascaramento como
        # qualquer outro texto que chega ao banco.
        detalhe = mascarar(erro.detalhe_bruto)[:2000]

    a = QuoteAttempt(
        id=_id("qa"), quote_id=quote_id, attempt=attempt,
        # `timeout` não tem status HTTP — o CHECK da migração impõe isso.
        http_status=None if outcome is QuoteOutcome.TIMEOUT else resp.http_status,
        latency_ms=resp.latency_ms, outcome=str(outcome), detalhe=detalhe,
    )
    s.add(a)
    s.flush()
    return a


def finalizar(
    s: Session, q: Quote, *, status: QuoteJobStatus,
    payload: QuotePayload | None = None, erro: QuoteError | None = None,
    latency_ms: int = 0, circuito_aberto: bool = False,
) -> Quote:
    q.status = str(status)
    q.total_latency_ms = latency_ms
    q.finalizado_em = dt.datetime.now(dt.UTC)
    q.circuito_aberto = circuito_aberto

    if status is QuoteJobStatus.OK and payload is not None:
        q.premio_mensal = payload.premio_mensal
        q.franquia = payload.franquia
        q.carencia_dias = payload.carencia.dias
        if payload.primeiro_pagamento_pro_rata:
            q.pro_rata_valor = payload.primeiro_pagamento_pro_rata.valor_primeiro_pagamento
            q.pro_rata_dias = payload.primeiro_pagamento_pro_rata.dias_cobrados
        bruto = payload.model_dump()
        # A data de início vai junto para que o render seja reproduzível a partir só
        # da linha de `quotes` — inclusive anos depois, na verificação do guardrail.
        bruto["_data_inicio"] = q.req_data_inicio.isoformat() if q.req_data_inicio else None
        q.payload = bruto
    if erro is not None:
        q.erro_outcome = str(erro.outcome)
        if status is QuoteJobStatus.REFUSED and erro.motivo_recusa:
            q.motivo_recusa = str(erro.motivo_recusa)
    s.flush()
    return q


def executar_job(s: Session, conversation_id: str, req: QuoteRequest) -> Quote:
    """Uma tentativa (fatia 3). O laço de retry entra na fatia 4."""
    q = criar_job(s, conversation_id, req)
    resp = client.chamar(req)
    erro = None if resp.ok else resp.erro()
    gravar_tentativa(s, q.id, 1, resp, erro)

    if resp.ok:
        return finalizar(s, q, status=QuoteJobStatus.OK,
                         payload=QuotePayload.model_validate(resp.corpo),
                         latency_ms=resp.latency_ms)

    status = {
        QuoteOutcome.REFUSED: QuoteJobStatus.REFUSED,
    }.get(erro.outcome, QuoteJobStatus.FAILED)
    return finalizar(s, q, status=status, erro=erro, latency_ms=resp.latency_ms)
