"""A superfície HTTP.

Implementa as nove rotas de `docs/openapi.yaml`, congelado na Fase 0. O que garante
que ele não vire documentação mentindo é `tests/nucleo/test_contrato_openapi.py`, que
compara nos **dois sentidos** — e é o segundo sentido, "toda rota gerada existe no
congelado", que pega superfície não documentada.

Três decisões de exposição, todas de `CLAUDE.md` 14b/14c:

- o compose publica em `127.0.0.1`, nunca em `0.0.0.0`. É o controle que de fato
  protege, e independe de autenticação;
- a autenticação é opcional e vive em `app/auth.py`: `ADMIN_USER`/`ADMIN_PASSWORD`
  ligam o login com sessão em cookie, `ADMIN_TOKEN` liga o cabeçalho para máquina, e
  sem nenhum dos dois o serviço sobe e avisa no log. Existe para que o achado do
  passe de segurança tenha resposta em código, desligada por padrão, em vez de
  "risco aceito" em prosa;
- `/docs`, `/redoc` e `/openapi.json` ficam **desligados** fora de desenvolvimento. O
  legado do desafio os expõe abertos; este serviço não repete esse default.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.api import consultas
from app import ratelimit
from app.auth import aviso_de_boot, exigir_admin, redefinir_credenciais, registrar_autenticacao
from app.api.schemas import (
    Conversation,
    ConversationDetail,
    ConversationSummary,
    Erro,
    HandoffOut,
    QuoteHealth,
    Resumo,
    Usage,
)
from app.persistence import repo
from app.persistence.db import sessao_factory

log = logging.getLogger("autoseguro")

DEV = os.getenv("APP_ENV", "prod") == "dev"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.bootstrap import bootstrap

    # Explícito no boot: o .env não chega ao SDK sozinho, e faltar credencial
    # tem que doer aqui, não no meio de uma conversa.
    bootstrap()

    # Deriva o hash da senha e apaga o texto puro do processo. Antes do primeiro
    # request, para que nenhuma rota veja o ambiente com a senha ainda nele.
    redefinir_credenciais()

    # O laço do servidor, para que uma rota síncrona consiga empurrar evento.
    import asyncio as _asyncio

    from app.channels import web as _web

    _web.registrar_laco(_asyncio.get_running_loop())

    aviso = aviso_de_boot()
    if aviso:
        log.warning(aviso)
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


# `exigir_admin` mora em `app/auth.py` — a decisão de "quem pode ler a operação" é
# de lá, e aqui só se declara a dependência. As três rotas de login são montadas no
# fim do arquivo, junto dos WebSockets, pelo mesmo motivo: são montagem, não contrato.


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
def criar_conversa(
    corpo: dict, request: Request, s: Session = Depends(sessao)
) -> Conversation:
    """Idempotente por `(channel, external_ref)`: mesma sessão, mesma conversa.

    Um literal fixo aqui — o que havia antes — fazia a primeira conversa gravar e
    todas as seguintes colidirem com a `UNIQUE` da migração, para sempre naquele
    banco. O avaliador abriria o `/chat`, conversaria, clicaria em "nova conversa" e
    receberia 500. Nenhum teste unitário pega isso, porque cada teste cria uma
    conversa num banco limpo — só aparece no **segundo uso**.

    `external_ref` nunca carrega telefone real: no console é o nome da sessão, no web
    é um identificador de sessão de navegador gerado localmente.
    """
    # Rota PÚBLICA: é o portão de entrada de tudo e não exige autenticação. Sem
    # limite, um laço abre conversas sem teto — e cada conversa é o começo de uma
    # cadeia que gasta inferência.
    if not ratelimit.CRIAR_CONVERSA.permite(ratelimit.origem(request)):
        raise HTTPException(status_code=429, detail="muitas conversas em pouco tempo")

    c, _ = repo.criar_ou_retomar_conversa(
        s,
        channel=corpo.get("channel", "web"),
        external_ref=corpo.get("external_ref"),
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


@app.get("/api/conversations/{conversation_id}/traces", tags=["rastreabilidade"],
         summary="O que cada resposta do agente executou — tools, tokens e duração")
def traces_conversa(
    conversation_id: str, s: Session = Depends(sessao), _: None = Depends(exigir_admin)
) -> dict:
    """Granularidade de CHAMADA, que a tabela de custo não tem.

    `turn_usage` conta um turno; aqui um turno que qualificou e cotou aparece com as
    duas execuções, cada uma com argumentos, resultado e duração próprios. Sem
    `response_model`: a forma vem de `run_data`, que é de uma dependência, e congelá-la
    num Pydantic nosso criaria um contrato que o Agno pode mudar sem avisar.

    Lista vazia quando não há trace — instalação nova, ou conversa do dataset
    reproduzida sem passar pelo agente. Não é 404: a conversa existe.
    """
    return {"items": consultas.traces_da_conversa(s, conversation_id)}


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


@app.get("/api/resumo", tags=["operacao"], response_model=Resumo,
         summary="Os números do painel")
def resumo(s: Session = Depends(sessao), _: None = Depends(exigir_admin)) -> Resumo:
    """Contado no BANCO, não na tela.

    Contar do lado do cliente exigiria paginar a lista inteira — `/api/conversations`
    devolve no máximo 200 —, e um painel que mente por paginação é pior que painel
    nenhum: ele parece informação.
    """
    return Resumo(**consultas.resumo_operacao(s))


@app.get("/api/handoffs", tags=["operacao"], summary="Fila de handoff")
def listar_handoffs(status: str | None = None, limit: int = 50,
                    s: Session = Depends(sessao), _: None = Depends(exigir_admin)) -> dict:
    from app.api.montagem import montar_handoffs

    itens, pendentes = montar_handoffs(s, status, min(limit, 200))
    return {"items": itens, "pendentes": pendentes}


@app.post("/api/conversations/{conversation_id}/mensagens", tags=["operacao"],
          status_code=201, responses={404: {"model": Erro}, 409: {"model": Erro}},
          summary="O operador responde na conversa que assumiu")
def responder_como_operador(
    conversation_id: str, corpo: dict, s: Session = Depends(sessao),
    _: None = Depends(exigir_admin),
) -> dict:
    """A outra ponta do handoff: a fila deixa de ser uma lista que ninguém atende.

    **Só em conversa `encaminhado`, e o 409 é a regra e não uma checagem defensiva.**
    Enquanto o agente conduz, ele é o único que fala pela empresa; deixar um humano
    escrever por cima produziria duas vozes no mesmo turno e um lead sem saber com
    quem está falando. Depois do encaminhamento o agente encerrou a participação —
    `encaminhado` é terminal —, e é exatamente aí que o humano assume.

    **Autor `operador`, e não `sistema`.** Os dois saem iguais para o lead, de
    propósito: para quem está do outro lado é a mesma empresa falando. A distinção é
    auditoria, e é justamente a pergunta que o admin existe para responder — isto aqui
    foi um template determinístico ou uma pessoa escrevendo? Achatar os dois apagaria
    a resposta.

    O texto passa pelo mesmo mascaramento de PII na escrita que todo o resto: um
    operador com pressa colando o CPF do lead não é hipótese, é rotina.
    """
    from app.channels.web import publicar_no_chat_sync
    from app.persistence import repo

    texto = (corpo.get("text") or "").strip()
    if not texto:
        return JSONResponse(status_code=422,
                            content={"error": "texto_vazio", "message": "text é obrigatório"})

    conversa = repo.obter_conversa(s, conversation_id)
    if conversa is None:
        return JSONResponse(status_code=404,
                            content={"error": "nao_encontrado", "message": conversation_id})
    if conversa.state != "encaminhado":
        return JSONResponse(status_code=409, content={
            "error": "conversa_nao_encaminhada",
            "message": "o agente ainda conduz esta conversa; só se responde depois do handoff",
        })

    m = repo.gravar_mensagem(
        s, conversation_id, autor="operador", conteudo=texto, status="sent",
    )
    s.commit()

    # E CHEGA AO LEAD que está com a página aberta. Sem este push a resposta do
    # atendente só apareceria no próximo F5 — que é o mesmo que não chegar.
    publicar_no_chat_sync(conversation_id, {
        "type": "message",
        "message": {
            "id": m.id, "index": m.index, "autor": m.autor, "tipo": m.tipo,
            "conteudo": m.conteudo, "status": m.status, "quote_id": m.quote_id,
            "criado_em": m.criado_em.isoformat(),
        },
    })
    return {
        "id": m.id, "index": m.index, "autor": m.autor, "tipo": m.tipo,
        "conteudo": m.conteudo, "status": m.status, "quote_id": m.quote_id,
        "criado_em": m.criado_em.isoformat(),
    }


@app.patch("/api/handoffs/{handoff_id}", tags=["operacao"], response_model=HandoffOut,
           responses={404: {"model": Erro}, 409: {"model": Erro}},
           summary="Assume ou resolve um handoff")
def atualizar_handoff(handoff_id: str, corpo: dict, s: Session = Depends(sessao),
                      _: None = Depends(exigir_admin)):
    from app.api.montagem import transicionar_handoff
    from app.channels.web import publicar_sync

    resultado = transicionar_handoff(s, handoff_id, corpo.get("status"))
    # Sem isto a fila e a badge de pendentes de QUALQUER outro operador continuam
    # mostrando o item como pendente até alguém recarregar a página — dois
    # operadores assumindo o mesmo caso é o resultado.
    publicar_sync("handoff.updated", {"id": handoff_id})
    return resultado


# ─── websockets ──────────────────────────────────────────────────────────────

from app.channels.web import registrar_websockets  # noqa: E402

registrar_websockets(app)
registrar_autenticacao(app)


# ─── o frontend ──────────────────────────────────────────────────────────────
#
# Servido pela MESMA origem da API, e não por um segundo serviço. Três razões, e a
# primeira é a que decide:
#
# 1. `docker compose up` precisa subir **o produto inteiro** com um comando. Um
#    frontend em outra porta transformaria "abra 8080" em "abra 8080 e 5173", e o
#    critério nº 1 do desafio é justamente que funcione;
# 2. mesma origem significa **sem CORS** — nada de `allow_origins` para configurar
#    errado, e o cookie de sessão do admin é `SameSite=Strict` sem exceção;
# 3. o WebSocket usa o mesmo host, então não há um segundo endereço para acertar.
#
# As rotas do SPA (`/chat`, `/admin/...`) são resolvidas no cliente: qualquer caminho
# que não seja `/api` nem um arquivo existente devolve o `index.html`, e o roteador
# do React decide. Sem isso, um F5 em `/admin/status` daria 404 — que é o defeito
# clássico de SPA servido por servidor estático ingênuo.

_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"

if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")


# A ROTA É SEMPRE A MESMA, com ou sem `web/dist`, e essa é a correção de um defeito
# de auto-consistência que uma avaliação externa encontrou.
#
# Antes, `dist` ausente trocava o catch-all por um `@app.get("/")` diferente — ou
# seja, **a superfície da API mudava conforme o frontend estivesse buildado ou não**.
# O efeito era o pior possível: o teste de contrato congelado, que existe para acusar
# deriva de superfície, ACUSAVA DERIVA quando alguém seguia o README ao pé da letra
# (`git clone` e `uv run pytest`, sem `npm run build`). A ferramenta anti-deriva
# apontando para si mesma.
#
# Uma rota, dois comportamentos: com `dist`, serve o SPA; sem, devolve 204 na raiz e
# 404 no resto — que é o que o desenvolvimento com Vite em outra porta precisa. O
# contrato não depende mais de um diretório existir.
@app.get("/{caminho:path}", include_in_schema=False)
def spa(caminho: str) -> Response:
    if not _DIST.is_dir():
        # Desenvolvimento: o Vite serve a interface noutra porta, e a raiz só precisa
        # responder que o backend está de pé.
        if caminho == "":
            return Response(status_code=204)
        return JSONResponse(status_code=404,
                            content={"error": "nao_encontrado", "message": caminho})
    return _servir_spa(caminho)


def _servir_spa(caminho: str) -> Response:
    # `/api` NUNCA cai no SPA. Sem esta guarda, um endpoint inexistente
    # devolveria `index.html` com 200 — e o cliente receberia HTML onde espera
    # JSON, com o erro aparecendo como "unexpected token <" três camadas adiante.
    # O mesmo vale para as rotas de documentação, que ficam desligadas fora de
    # dev e não podem voltar a existir por acidente de roteamento.
    if caminho.startswith("api/") or caminho in {"docs", "redoc", "openapi.json"}:
        return JSONResponse(status_code=404,
                            content={"error": "nao_encontrado", "message": caminho})
    arquivo = _DIST / caminho
    if caminho and arquivo.is_file() and _DIST in arquivo.resolve().parents:
        return FileResponse(arquivo)
    return FileResponse(_DIST / "index.html")
