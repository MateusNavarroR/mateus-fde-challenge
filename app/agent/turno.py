"""Um turno do agente, ponta a ponta.

Monta o contexto confiável, constrói o agente Agno com as tools ligadas, roda, e
aplica a **regra de descarte**: quando a tool já falou com o lead — cotação, recusa ou
indisponibilidade —, o texto do modelo naquele turno é jogado fora.

O motivo do descarte: tudo que o lead precisava ouvir já foi dito deterministicamente,
e o que o modelo acrescentar é texto não verificado sobre uma cotação. Vale nos três
desfechos, **sem exceção** — inclusive na recusa, onde o risco não é preço alucinado e
sim promessa falsa ("vou ver com o setor de exceções").

O agente roda numa **thread**, porque as tools do Agno são síncronas e uma delas
bloqueia por até ~37 s esperando a `/quote`. Rodá-lo no laço de eventos travaria o
WebSocket inteiro — inclusive as mensagens de espera que a própria tool precisa enviar.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.agent.agente import construir_agente
from app.agent.guardrail import GuardrailViolado
from app.agent.tools import ContextoDoTurno
from app.persistence import repo
from app.persistence.db import sessao_factory

log = logging.getLogger("autoseguro.turno")


async def responder(
    conversation_id: str, texto: str, adaptador, chegada_do_lead: float | None = None
) -> None:
    laco = asyncio.get_running_loop()
    fabrica = sessao_factory()

    with fabrica() as s:

        def _persistir(conteudo: str, quote_id: str | None, autor: str):
            m = repo.gravar_mensagem(
                s, conversation_id, autor=autor, conteudo=conteudo,
                status="pending", quote_id=quote_id,
            )
            s.commit()
            return m

        def _confirmar(m) -> None:
            repo.atualizar_status_mensagem(s, m.id, "sent")
            s.commit()

        async def _entregar(m, autor: str) -> None:
            await adaptador.send(conversation_id, m.conteudo, message_id=m.id,
                                 quote_id=m.quote_id, autor=autor,
                                 index=m.index, status="sent")

        def enviar(conteudo: str, quote_id: str | None = None,
                   autor: str = "sistema") -> None:
            """Grava e entrega, **bloqueando** até o frame sair.

            Chamado de dentro da thread do agente. `run_coroutine_threadsafe(...)
            .result()` é o que garante a ordem: agendar sem esperar deixaria o aviso
            de espera chegar depois do preço.

            ⚠️ **Só pode ser chamado fora da thread do laço.** Chamá-lo de dentro dela
            agenda no laço que está bloqueado esperando o resultado — deadlock, e o
            sintoma é um `TimeoutError` a 30 s de distância da causa. O caminho de
            erro abaixo usa `await` direto por isso.
            """
            m = _persistir(conteudo, quote_id, autor)
            asyncio.run_coroutine_threadsafe(_entregar(m, autor), laco).result(timeout=45)
            _confirmar(m)

        async def enviar_async(conteudo: str, autor: str = "sistema") -> None:
            """A versão para quando já se está no laço."""
            m = _persistir(conteudo, None, autor)
            await _entregar(m, autor)
            _confirmar(m)

        ctx = ContextoDoTurno(
            sessao=s,
            conversation_id=conversation_id,
            texto_do_lead=texto,
            enviar=enviar,
            chegada_do_lead=chegada_do_lead or time.monotonic(),
        )
        agente = construir_agente(ctx)

        try:
            r = await asyncio.to_thread(agente.run, texto)
        except Exception:  # noqa: BLE001
            log.exception("turno falhou")
            if not ctx.ja_enviou:
                await enviar_async(
                    "Tive um problema aqui do meu lado. Já vou chamar alguém da equipe."
                )
            return

        _gravar_uso(s, conversation_id, r)

        if ctx.ja_enviou:
            # A tool já disse tudo o que o lead precisava. O texto do modelo vai fora.
            return

        saida = (getattr(r, "content", "") or "").strip()
        if not saida:
            return
        try:
            await enviar_async(saida, autor="agente")
        except GuardrailViolado as e:
            # Violação não é corrigida pelo modelo — isso vira laço. A mensagem é
            # descartada e a violação conta.
            log.warning("guardrail: %s", e.motivo)


def _gravar_uso(s, conversation_id: str, r) -> None:
    """Custo e uso por turno. Substitui o Langfuse: fica na própria base."""
    from app.persistence.uso import gravar_turn_usage

    try:
        gravar_turn_usage(s, conversation_id, r)
    except Exception:  # noqa: BLE001
        log.exception("turn_usage não gravado")
