"""Adaptador `web` da porta `ChannelAdapter`, sobre WebSocket.

**O problema que ele resolve:** a tool de cotação bloqueia até o job resolver — até
~37 s no pior caso — e fala durante a espera. Aviso aos 6 s, reforço aos ~20 s, e o
bloco da cotação quando resolve. São **três mensagens separadas que aparecem enquanto
o turno não terminou**.

O WebSocket não é request/response, então não há acoplamento a desfazer: quem chama
`send()` no meio do turno é a tool, e o frame sai na hora.

Ordem dos frames num turno degradado:

    1. MessageEvent  autor=lead      eco com o id e o `index` canônicos
    2. TypingEvent   ativo=true      ao adquirir o lock do turno
    3. MessageEvent  autor=sistema   aviso, aos 6 s          ← da tool
    4. MessageEvent  autor=sistema   reforço, aos ~20 s      ← da tool
    5. MessageEvent  autor=sistema   bloco da cotação        ← da tool, com quote_id
    6. MessageEvent  autor=agente    só quando há texto do modelo
    7. StateEvent                    na mudança de estado
    8. TypingEvent   ativo=false     ao liberar o lock

O indicador de digitando **permanece** entre 2 e 8, inclusive enquanto 3, 4 e 5 chegam:
é o que comunica "ainda estou trabalhando" e a diferença entre "travou" e "está
tentando".

**Reconexão é obrigatória** por causa da janela de 37 s. Ao conectar, o cliente manda
`{"type":"hello","last_index":N}` e o servidor reenvia de `messages` tudo com
`index > N` — do **banco**, não de um buffer em memória.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.persistence import repo
from app.persistence.db import sessao_factory

log = logging.getLogger("autoseguro.web")


@dataclass
class WebChannelAdapter:
    """Implementa a porta. Um adaptador por conexão."""

    ws: WebSocket
    name: str = "web"
    enviadas: list[dict] = field(default_factory=list)

    async def send(self, conversation_id: str, text: str, *, message_id: str,
                   quote_id: str | None = None, autor: str = "agente",
                   index: int = 0, status: str = "sent",
                   tipo: str = "text") -> str:
        frame = {
            "type": "message",
            "message": {
                "id": message_id, "index": index, "autor": autor, "tipo": tipo,
                "conteudo": text, "status": status, "quote_id": quote_id,
            },
        }
        self.enviadas.append(frame["message"])
        await self.ws.send_text(json.dumps(frame, ensure_ascii=False))
        return f"web:{message_id}"

    async def typing(self, conversation_id: str, *, ativo: bool) -> None:
        """Visível aqui — é nesta tela que ele existe. No console é no-op.

        Falhar aqui nunca interrompe o turno: é sinalização, não conteúdo.
        """
        try:
            await self.ws.send_text(json.dumps({"type": "typing", "ativo": ativo}))
        except Exception:  # noqa: BLE001
            log.debug("typing perdido; o turno segue")

    async def estado(self, state: str) -> None:
        await self.ws.send_text(json.dumps({"type": "state", "state": state}))

    async def receive(self) -> AsyncIterator[dict]:  # pragma: no cover
        while True:
            yield json.loads(await self.ws.receive_text())


#: Os tipos que o canal aceita — o espelho do enum `message_tipo` do banco.
_TIPOS = frozenset({"text", "image", "audio", "document"})

#: Conexões de administração, para o push de `/api/events`.
_admin: set[WebSocket] = set()

#: O laço do servidor, capturado no boot. Uma rota síncrona roda no threadpool do
#: AnyIO e não tem laço próprio: `get_event_loop()` de lá devolveria outro laço, ou
#: nada. Guardar o certo no startup é a única forma de o push sair de uma rota `def`.
_laco: asyncio.AbstractEventLoop | None = None


def registrar_laco(laco: asyncio.AbstractEventLoop) -> None:
    global _laco
    _laco = laco


async def publicar_evento(tipo: str, dados: dict) -> None:
    """`handoff.created`, `handoff.updated`, `quote.attempt`.

    É o que faz um handoff criado no backend aparecer na fila **sem recarregar a
    página** — comportamento que a evidência de UI precisa provar.
    """
    frame = json.dumps({"type": tipo, "data": dados}, ensure_ascii=False, default=str)
    mortos = []
    for ws in _admin:
        try:
            await ws.send_text(frame)
        except Exception:  # noqa: BLE001
            mortos.append(ws)
    for ws in mortos:
        _admin.discard(ws)


def publicar_sync(tipo: str, dados: dict) -> None:
    """`publicar_evento` a partir de uma rota **síncrona**.

    As rotas de operação são `def`, então correm no threadpool do AnyIO e não têm
    laço de eventos próprio. `run_coroutine_threadsafe` marshala para o laço do
    servidor; sem esperar o resultado, porque um push perdido nunca pode atrasar ou
    derrubar a resposta HTTP que o operador está esperando.

    Falhar aqui é silencioso de propósito: o push é conveniência, e a tela recarrega
    do endpoint de qualquer forma.
    """
    if _laco is None:  # sem servidor rodando: teste de unidade, script
        return
    try:
        asyncio.run_coroutine_threadsafe(publicar_evento(tipo, dados), _laco)
    except Exception:  # noqa: BLE001  # pragma: no cover
        log.debug("push perdido; a tela recarrega do endpoint")


def registrar_websockets(app: FastAPI) -> None:
    @app.websocket("/api/chat/{conversation_id}")
    async def chat(ws: WebSocket, conversation_id: str) -> None:
        await ws.accept()
        adaptador = WebChannelAdapter(ws)
        fabrica = sessao_factory()

        with fabrica() as s:
            if repo.obter_conversa(s, conversation_id) is None:
                await ws.close(code=4404)
                return

        try:
            while True:
                bruto = await ws.receive_text()
                msg = json.loads(bruto)

                if msg.get("type") == "hello":
                    # Replay a partir do BANCO: o que saiu durante uma queda de socket
                    # numa janela de 37 s não pode se perder.
                    ultimo = int(msg.get("last_index", -1))
                    with fabrica() as s:
                        for m in repo.mensagens(s, conversation_id):
                            if m.index > ultimo:
                                await adaptador.send(
                                    conversation_id, m.conteudo, message_id=m.id,
                                    quote_id=m.quote_id, autor=m.autor,
                                    index=m.index, status=m.status,
                                )
                    continue

                if msg.get("type") != "message":
                    continue

                texto = msg.get("text", "")
                # O canal decide o tipo, não o modelo. Um valor fora do enum viraria
                # erro de banco três camadas adiante, então a validação é aqui.
                tipo = msg.get("tipo", "text")
                if tipo not in _TIPOS:
                    tipo = "text"
                from app.agent.runner import processar_turno_web

                await processar_turno_web(conversation_id, texto, adaptador, tipo=tipo)

        except WebSocketDisconnect:
            return

    @app.websocket("/api/events")
    async def eventos(ws: WebSocket) -> None:
        cfg = get_settings()
        # O navegador não põe cabeçalho no handshake do WebSocket: quando
        # ADMIN_TOKEN está definido, o token vem por query string.
        # A MESMA comparação que `exigir_admin` faz no REST: ausente coage para `""`
        # e o confronto é em tempo constante. Antes, o REST coagia e o WS não, então
        # a mesma requisição sem token era aceita numa porta e recusada na outra.
        apresentado = ws.query_params.get("token") or ""
        if cfg.admin_exigido and not hmac.compare_digest(
            apresentado.encode("utf-8"), (cfg.admin_token or "").encode("utf-8")
        ):
            await ws.close(code=4401)
            return
        await ws.accept()
        _admin.add(ws)
        try:
            while True:
                await asyncio.sleep(30)
                await ws.send_text(json.dumps({"type": "ping"}))
        except Exception:  # noqa: BLE001
            pass
        finally:
            _admin.discard(ws)
