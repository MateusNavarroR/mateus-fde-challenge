"""A cotação como **job com estado**.

Não é preferência de design; é aritmética. O pior caso da política de retry é
~37 s — três tentativas de 12 s mais backoff — e isso não cabe dentro de um turno de
conversa. Ou o agente fala antes de ter o preço, ou fica mudo por meio minuto.

O job grava **toda** tentativa, inclusive as que falham — que é justamente quando a
linha do tempo importa. É `quote_attempts` que responde, sem log nenhum: "tentamos 3
vezes, a 1ª deu 503 em 40 ms, a 2ª estourou o timeout aos 12 s, a 3ª voltou 200 aos
8,01 s".

**O laço de retry.** Só `transient` e `timeout` retentam — 3 tentativas levam a 0,8% de
falha residual, e a 4ª compraria 0,64 ponto percentual por mais um ciclo que pode ser
de 12 s. `400` e `422`, nas duas formas, **nunca** retentam: retentá-los mascara defeito
e queima tempo.

**A espera é visível.** O relógio é o do lead — conta da chegada da mensagem dele, não
de quando a tool começou —, e o disparo é daqui, não de um watchdog genérico na camada
de conversa, que dispararia durante a geração do modelo.

**O breaker é consultado antes da primeira tentativa.** Com o circuito aberto o job
nasce `failed` **sem nenhuma tentativa** e com `circuito_aberto=True`: a tela precisa
distinguir isso de "tentamos 3 vezes e falhou".
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid

from sqlalchemy.orm import Session

from app.contracts.quote import (
    QuoteError,
    QuoteJobStatus,
    QuoteOutcome,
    QuotePayload,
    QuoteRequest,
)
from app.config import get_settings
from app.persistence.models import Quote, QuoteAttempt
from app.privacy.mascarar import mascarar
from app.quote import client
from app.quote.breaker import breaker_global


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


def executar_job(
    s: Session,
    conversation_id: str,
    req: QuoteRequest,
    *,
    chegada_do_lead: float | None = None,
    avisar=None,
) -> Quote:
    """Executa o job até resolver, com retry, backoff e breaker.

    `chegada_do_lead` é o `time.monotonic()` de quando a mensagem do lead entrou — o
    **relógio do lead**. Se contássemos do início da tool, o aviso chegaria depois de o
    lead já ter ficado 8 s no escuro, porque o turno gasta a latência do modelo antes.

    `avisar(texto)` entrega uma mensagem ao lead durante a espera. É opcional para que
    o job seja testável sem canal.
    """
    cfg = get_settings()
    br = breaker_global()
    t0 = chegada_do_lead if chegada_do_lead is not None else time.monotonic()

    q = criar_job(s, conversation_id, req)

    if not br.permite_chamada():
        # Sem nenhuma tentativa: não chamamos a API, então não sabemos se este lead
        # seria recusado. Afirmar recusa aqui seria adivinhar.
        return finalizar(s, q, status=QuoteJobStatus.FAILED,
                         erro=QuoteError(outcome=QuoteOutcome.TRANSIENT),
                         circuito_aberto=True)

    avisos = _Avisos(t0, avisar, cfg)
    total = 0
    erro: QuoteError | None = None

    for tentativa in range(1, cfg.quote_max_attempts + 1):
        resp = client.chamar(req)
        total += resp.latency_ms
        erro = None if resp.ok else resp.erro()
        gravar_tentativa(s, q.id, tentativa, resp, erro)

        if resp.ok:
            br.registrar_sucesso()
            avisos.cancelar()
            return finalizar(s, q, status=QuoteJobStatus.OK,
                             payload=QuotePayload.model_validate(resp.corpo),
                             latency_ms=total)

        if not erro.outcome.retentavel:
            # 400 e 422 (nas duas formas): a API respondeu, e a resposta é final.
            br.registrar_desfecho_de_negocio()
            avisos.cancelar()
            status = (QuoteJobStatus.REFUSED if erro.outcome is QuoteOutcome.REFUSED
                      else QuoteJobStatus.FAILED)
            return finalizar(s, q, status=status, erro=erro, latency_ms=total)

        br.registrar_falha_transitoria()
        if tentativa < cfg.quote_max_attempts:
            time.sleep(client.calcular_backoff(tentativa))

    avisos.cancelar()
    return finalizar(s, q, status=QuoteJobStatus.FAILED, erro=erro, latency_ms=total)


class _Avisos:
    """Aviso aos 6 s e reforço aos ~20 s, contados do relógio do LEAD.

    **São temporizadores, não verificações entre tentativas.** A primeira versão
    checava o relógio no topo de cada volta do laço, e um teste pegou o furo: a
    chamada lenta bloqueia 8 s numa tentativa só, então o aviso de 6 s só dispararia
    **depois** de o preço já ter chegado. Inútil justamente nos 10% do tráfego que a
    espera existe para cobrir.

    O disparo continua sendo **da tool**, e não de um watchdog na camada de conversa:
    o temporizador nasce e morre com o job, então ele só existe quando há de fato uma
    cotação em voo — e nunca dispara durante a geração do modelo.
    """

    def __init__(self, t0: float, avisar, cfg) -> None:
        self.avisar = avisar
        self.enviados: list[str] = []
        self._timers: list[threading.Timer] = []
        if avisar is None:
            return

        from app import textos

        # O relógio é o do lead: se ele já esperou 3 s antes de a tool começar, o
        # aviso sai 3 s depois daqui, não 6.
        decorrido = time.monotonic() - t0
        for nome, limiar, texto in (
            ("aviso", cfg.aviso_espera_s, textos.AVISO_ESPERA),
            ("reforco", cfg.reforco_espera_s, textos.REFORCO),
        ):
            atraso = max(0.0, limiar - decorrido)
            t = threading.Timer(atraso, self._disparar, args=(nome, texto))
            t.daemon = True
            t.start()
            self._timers.append(t)

    def _disparar(self, nome: str, texto: str) -> None:
        # O aviso sempre precede o reforço, mesmo se os dois vencerem juntos: receber
        # "ainda tô aqui" antes de "tô buscando" confundiria o lead.
        if nome == "reforco" and "aviso" not in self.enviados:
            return
        if nome in self.enviados:
            return
        self.enviados.append(nome)
        self.avisar(texto)

    def cancelar(self) -> None:
        """Chamado quando o job resolve: nada de aviso depois do preço."""
        for t in self._timers:
            t.cancel()
