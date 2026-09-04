"""O turno do agente. Substituído pelo agente Agno na fatia 3."""

from __future__ import annotations

from app.persistence import repo
from app.persistence.db import sessao_factory


async def responder(conversation_id: str, texto: str, adaptador) -> None:
    fabrica = sessao_factory()
    resposta = "Recebi! Ainda estou sendo montado — a cotação chega na próxima fatia."
    with fabrica() as s:
        m = repo.gravar_mensagem(
            s, conversation_id, autor="agente", conteudo=resposta, status="pending"
        )
        s.commit()
        await adaptador.send(conversation_id, m.conteudo, message_id=m.id,
                             autor="agente", index=m.index, status="sent")
        repo.atualizar_status_mensagem(s, m.id, "sent")
        s.commit()
