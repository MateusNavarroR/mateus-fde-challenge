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
from app import textos
from app.persistence import repo
from app.persistence.db import sessao_factory

log = logging.getLogger("autoseguro.turno")


async def responder(
    conversation_id: str,
    texto: str,
    adaptador,
    chegada_do_lead: float | None = None,
    tipo: str = "text",
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

        conv = repo.obter_conversa(s, conversation_id)
        if conv is not None and conv.state == "encaminhado":
            # `encaminhado` é TERMINAL: o agente parou de responder. A mensagem do
            # lead fica persistida — ela é do operador, não nossa para responder.
            return

        ctx = ContextoDoTurno(
            sessao=s,
            conversation_id=conversation_id,
            texto_do_lead=texto,
            enviar=enviar,
            chegada_do_lead=chegada_do_lead or time.monotonic(),
            tipo_da_mensagem=tipo,
        )
        agente = construir_agente(ctx)

        try:
            r = await asyncio.to_thread(agente.run, texto)
        except Exception:  # noqa: BLE001
            log.exception("turno falhou")
            if not ctx.ja_enviou:
                # De `textos`, como todo o resto: um literal aqui é a deriva que o
                # teste byte a byte de `docs/TEXTOS.md` existe para impedir.
                await enviar_async(textos.FALHA_TECNICA)
            return

        # O `finally` é o ponto, e ele resolve DOIS defeitos de uma vez.
        #
        # 1. **O commit.** `gravar_turn_usage` faz `flush`, não `commit`. Todo caminho
        #    de saída que não envia mensagem própria — `ja_enviou`, saída vazia —
        #    saía sem commitar, e o `flush` voltava atrás no rollback do
        #    `with fabrica() as s`. Medido na vistoria: uma conversa de 2 turnos tinha
        #    1 linha em `turn_usage`, e a que faltava era a do turno da COTAÇÃO — ou
        #    seja, o painel perdia exatamente os turnos com tool call, os mais caros.
        #
        # 2. **A ordem.** Gravar ANTES de enviar ancorava o custo na mensagem do turno
        #    ANTERIOR: a deste turno ainda não existia. A coluna promete "a mensagem
        #    que este turno produziu" e entregava a de outro. Dois turnos seguidos sem
        #    mensagem nova apontavam para a mesma âncora e colidiam no índice único —
        #    foi o que derrubou o replay do dataset aos 15/30.
        #
        # No `finally` porque são cinco saídas diferentes e o custo do turno existe em
        # todas elas, inclusive quando o guardrail descarta o texto.
        try:
            if await _encaminhar(s, conversation_id, ctx, texto, enviar_async, adaptador):
                return

            if ctx.ja_enviou:
                # A tool já disse tudo o que o lead precisava. O texto do modelo sai fora.
                return

            saida = (getattr(r, "content", "") or "").strip()
            if not saida:
                return

            # ⚠️ **O turno que "deu certo" e não deu.**
            #
            # Quando a chamada ao provider falha, o Agno NÃO levanta: ele devolve um
            # `RunOutput` com `status=ERROR` e põe o texto do erro em `content`. O
            # `except` em volta de `agente.run` nunca dispara, e a mensagem seguia o
            # caminho normal — persistida como fala do `agente` e ENTREGUE AO LEAD.
            #
            # Medido no replay: a conta ficou sem crédito no meio da execução, e 14
            # conversas gravaram «Error code: 400 … Your credit balance is too low …»
            # como resposta do agente. O guardrail não pega: não há valor monetário no
            # texto. Um lead lendo isso é o pior desfecho possível de uma falha de
            # infraestrutura — pior que silêncio, porque expõe a nossa operação.
            #
            # A detecção é por ESTADO, não por farejar o texto: `RunStatus.ERROR` é o
            # contrato do Agno, e um regex de "Error code:" quebraria na primeira
            # mudança de formato do SDK.
            if _falhou(r):
                log.error("run com status de erro: %s", saida[:200])
                await enviar_async(textos.FALHA_TECNICA)
                return
            await _entregar_do_modelo(s, conversation_id, ctx, texto, saida,
                                      enviar_async, adaptador)
        finally:
            _gravar_uso(s, conversation_id, r)
            s.commit()


def _falhou(r) -> bool:
    """`RunStatus.ERROR`, sem importar o enum do Agno no topo.

    Comparação por VALOR e insensível a caixa: o enum é do Agno, e prender o nosso
    caminho de erro à identidade de um objeto de terceiro é como um `import` a mais
    vira defeito numa atualização menor.
    """
    return str(getattr(r, "status", "") or "").upper().endswith("ERROR")


async def _entregar_do_modelo(
    s, conversation_id, ctx, texto, saida, enviar_async, adaptador=None
):
    """O texto do modelo, com o descarte do guardrail no caminho de erro."""
    from app.persistence import repo

    try:
        await enviar_async(saida, autor="agente")
    except GuardrailViolado as e:
        # Violação não é corrigida pelo modelo — pedir de novo vira laço. A mensagem
        # é descartada, o descarte é GRAVADO (é a evidência que o operador lê) e a
        # violação conta para o gatilho.
        log.warning("guardrail: %s", e.motivo)
        repo.registrar_descarte(s, conversation_id, saida)
        s.commit()
        # Reavalia AGORA: a contagem acabou de mudar, e esperar o próximo turno
        # deixaria o lead sem resposta e sem handoff justamente no turno em que o
        # agente falhou duas vezes.
        await _encaminhar(s, conversation_id, ctx, texto, enviar_async, adaptador)


async def _encaminhar(
    s, conversation_id: str, ctx, texto: str, enviar_async, adaptador=None
) -> bool:
    """Avalia os sete gatilhos e, se algum casar, encaminha.

    As duas origens convergem aqui: o que o **modelo** pediu por `escalate_to_human`
    (write-back em `ctx.handoffs`) e o que a **regra** detectou no turno. Elas
    produzem o mesmo sinal, e `disparado_por` é a única diferença — que é
    exatamente o ponto do padrão write-back.
    """
    from app.contracts.conversa import HandoffTrigger
    from app.handoff import gatilhos

    contexto = gatilhos.Contexto(
        texto_do_lead=texto,
        tipo_da_mensagem=ctx.tipo_da_mensagem,
        cotacao_falhou=any(
            h.get("trigger") is HandoffTrigger.COTACAO_INDISPONIVEL for h in ctx.handoffs
        ),
        tentativas_extracao=repo.tentativas_de_extracao(s, conversation_id),
        objecoes_de_preco=ctx.objecoes_de_preco,
        violacoes_guardrail=repo.violacoes_de_guardrail(s, conversation_id),
        # Do BANCO, incluindo a mensagem deste turno, que já foi gravada.
        midias_apos_pedido=repo.midias_do_lead(s, conversation_id),
    )
    avaliado = gatilhos.avaliar(contexto)
    do_modelo = next((h for h in ctx.handoffs if h.get("disparado_por") == "modelo"), None)

    if avaliado is None and do_modelo is None:
        return False

    if avaliado is not None:
        trigger, motivo, secundarios = avaliado
        origem = "regra"
        quote_id = next((h.get("quote_id") for h in ctx.handoffs if h.get("quote_id")), None)
        resumo = None
    else:
        trigger = do_modelo["trigger"]
        motivo, secundarios, origem = do_modelo["reason"], [], "modelo"
        quote_id, resumo = do_modelo.get("quote_id"), do_modelo.get("summary")

    handoff = gatilhos.registrar(
        s, conversation_id, trigger, motivo,
        secundarios=secundarios, summary=resumo, quote_id=quote_id,
        disparado_por=origem,
    )
    s.commit()

    # É este push que faz a fila do admin ganhar o caso SEM recarregar — que é o que
    # a tela de handoffs promete por escrito. Antes, `publicar_evento` não era
    # chamada em lugar nenhum: o cliente assinava, o servidor aceitava a conexão, e
    # nada nunca era enviado.
    from app.channels.web import publicar_evento

    await publicar_evento("handoff.created", {
        "id": handoff.id, "conversation_id": conversation_id, "trigger": str(trigger),
    })

    # A mensagem de indisponibilidade já saiu de dentro da tool de cotação;
    # repeti-la aqui seria dizer duas vezes a mesma coisa ao lead.
    # A mensagem de indisponibilidade já saiu de dentro da tool de cotação, e
    # `compor_handoff("cotacao_indisponivel")` JÁ TERMINA com a despedida. Mandar
    # `DESPEDIDA` aqui repetia a mesma frase, palavra por palavra, duas mensagens
    # seguidas — visível no transcript do cenário degradado.
    if trigger is not HandoffTrigger.COTACAO_INDISPONIVEL:
        await enviar_async(
            textos.compor_handoff(str(trigger), assunto=gatilhos.assunto_do_texto(texto))
        )

    # E AVISA A TELA que a conversa fechou.
    #
    # `gatilhos.registrar` marca `conv.state = "encaminhado"`, que é terminal: o agente
    # para de responder (ver a guarda no topo de `responder`). O cliente sabe tratar
    # esse estado — o reducer tem `entradaBloqueada`, a tela tem a faixa de conversa
    # encerrada, o adaptador tem o método `estado()` — e **ninguém nunca o chamava**.
    # Uma cadeia inteira construída e nunca ligada: o lead ficava com o campo liberado
    # numa conversa que já não responde, digitando no vazio, e um F5 não mudava nada.
    #
    # Falhar aqui não pode derrubar o encaminhamento, que já foi gravado: é
    # sinalização, como o `typing`.
    estado = getattr(adaptador, "estado", None)
    if estado is not None:
        try:
            await estado("encaminhado")
        except Exception:  # noqa: BLE001 — ver acima
            log.debug("StateEvent perdido; o handoff está gravado")
    return True


def _gravar_uso(s, conversation_id: str, r) -> None:
    """Custo e uso por turno. Substitui o Langfuse: fica na própria base."""
    from app.persistence.uso import gravar_turn_usage

    try:
        gravar_turn_usage(s, conversation_id, r)
    except Exception:  # noqa: BLE001
        log.exception("turn_usage não gravado")
