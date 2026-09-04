"""A porta `ChannelAdapter` — o agente é agnóstico de canal.

Dois adaptadores são entregues, ambos **sem credencial**:

| Adaptador | Papel |
|---|---|
| `console` | CLI determinístico. Gera o log de execução completa e roda no CI. |
| `web`     | Interface que simula o WhatsApp, sobre WebSocket. |

WhatsApp Cloud API e Baileys **não são entregues**, e isso é decisão de escopo, não
omissão: nenhum critério de avaliação depende do canal, ambos exigiriam credencial e
webhook público que quem clona não tem, e o tempo foi para o que é avaliado. O contrato
que cada um cumpriria está documentado em `docs/ARQUITETURA.md`.

O desenho da porta é o que torna essa afirmação verificável: os dois adaptadores
entregues são maximamente diferentes — um é síncrono e in-process, o outro é
assíncrono, multi-cliente e com estado de conexão. O que sobrevive aos dois é o que
uma implementação Meta ou Baileys também cumpriria.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from app.contracts.conversa import TipoMidia


class InboundMessage(Protocol):
    """Mensagem que entra pelo canal.

    `external_id` é o identificador do canal (o `wamid` no WhatsApp, o índice da linha
    no console). É por ele que se deduplica: o mesmo `external_id` entregue duas vezes
    produz **um** turno. Canais reais reentregam; o console não, mas o contrato é o
    mesmo para que o teste do console prove o caminho.
    """

    conversation_id: str
    external_id: str
    tipo: TipoMidia
    texto: str


@runtime_checkable
class ChannelAdapter(Protocol):
    """Porta de canal.

    Três operações, e só três. `typing` está aqui — e não é enfeite — porque é o que
    torna a degradação da `/quote` **visível** ao lead: quando a cotação demora, o
    "digitando…" e o aviso de espera acontecem no canal enquanto o job continua.
    Um canal que não sabe sinalizar espera não consegue expressar o comportamento que
    o desafio avalia.
    """

    name: str

    async def send(
        self,
        conversation_id: str,
        text: str,
        *,
        message_id: str,
        quote_id: str | None = None,
    ) -> str:
        """Envia uma mensagem e devolve o `external_id` atribuído pelo canal.

        `message_id` é **nosso** e vem de fora: a linha em `messages` é criada com
        status `pending` antes do envio e passa a `sent` com o retorno daqui. Assim
        uma falha de canal deixa rastro em vez de sumir.

        `quote_id` acompanha a mensagem que carrega uma cotação. É o guardrail
        auditável: mensagem com valor monetário sem `quote_id` é bug.
        """
        ...

    async def typing(self, conversation_id: str, *, ativo: bool) -> None:
        """Liga/desliga o indicador de digitação. Idempotente, e falhar aqui **nunca**
        interrompe o turno — é sinalização, não conteúdo."""
        ...

    def receive(self) -> AsyncIterator[InboundMessage]:
        """Fluxo de mensagens que chegam. O runtime consome; o adaptador não decide
        nada sobre a conversa."""
        ...
