"""Execução de um turno.

Nesta fatia o runner ainda é a espinha: ele orquestra persistência e canal. O agente
Agno com tools entra na fatia 3, junto com a cotação.
"""

from __future__ import annotations

from app.persistence import repo
from app.persistence.db import sessao_factory


async def processar_turno_web(conversation_id: str, texto: str, adaptador) -> None:
    """Um turno vindo do canal web.

    A mensagem do lead é **ecoada** de volta com o id e o `index` canônicos: sem isso
    o cliente não tem como reconciliar a bolha otimista, e passa a exibir um status
    que ele mesmo inventou.
    """
    fabrica = sessao_factory()
    with fabrica() as s:
        m = repo.gravar_mensagem(
            s, conversation_id, autor="lead", conteudo=texto, status="received"
        )
        s.commit()
        await adaptador.send(conversation_id, m.conteudo, message_id=m.id,
                             autor="lead", index=m.index, status=m.status)

    await adaptador.typing(conversation_id, ativo=True)
    try:
        from app.agent.turno import responder

        await responder(conversation_id, texto, adaptador)
    finally:
        await adaptador.typing(conversation_id, ativo=False)
