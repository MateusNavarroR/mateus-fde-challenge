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


def _cache_do_prompt(s: Session) -> dict:
    """A prova do prompt caching, com número — não com adjetivo.

    Duas leituras, e a segunda é a que importa:

    - **a fração do contexto que veio do cache**, que é a economia;
    - **quantos turnos leram ZERO**, que é o que distingue "o cache funciona dentro
      de uma conversa" de "o cache é do PREFIXO e atravessa conversas". Se o prefixo
      sobrevive, até o primeiro turno de uma conversa nova lê do cache, e esse número
      tende a zero. Medido no replay: 0 de 186.

    `cache_read` é anulável de propósito — o Ollama não reporta —, então provider que
    não reporta fica de fora da conta em vez de virar 0% e mentir.
    """
    linha = s.execute(
        select(
            func.count().label("turnos"),
            func.coalesce(func.sum(TurnUsage.tokens_in), 0).label("enviados"),
            func.coalesce(func.sum(TurnUsage.cache_read), 0).label("lidos"),
            func.count().filter(TurnUsage.cache_read == 0).label("zerados"),
        ).where(TurnUsage.cache_read.isnot(None))
    ).one()

    total = int(linha.enviados) + int(linha.lidos)
    return {
        "turnos_medidos": int(linha.turnos),
        "tokens_do_cache": int(linha.lidos),
        "tokens_enviados": int(linha.enviados),
        # `None`, e não 0: sem turno medido não há fração, e 0% diria que o cache
        # falhou onde a verdade é que não houve o que medir.
        "fracao_do_cache": round(linha.lidos / total, 4) if total else None,
        "turnos_sem_cache": int(linha.zerados),
    }


def _evals(s: Session) -> dict:
    """O que os módulos nativos do Agno gravaram em `ai.eval_runs`.

    A tabela é criada e escrita pelo próprio Agno, no schema `ai` — não é nossa, e por
    isso é lida por SQL cru em vez de por um modelo do SQLAlchemy que teríamos de
    manter em sincronia com uma dependência.

    Ausente a tabela, devolve zeros em silêncio: o painel não pode quebrar porque
    ninguém rodou avaliação ainda.

    **As duas classes reportam aprovação de formas diferentes**, e a consulta trata as
    duas: `ReliabilityResult` grava `eval_status`; `AgentAsJudgeResult` grava
    `pass_rate`. Contar só a primeira faria todo julgamento de texto aparecer como
    reprovado — o mesmo erro que o contador do replay cometeu, e que só apareceu
    quando alguém abriu o `eval_data` no banco.
    """
    from sqlalchemy import text as _sql

    try:
        linha = s.execute(_sql("""
            select
              count(*) as total,
              count(*) filter (
                where eval_data->>'eval_status' = 'PASSED'
                   or (eval_data->>'pass_rate')::numeric >= 100
              ) as passaram,
              count(*) filter (where eval_type = 'reliability') as reliability,
              count(*) filter (where eval_type = 'agent_as_judge') as juiz,
              max(created_at) as ultimo
            from ai.eval_runs
        """)).one()
    except Exception:  # noqa: BLE001 — tabela ainda não existe
        s.rollback()
        return {"total": 0, "passaram": 0, "reliability": 0, "juiz": 0, "ultimo": None}

    # `created_at` é epoch em segundos no schema do Agno — não um timestamp. Converter
    # aqui, e não na tela: a tela não tem por que conhecer o formato de uma dependência.
    ultimo = linha.ultimo
    quando = None
    if ultimo is not None:
        import datetime as _dt

        quando = _dt.datetime.fromtimestamp(int(ultimo), _dt.UTC).isoformat()

    return {
        "total": int(linha.total),
        "passaram": int(linha.passaram),
        # O RECORTE, como em todo número deste painel: "12 avaliações" não diz nada
        # sobre um sistema cujos dois avaliadores medem coisas incomparáveis — um
        # confere chamadas de tool por cálculo, o outro julga texto com um modelo.
        "reliability": int(linha.reliability),
        "juiz": int(linha.juiz),
        "ultimo": quando,
    }


