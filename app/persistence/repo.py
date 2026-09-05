"""O ponto de estrangulamento.

`gravar_mensagem` é o **único** caminho para a tabela `messages`. Toda fatia seguinte
escreve por aqui, e é por isso que mascaramento e guardrail cabem num lugar só em vez
de virarem boa intenção espalhada.

A ordem das operações não é acidental:

    mascarar → guardrail → calcular index → gravar

Mascarar antes do guardrail porque a exceção do guardrail carrega um trecho do texto
para a linha de auditoria, e esse trecho não pode conter PII. Guardrail antes de gravar
porque a mensagem violadora não deve existir nem por um instante.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.agent.guardrail import checar_mensagem_de_cotacao, checar_texto_do_modelo
from app.persistence.models import Conversation, Message, Quote
from app.privacy.mascarar import mascarar


def _id(prefixo: str) -> str:
    return f"{prefixo}_{uuid.uuid4().hex[:16]}"


# ─── conversas ───────────────────────────────────────────────────────────────


def criar_conversa(s: Session, *, channel: str, external_ref: str) -> Conversation:
    c = Conversation(id=_id("conv"), channel=channel, external_ref=external_ref)
    s.add(c)
    s.flush()
    return c


def criar_ou_retomar_conversa(
    s: Session, *, channel: str, external_ref: str | None = None
) -> tuple[Conversation, bool]:
    """Cria, ou devolve a que já existe para aquele `external_ref`.

    `external_ref` é o identificador do lead **no canal** — o `wamid` no WhatsApp, o
    id de sessão do navegador no web. A migração tem `UNIQUE (channel, external_ref)`,
    e é essa restrição que dá sentido ao campo: **mesma sessão, mesma conversa**.

    Quando o canal não manda referência, geramos uma única. Nunca um literal fixo:
    um literal faz a primeira conversa gravar e **todas as seguintes colidirem para
    sempre naquele banco** — e o sintoma é um 500 no segundo uso, que nenhum teste
    unitário pega, porque cada teste cria uma conversa num banco limpo.

    Devolve `(conversa, criada)`.
    """
    if external_ref:
        existente = s.execute(
            select(Conversation).where(
                Conversation.channel == channel,
                Conversation.external_ref == external_ref,
            )
        ).scalar_one_or_none()
        if existente is not None:
            return existente, False
    else:
        external_ref = f"{channel}:{uuid.uuid4().hex}"
    return criar_conversa(s, channel=channel, external_ref=external_ref), True


def obter_conversa(s: Session, conversation_id: str) -> Conversation | None:
    return s.get(Conversation, conversation_id)


def atualizar_estado(s: Session, conversation_id: str, estado: str) -> None:
    c = s.get(Conversation, conversation_id)
    c.state = estado
    c.atualizado_em = dt.datetime.now(dt.UTC)
    s.flush()


# ─── mensagens ───────────────────────────────────────────────────────────────


def proximo_index(s: Session, conversation_id: str) -> int:
    maior = s.execute(
        select(func.max(Message.index)).where(Message.conversation_id == conversation_id)
    ).scalar()
    return 0 if maior is None else maior + 1


def gravar_mensagem(
    s: Session,
    conversation_id: str,
    *,
    autor: str,
    conteudo: str,
    status: str,
    tipo: str = "text",
    external_id: str | None = None,
    quote_id: str | None = None,
) -> Message:
    """Grava uma mensagem. Único caminho para `messages`.

    Deduplica por `external_id`: o mesmo id entregue duas vezes produz **uma** linha.
    Canais reais reentregam; o console não, mas o contrato é o mesmo — assim o teste
    do console prova o caminho que o canal real vai usar.
    """
    conteudo = mascarar(conteudo)

    # Verificação 1: texto do modelo não escreve preço.
    if autor == "agente":
        checar_texto_do_modelo(conteudo)

    # Verificações 2 e 3: o status e o render vêm do BANCO, não do chamador — não há
    # como passar valores convenientes.
    if quote_id is not None:
        q = s.get(Quote, quote_id)
        if q is None:
            from app.agent.guardrail import GuardrailViolado

            raise GuardrailViolado(f"quote_id {quote_id!r} não existe")
        checar_mensagem_de_cotacao(
            conteudo,
            quote_status=q.status,
            render_esperado=_render_de(q),
        )

    if external_id is not None:
        existente = s.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.external_id == external_id,
            )
        ).scalar_one_or_none()
        if existente is not None:
            return existente

    m = Message(
        id=_id("msg"),
        conversation_id=conversation_id,
        index=proximo_index(s, conversation_id),
        autor=autor,
        tipo=tipo,
        conteudo=conteudo,
        status=status,
        external_id=external_id,
        quote_id=quote_id,
    )
    # ON CONFLICT DO NOTHING + releitura, e não SELECT antes do INSERT, que é corrida:
    # duas entregas simultâneas do mesmo external_id passariam pelo SELECT juntas.
    if external_id is not None:
        s.execute(
            insert(Message.__table__)
            .values(
                id=m.id,
                conversation_id=m.conversation_id,
                index=m.index,
                autor=m.autor,
                tipo=m.tipo,
                conteudo=m.conteudo,
                status=m.status,
                external_id=m.external_id,
                quote_id=m.quote_id,
            )
            # O índice da migração é PARCIAL (`WHERE external_id IS NOT NULL`), e o
            # ON CONFLICT só casa com ele se repetir o mesmo predicado. Sem o
            # `index_where`, o Postgres responde "there is no unique or exclusion
            # constraint matching the ON CONFLICT specification".
            .on_conflict_do_nothing(
                index_elements=["conversation_id", "external_id"],
                index_where=Message.external_id.isnot(None),
            )
        )
        s.flush()
        return s.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.external_id == external_id,
            )
        ).scalar_one()

    s.add(m)
    s.flush()
    return m


def tentativas_de_extracao(s: Session, conversation_id: str) -> dict[str, int]:
    """`{campo: n}` acumulado na conversa. Insumo de `EXTRACAO_FALHOU`.

    A terceira das contagens derivadas do banco, com `midias_do_lead` e
    `violacoes_de_guardrail`, e pelo mesmo motivo: um contador que vive só no envelope
    do turno reinicia a cada mensagem, e "a segunda falha no mesmo campo" deixa de
    poder acontecer entre turnos — que é exatamente o caso que a regra descreve.
    """
    conv = s.get(Conversation, conversation_id)
    return dict(conv.tentativas_extracao or {}) if conv is not None else {}


def registrar_descarte(s: Session, conversation_id: str, conteudo: str) -> Message:
    """Grava a mensagem que o guardrail **impediu de sair**, com status `discarded`.

    Sem isto a violação virava uma linha de log e desaparecia: o transcript entregue
    mostrava a conversa como se nada tivesse acontecido, e `discarded` era um valor
    do enum que nada nunca escrevia — uma promessa do contrato sem caminho de código.

    Ela é o insumo de `GUARDRAIL`, que encaminha na **segunda** violação. A primeira
    é descartada e contada: um modelo que escorrega uma vez não justifica ocupar uma
    pessoa; um que escorrega duas na mesma conversa, sim.

    ⚠️ **Não passa pela verificação 1 de propósito.** As três verificações guardam o
    que é **entregue**; esta linha existe justamente para registrar que o texto NÃO
    foi entregue. Submetê-la ao guardrail seria pedir que o registro do descarte
    fosse recusado pelo mesmo motivo que causou o descarte — e a evidência sumiria de
    novo, agora por construção.
    """
    m = Message(
        id=_id("msg"),
        conversation_id=conversation_id,
        index=proximo_index(s, conversation_id),
        autor="agente",
        tipo="text",
        conteudo=mascarar(conteudo),
        status="discarded",
    )
    s.add(m)
    s.flush()
    return m


def violacoes_de_guardrail(s: Session, conversation_id: str) -> int:
    """Quantas mensagens desta conversa o guardrail barrou. Derivado do banco, como
    `midias_do_lead` e pelo mesmo motivo."""
    return int(
        s.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.status == "discarded",
            )
        ).scalar_one()
    )


def midias_do_lead(s: Session, conversation_id: str) -> int:
    """Quantas mensagens de mídia o lead já mandou nesta conversa.

    Deriva do **banco**, e não de um contador que o chamador passa, pelo mesmo motivo
    das três verificações do guardrail: um contador de argumento é um número que o
    chamador pode escolher, e o gatilho de handoff deixaria de ser auditável a partir
    do transcript.

    É o insumo de `MIDIA_SEM_TEXTO`. A regra dispara na **segunda** mídia porque a
    resposta à primeira é sempre o pedido de texto — "insistiu depois de pedirmos"
    é, operacionalmente, "mandou a segunda".
    """
    return int(
        s.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.autor == "lead",
                Message.tipo != "text",
            )
        ).scalar_one()
    )


def atualizar_status_mensagem(s: Session, message_id: str, status: str) -> None:
    s.get(Message, message_id).status = status
    s.flush()


def mensagens(s: Session, conversation_id: str) -> list[Message]:
    """Ordenado por `index`, **nunca** por timestamp. No dataset do desafio 99,8% das
    conversas têm timestamp fora de ordem, e a lição vale para o nosso lado: relógio
    não é ordem."""
    return list(
        s.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.index)
        ).scalars()
    )


def _render_de(q: Quote) -> str | None:
    """O render canônico de uma cotação, recalculado do payload guardado.

    Fica aqui e não no renderer para evitar import circular; delega assim que a
    fatia 3 criar `quote/renderer.py`.
    """
    if q.payload is None:
        return None
    from app.quote.renderer import render_de_payload

    return render_de_payload(q.payload)
