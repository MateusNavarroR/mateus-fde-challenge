"""A superfície HTTP.

Implementa as nove rotas de `docs/openapi.yaml`, congelado na Fase 0. O que garante
que ele não vire documentação mentindo é `tests/nucleo/test_contrato_openapi.py`, que
compara nos **dois sentidos** — e é o segundo sentido, "toda rota gerada existe no
congelado", que pega superfície não documentada.

Três decisões de exposição, todas de `CLAUDE.md` 14b/14c:

- o compose publica em `127.0.0.1`, nunca em `0.0.0.0`. É o controle que de fato
  protege, e independe de autenticação;
- `ADMIN_TOKEN` é opcional: definido ⇒ exigido; ausente ⇒ sobe e avisa no log. Existe
  para que o achado do passe de segurança tenha resposta em código, desligada por
  padrão, em vez de "risco aceito" em prosa;
- `/docs`, `/redoc` e `/openapi.json` ficam **desligados** fora de desenvolvimento. O
  legado do desafio os expõe abertos; este serviço não repete esse default.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api import consultas
from app.api.schemas import (
    Conversation,
    ConversationDetail,
    ConversationSummary,
    Erro,
    HandoffOut,
    QuoteHealth,
    Usage,
)
from app.config import get_settings
from app.persistence import repo
from app.persistence.db import sessao_factory

log = logging.getLogger("autoseguro")

DEV = os.getenv("APP_ENV", "dev") == "dev"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if not s.admin_exigido:
        log.warning(
            "ADMIN_TOKEN não definido: /api/* está sem autenticação. "
            "A proteção efetiva é o bind em 127.0.0.1 do docker-compose.yml. "
            "Defina ADMIN_TOKEN para exigir o cabeçalho X-Admin-Token."
        )
    yield


app = FastAPI(
    title="AutoSeguro — backend do agente",
    version="0.1.0",
    lifespan=lifespan,
    # Fora de dev não há superfície de documentação aberta.
    docs_url="/docs" if DEV else None,
    redoc_url="/redoc" if DEV else None,
    openapi_url="/openapi.json" if DEV else None,
)


def sessao() -> Session:
    s = sessao_factory()()
    try:
        yield s
        s.commit()
    finally:
        s.close()


def exigir_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Exigido **apenas** quando `ADMIN_TOKEN` está definido."""
    cfg = get_settings()
    if cfg.admin_exigido and x_admin_token != cfg.admin_token:
        raise HTTPException(status_code=401, detail="token de admin inválido ou ausente")


# ─── saúde ───────────────────────────────────────────────────────────────────


@app.get("/api/health", tags=["operacao"], summary="Saúde do backend")
def health(s: Session = Depends(sessao)) -> dict:
    """Saúde **deste** serviço. Deliberadamente não reflete a saúde da `/quote`: o
    `/health` do legado responde 200 mesmo com 100% das cotações falhando, e confundir
    os dois é como se produz um monitor que mente."""
    try:
        s.execute(__import__("sqlalchemy").text("select 1"))
        db = "ok"
    except Exception:  # noqa: BLE001
        db = "degraded"
    return {"status": "ok", "db": db}


# ─── conversas ───────────────────────────────────────────────────────────────


@app.post("/api/conversations", tags=["chat"], status_code=201,
          response_model=Conversation, summary="Abre uma conversa")
def criar_conversa(corpo: dict, s: Session = Depends(sessao)) -> Conversation:
    c = repo.criar_conversa(
        s,
        channel=corpo.get("channel", "web"),
        # Nunca um telefone real: no console é o nome da sessão, no web o id do socket.
        external_ref=corpo.get("external_ref") or "web",
    )
    return Conversation(id=c.id, channel=c.channel, state=c.state, criado_em=c.criado_em)


@app.get("/api/conversations", tags=["rastreabilidade"], summary="Lista conversas")
def listar_conversas(
    state: str | None = None, limit: int = 50, cursor: str | None = None,
    s: Session = Depends(sessao), _: None = Depends(exigir_admin),
) -> dict:
    itens = consultas.resumo_conversas(s, state=state, limit=min(limit, 200))
    return {"items": [ConversationSummary(**i) for i in itens], "next_cursor": None}


@app.get("/api/conversations/{conversation_id}", tags=["rastreabilidade"],
         response_model=ConversationDetail, responses={404: {"model": Erro}},
         summary="Detalhe da conversa — mensagens e linha do tempo das cotações")
def detalhe_conversa(
    conversation_id: str, s: Session = Depends(sessao), _: None = Depends(exigir_admin)
):
    from app.api.montagem import montar_detalhe

    detalhe = montar_detalhe(s, conversation_id)
    if detalhe is None:
        return JSONResponse(status_code=404,
                            content={"error": "nao_encontrado", "message": conversation_id})
    return detalhe


# ─── operação ────────────────────────────────────────────────────────────────


@app.get("/api/quote-health", tags=["operacao"], response_model=QuoteHealth,
         summary="Saúde real da /quote")
def quote_health(janela: int = 50, s: Session = Depends(sessao),
                 _: None = Depends(exigir_admin)) -> QuoteHealth:
    from app.quote.breaker import breaker_global
    from app.quote.client import sondar_upstream

    return QuoteHealth(
        upstream_health=sondar_upstream(),
        janela=consultas.janela_de_tentativas(s, min(janela, 500)),
        breaker=breaker_global().estado_para_api(),
        ultimas_tentativas=consultas.ultimas_tentativas(s),
    )


@app.get("/api/usage", tags=["operacao"], response_model=Usage,
         summary="Custo e uso de tokens")
def usage(conversation_id: str | None = None, limit: int = 50,
          s: Session = Depends(sessao), _: None = Depends(exigir_admin)) -> Usage:
    """Alimenta o painel de custo. **Só soma** — o custo é calculado na escrita, com a
    vigência gravada junto; recalcular na leitura reescreveria a história com o preço
    de hoje."""
    return Usage(**consultas.usage(s, conversation_id, min(limit, 200)))


@app.get("/api/handoffs", tags=["operacao"], summary="Fila de handoff")
def listar_handoffs(status: str | None = None, limit: int = 50,
                    s: Session = Depends(sessao), _: None = Depends(exigir_admin)) -> dict:
    from app.api.montagem import montar_handoffs

    itens, pendentes = montar_handoffs(s, status, min(limit, 200))
    return {"items": itens, "pendentes": pendentes}


@app.patch("/api/handoffs/{handoff_id}", tags=["operacao"], response_model=HandoffOut,
           responses={404: {"model": Erro}, 409: {"model": Erro}},
           summary="Assume ou resolve um handoff")
def atualizar_handoff(handoff_id: str, corpo: dict, s: Session = Depends(sessao),
                      _: None = Depends(exigir_admin)):
    from app.api.montagem import transicionar_handoff

    return transicionar_handoff(s, handoff_id, corpo.get("status"))


# ─── websockets ──────────────────────────────────────────────────────────────

from app.channels.web import registrar_websockets  # noqa: E402

registrar_websockets(app)


@app.get("/", include_in_schema=False)
def raiz() -> Response:
    return Response(status_code=204)
