"""`turn_usage` — custo e uso de tokens por turno.

Substitui o Langfuse (`docs/DECISOES-FECHADAS.md` §5): a informação fica na própria
base, disponível para quem rodar `docker compose up`, em vez de exigir seis containers
e ~5,6 GB de imagens para ser conferida.

**O custo é calculado na escrita, não na leitura.** Recalcular na leitura reescreveria
a história com o preço de hoje — um turno de junho passaria a custar o preço de
setembro. Por isso a vigência da entrada usada é gravada junto, e `/api/usage` só soma.

A Anthropic **não popula** o campo `cost` do Agno; calcular do nosso lado não é
preferência, é a única opção.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import uuid
from decimal import Decimal
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.persistence.models import Message, TurnUsage

_PRECOS: list[dict] | None = None
_ARQUIVO = Path(__file__).resolve().parents[2] / "config" / "model_pricing.yaml"


def tabela_de_precos() -> list[dict]:
    global _PRECOS
    if _PRECOS is None:
        _PRECOS = yaml.safe_load(_ARQUIVO.read_text())["modelos"] if _ARQUIVO.exists() else []
    return _PRECOS


def preco_de(model: str, hoje: dt.date | None = None) -> dict | None:
    """A entrada cuja vigência é a maior que não ultrapassa hoje, para aquele modelo.

    Casamento exato primeiro, depois glob (`ollama:*`).
    """
    hoje = hoje or dt.date.today()
    candidatos = [
        m for m in tabela_de_precos()
        if (m["id"] == model or fnmatch.fnmatch(model, m["id"]))
        and m.get("vigencia_a_partir_de") and m["vigencia_a_partir_de"] <= hoje
    ]
    if not candidatos:
        return None
    exatos = [m for m in candidatos if m["id"] == model]
    return max(exatos or candidatos, key=lambda m: m["vigencia_a_partir_de"])


def calcular_custo(model: str, m) -> tuple[Decimal | None, dt.date | None]:
    p = preco_de(model)
    if p is None or p.get("input") is None:
        # Inferência local não tem preço por token. NULL, nunca zero: zero afirmaria
        # que foi grátis.
        return None, None
    total = (
        (m.input_tokens or 0) * p["input"]
        + (m.output_tokens or 0) * p["output"]
        + (m.cache_read_tokens or 0) * (p.get("cache_read") or 0)
        + (m.cache_write_tokens or 0) * (p.get("cache_write") or 0)
    ) / 1_000_000
    return Decimal(str(round(total, 6))), p["vigencia_a_partir_de"]


def gravar_turn_usage(s: Session, conversation_id: str, r) -> TurnUsage | None:
    """Um turno = uma execução do agente = um `RunOutput`, cujo `metrics` é um
    `RunMetrics`. Não é por chamada de API: um turno com tool call faz várias, e o que
    interessa é o custo do turno."""
    m = getattr(r, "metrics", None)
    if m is None:
        return None

    ultima = s.execute(
        select(Message).where(Message.conversation_id == conversation_id)
        .order_by(Message.index.desc()).limit(1)
    ).scalar_one_or_none()
    if ultima is None:
        return None

    model = get_settings().llm_model
    provider = model.split(":", 1)[0]
    custo, vigencia = calcular_custo(model, m)

    # `cache_read`/`cache_write` ficam NULL quando o provider não reporta — o Ollama
    # não reporta. Zero diria "o cache não acertou" onde a verdade é "não existe cache
    # neste caminho", e o painel mostraria 0% em vez de "n/a".
    reporta_cache = provider == "anthropic"

    u = TurnUsage(
        id=f"tu_{uuid.uuid4().hex[:16]}",
        message_id=ultima.id,
        conversation_id=conversation_id,
        model=model,
        provider=provider,
        tokens_in=m.input_tokens or 0,
        tokens_out=m.output_tokens or 0,
        cache_read=(m.cache_read_tokens or 0) if reporta_cache else None,
        cache_write=(m.cache_write_tokens or 0) if reporta_cache else None,
        latency_ms=int((getattr(m, "duration", 0) or 0) * 1000),
        cost_usd=custo,
        pricing_vigencia=vigencia,
    )
    s.add(u)
    s.flush()
    return u
