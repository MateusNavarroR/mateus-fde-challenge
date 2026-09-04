"""Montagem das respostas compostas.

Fica separado dos routers porque é a tradução entre o modelo de dados e o contrato —
e é onde o guardrail vira coisa visível: uma mensagem com valor monetário e `quote_id`
nulo é marcada, em vez de silenciada.
"""

from __future__ import annotations

import datetime as dt

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    ConversationDetail,
    HandoffOut,
    LeadProfileOut,
    MessageOut,
    QuoteOut,
    QuoteResultadoOut,
)
from app.contracts.conversa import CAMPOS_QUALIFICACAO
from app.persistence.models import Conversation, Handoff, Message, Quote

TRANSICOES = {
    ("pendente", "assumido"),
    ("pendente", "resolvido"),
    ("assumido", "resolvido"),
}


def _quote_out(q: Quote) -> QuoteOut:
    resultado = None
    if q.status == "ok" and q.payload:
        p = q.payload
        pr = p.get("primeiro_pagamento_pro_rata")
        resultado = QuoteResultadoOut(
            premio_mensal=p["premio_mensal"], franquia=p["franquia"],
            moeda=p["moeda"], coberturas=p["coberturas"], carencia=p["carencia"],
            pro_rata=pr,
        )
    return QuoteOut(
        id=q.id, status=q.status,
        request={
            "plano_id": q.req_plano_id, "idade": q.req_idade,
            "veiculo_ano": q.req_veiculo_ano, "cep": q.req_cep,
            "data_inicio": q.req_data_inicio,
        },
        resultado=resultado, motivo_recusa=q.motivo_recusa,
        erro_outcome=q.erro_outcome, circuito_aberto=q.circuito_aberto,
        total_latency_ms=q.total_latency_ms,
        attempts=[
            {"id": a.id, "attempt": a.attempt, "http_status": a.http_status,
             "latency_ms": a.latency_ms, "outcome": a.outcome, "criado_em": a.criado_em}
            for a in q.attempts
        ],
        criado_em=q.criado_em,
    )


def _handoff_out(h: Handoff, s: Session) -> HandoffOut:
    ultima = s.get(Quote, h.quote_id) if h.quote_id else None
    return HandoffOut(
        id=h.id, conversation_id=h.conversation_id, trigger=h.trigger,
        reason=h.reason, summary=h.summary, disparado_por=h.disparado_por,
        quote_id=h.quote_id,
        ultima_cotacao=_quote_out(ultima) if ultima else None,
        status=h.status, criado_em=h.criado_em, assumido_em=h.assumido_em,
        resolved_at=h.resolved_at,
    )


def montar_detalhe(s: Session, conversation_id: str) -> ConversationDetail | None:
    c = s.get(Conversation, conversation_id)
    if c is None:
        return None

    perfil = LeadProfileOut(
        idade=c.idade, veiculo_ano=c.veiculo_ano, cep=c.cep,
        data_inicio=c.data_inicio, plano_id=c.plano_id,
        campos_faltantes=[k for k in CAMPOS_QUALIFICACAO if getattr(c, k) is None],
    )
    # Ordenado por `index`, NUNCA por timestamp.
    msgs = list(s.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.index)
    ).scalars())
    quotes = list(s.execute(
        select(Quote).where(Quote.conversation_id == conversation_id)
        .order_by(Quote.criado_em)
    ).scalars())
    handoffs = list(s.execute(
        select(Handoff).where(Handoff.conversation_id == conversation_id)
        .order_by(Handoff.criado_em)
    ).scalars())

    return ConversationDetail(
        id=c.id, channel=c.channel, state=c.state, criado_em=c.criado_em,
        perfil=perfil,
        messages=[
            MessageOut(id=m.id, index=m.index, autor=m.autor, tipo=m.tipo,
                       conteudo=m.conteudo, status=m.status, quote_id=m.quote_id,
                       criado_em=m.criado_em)
            for m in msgs
        ],
        quotes=[_quote_out(q) for q in quotes],
        handoffs=[_handoff_out(h, s) for h in handoffs],
    )


def montar_handoffs(s: Session, status: str | None, limit: int) -> tuple[list, int]:
    q = select(Handoff).order_by(Handoff.criado_em.desc()).limit(limit)
    if status:
        q = q.where(Handoff.status == status)
    itens = [_handoff_out(h, s) for h in s.execute(q).scalars()]
    pendentes = s.execute(
        select(func.count()).select_from(Handoff).where(Handoff.status == "pendente")
    ).scalar()
    return itens, pendentes


def transicionar_handoff(s: Session, handoff_id: str, novo: str | None):
    h = s.get(Handoff, handoff_id)
    if h is None:
        return JSONResponse(status_code=404,
                            content={"error": "nao_encontrado", "message": handoff_id})
    if (h.status, novo) not in TRANSICOES:
        return JSONResponse(
            status_code=409,
            content={"error": "transicao_invalida",
                     "message": f"{h.status} → {novo} não é uma transição válida"},
        )
    h.status = novo
    agora = dt.datetime.now(dt.UTC)
    if novo == "assumido":
        h.assumido_em = agora
    if novo == "resolvido":
        h.resolved_at = agora
    s.flush()
    return _handoff_out(h, s)
