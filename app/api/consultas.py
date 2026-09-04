"""Consultas de leitura para as telas de administração.

Ficam separadas dos routers porque são SQL, e SQL misturado com roteamento é onde a
lógica de agregação some. `/api/usage` em particular **só soma** — ele nunca abre
`config/model_pricing.yaml`: o custo é calculado na escrita, com a vigência gravada
junto, senão um turno de junho passaria a custar o preço de setembro.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.persistence.models import (
    Conversation,
    Handoff,
    Message,
    Quote,
    QuoteAttempt,
    TurnUsage,
)


def _percentil(valores: list[int], p: float) -> int:
    if not valores:
        return 0
    ordenados = sorted(valores)
    i = min(int(round(p * (len(ordenados) - 1))), len(ordenados) - 1)
    return ordenados[i]


def janela_de_tentativas(s: Session, n: int = 50) -> dict:
    linhas = list(
        s.execute(
            select(QuoteAttempt).order_by(QuoteAttempt.criado_em.desc()).limit(n)
        ).scalars()
    )
    lat = [a.latency_ms for a in linhas]
    por_outcome: dict[str, int] = {}
    for a in linhas:
        por_outcome[a.outcome] = por_outcome.get(a.outcome, 0) + 1
    sucesso = por_outcome.get("ok", 0)
    return {
        "total": len(linhas),
        "sucesso": sucesso,
        "taxa_sucesso": (sucesso / len(linhas)) if linhas else 0.0,
        "p50_ms": _percentil(lat, 0.50),
        "p95_ms": _percentil(lat, 0.95),
        "por_outcome": por_outcome,
    }


def ultimas_tentativas(s: Session, n: int = 20) -> list[dict]:
    linhas = s.execute(
        select(QuoteAttempt, Quote.conversation_id)
        .join(Quote, Quote.id == QuoteAttempt.quote_id)
        .order_by(QuoteAttempt.criado_em.desc())
        .limit(n)
    ).all()
    return [
        {
            "id": a.id, "attempt": a.attempt, "http_status": a.http_status,
            "latency_ms": a.latency_ms, "outcome": a.outcome, "criado_em": a.criado_em,
            "quote_id": a.quote_id, "conversation_id": conv_id,
        }
        for a, conv_id in linhas
    ]


def _agregar(linhas: list[TurnUsage]) -> dict:
    """`cache_read` nulo é **excluído** do denominador, e se o grupo inteiro for nulo
    a taxa vem `None` — a tela mostra "n/a", nunca "0 %"."""
    com_cache = [u for u in linhas if u.cache_read is not None]
    cache_read = sum(u.cache_read for u in com_cache) if com_cache else None
    cache_write = (
        sum(u.cache_write or 0 for u in com_cache) if com_cache else None
    )
    tokens_in_cacheaveis = sum(u.tokens_in for u in com_cache)
    taxa = None
    if com_cache and (cache_read + tokens_in_cacheaveis) > 0:
        # A Anthropic reporta `input_tokens` já SEM os lidos de cache.
        taxa = cache_read / (cache_read + tokens_in_cacheaveis)

    com_custo = [u for u in linhas if u.cost_usd is not None]
    lat = [u.latency_ms for u in linhas]
    return {
        "tokens_in": sum(u.tokens_in for u in linhas),
        "tokens_out": sum(u.tokens_out for u in linhas),
        "cache_read": cache_read,
        "cache_write": cache_write,
        "taxa_acerto_cache": taxa,
        "custo_usd": float(sum(u.cost_usd for u in com_custo)) if com_custo else None,
        "pricing_vigencia": max((u.pricing_vigencia for u in com_custo), default=None),
        "latency_p50_ms": _percentil(lat, 0.50) if lat else None,
    }


def usage(s: Session, conversation_id: str | None = None, limit: int = 50) -> dict:
    q = select(TurnUsage)
    if conversation_id:
        q = q.where(TurnUsage.conversation_id == conversation_id)
    linhas = list(s.execute(q).scalars())

    por_provider: dict[str, list[TurnUsage]] = {}
    por_conversa: dict[str, list[TurnUsage]] = {}
    for u in linhas:
        por_provider.setdefault(u.provider, []).append(u)
        por_conversa.setdefault(u.conversation_id, []).append(u)

    return {
        "total": _agregar(linhas),
        "por_provider": [
            {"provider": p, **_agregar(v)} for p, v in sorted(por_provider.items())
        ],
        "por_conversa": [
            {"conversation_id": c, "turnos": len(v), **_agregar(v)}
            for c, v in list(por_conversa.items())[:limit]
        ],
    }


def resumo_conversas(s: Session, state: str | None = None, limit: int = 50) -> list[dict]:
    q = select(Conversation).order_by(Conversation.atualizado_em.desc()).limit(limit)
    if state:
        q = q.where(Conversation.state == state)
    saida = []
    for c in s.execute(q).scalars():
        msgs = list(
            s.execute(
                select(Message).where(Message.conversation_id == c.id).order_by(Message.index)
            ).scalars()
        )
        ultima_cot = s.execute(
            select(Quote).where(Quote.conversation_id == c.id)
            .order_by(Quote.criado_em.desc()).limit(1)
        ).scalar_one_or_none()
        pendente = s.execute(
            select(func.count()).select_from(Handoff)
            .where(Handoff.conversation_id == c.id, Handoff.status == "pendente")
        ).scalar()
        saida.append({
            "id": c.id, "channel": c.channel, "state": c.state, "criado_em": c.criado_em,
            "total_mensagens": len(msgs), "atualizado_em": c.atualizado_em,
            "ultima_mensagem": msgs[-1].conteudo if msgs else None,
            "handoff_pendente": bool(pendente),
            "ultima_cotacao_status": ultima_cot.status if ultima_cot else None,
        })
    return saida