def traces_da_conversa(s: Session, conversation_id: str) -> list[dict]:
    """O trace de cada resposta do agente: as tools que ela executou, em ordem.

    **A fonte já existia e ninguém lia.** `ai.agno_runs.run_data` guarda, por resposta,
    cada `ToolExecution` com nome, argumentos, resultado, duração e erro — e as métricas
    do turno. Isso é granularidade de CHAMADA, que `turn_usage` (granularidade de turno)
    não tem: um turno em que o agente qualifica e cota aparece como uma linha só na
    tabela de custo e como duas execuções distintas aqui.

    Por isso o painel não precisa de OpenTelemetry para responder "o que o agente fez
    nesta resposta". O `setup_tracing()` do Agno existe e daria spans mais finos, mas
    custaria três dependências novas — e o item 17 do `CLAUDE.md` diz que nenhuma
    observabilidade é dependência.

    Tabela do Agno, fora das nossas migrações ⇒ SQL cru, como em `_evals()`, e um
    `except` que devolve lista vazia: uma instalação que nunca rodou o agente não tem a
    tabela, e o detalhe da conversa não pode quebrar por causa disso.

    **`tool_args` é MASCARADO na saída, e essa linha é o ponto mais importante daqui.**
    O Agno grava os argumentos como o modelo os escreveu — com o CEP cru, porque é o
    que a `/quote` precisa receber. Toda a aplicação mascara PII na escrita
    (`app/privacy/mascarar.py`); esta tabela é a exceção, porque quem escreve nela é uma
    dependência, não nós. Servir isso sem mascarar publicaria pela porta dos fundos
    exatamente o dado que o resto do sistema protege.
    """
    from sqlalchemy import text as _sql

    from app.privacy.mascarar import mascarar

    try:
        linhas = s.execute(_sql("""
            select run_id, run_index, status, run_data
              from ai.agno_runs
             where session_id = :sid
             order by run_index asc
        """), {"sid": conversation_id}).all()
    except Exception:  # noqa: BLE001 — a tabela é do Agno e pode não existir
        s.rollback()
        return []

    def _limpar(valor):
        """Mascara recursivamente qualquer string dentro dos argumentos."""
        if isinstance(valor, str):
            return mascarar(valor)
        if isinstance(valor, dict):
            return {k: _limpar(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [_limpar(v) for v in valor]
        return valor

    saida = []
    for linha in linhas:
        dados = linha.run_data or {}
        metricas = dados.get("metrics") or {}
        tools = []
        for t in dados.get("tools") or []:
            m = t.get("metrics") or {}
            tools.append({
                "nome": t.get("tool_name") or "?",
                "argumentos": _limpar(t.get("tool_args") or {}),
                "resultado": mascarar(t.get("result") or "") or "",
                "duracao_ms": round((m.get("duration") or 0.0) * 1000, 1),
                "erro": bool(t.get("tool_call_error")),
            })
        saida.append({
            "run_id": linha.run_id,
            "index": linha.run_index,
            "status": linha.status or "?",
            "modelo": dados.get("model") or "",
            "provider": dados.get("model_provider") or "",
            "tokens_in": int(metricas.get("input_tokens") or 0),
            "tokens_out": int(metricas.get("output_tokens") or 0),
            "cache_read": metricas.get("cache_read_tokens"),
            "duracao_ms": round((metricas.get("duration") or 0.0) * 1000, 1),
            "tools": tools,
        })
    return saida


def resumo_operacao(s: Session) -> dict:
    """Os números do painel, numa consulta por métrica em vez de contar no cliente.

    Contar do lado da tela exigiria paginar a lista inteira — o `/api/conversations`
    devolve no máximo 200 —, e um painel que mente por paginação é pior que nenhum.

    **O recorte de cada número é uma decisão, não uma agregação óbvia:**

    - *mensagens enviadas* conta o que SAIU (`agente` e `sistema`), não o total. O que
      o operador quer saber é quanto o agente falou, e somar a fala do lead dobraria o
      número sem significar nada;
    - *cotações* separa `ok` de `refused` de `failed`. Um total só esconderia
      exatamente a distinção que o produto existe para tratar: recusa é desfecho de
      negócio, falha é indisponibilidade;
    - *handoffs* separa pendentes do total, porque pendente é fila e total é volume.
    """
    def _n(consulta) -> int:
        return int(s.execute(consulta).scalar_one() or 0)

    por_status = {
        linha[0]: int(linha[1])
        for linha in s.execute(
            select(Quote.status, func.count()).group_by(Quote.status)
        )
    }

    return {
        "conversas": _n(select(func.count()).select_from(Conversation)),
        "conversas_encaminhadas": _n(
            select(func.count()).select_from(Conversation)
            .where(Conversation.state == "encaminhado")
        ),
        "mensagens_enviadas": _n(
            select(func.count()).select_from(Message)
            .where(Message.autor.in_(("agente", "sistema")))
        ),
        "mensagens_recebidas": _n(
            select(func.count()).select_from(Message).where(Message.autor == "lead")
        ),
        "cotacoes_ok": por_status.get("ok", 0),
        "cotacoes_recusadas": por_status.get("refused", 0),
        "cotacoes_falhas": por_status.get("failed", 0),
        "handoffs_pendentes": _n(
            select(func.count()).select_from(Handoff).where(Handoff.status == "pendente")
        ),
        "handoffs_total": _n(select(func.count()).select_from(Handoff)),
        "cache": _cache_do_prompt(s),
        "evals": _evals(s),
    }
