"""A camada de conversa: um turno por vez, e o relógio de demora do modelo.

**Um turno por vez por conversa.** Mensagem que chega durante um turno entra na fila e
é processada depois. É uma linha de regra, e ela resolve de graça a pergunta "o que
fazer se o lead escrever durante a espera da cotação" — que existiria de qualquer forma,
porque a tool de cotação bloqueia por até ~37 s.

**O relógio de 10 s** cobre a demora do *modelo*, fora do caminho da cotação. O aviso da
cotação (6 s) é despachado de dentro da própria tool, com o relógio do lead — não aqui.
Um watchdog genérico pareceria mais simples e seria pior: ele dispararia **durante a
geração**, e uma pergunta respondida em 6,5 s receberia "só um instante" seguido da
resposta 0,2 s depois. Por isso são dois relógios com limiares diferentes: a demora da
cotação é projetada (8 s de sono, por construção), a do modelo é anômala.

Os dois não colidem: qualquer mensagem que sai para o lead cancela o relógio, então o
aviso de 6 s da cotação mata o de 10 s daqui.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app import textos
from app.config import get_settings

#: Assinatura de quem processa um turno: recebe o texto do lead, devolve o texto do
#: agente (ou `None` quando o turno não produz fala — por exemplo depois de uma
#: cotação, cujo bloco já foi enviado pela tool).
Agente = Callable[[str], Awaitable[str | None]]


@dataclass
class Conversa:
    """Um turno por vez, e o relógio de demora do modelo."""

    conversation_id: str
    agente: Agente
    #: Chamado para entregar uma mensagem ao lead: `(texto, autor) -> None`.
    entregar: Callable[[str, str], Awaitable[None]]
    estado: str = "novo"

    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    #: Instrumentação para a suíte: sem ela o teste de fila passaria mesmo com dois
    #: turnos concorrentes que por acaso não se atrapalharam.
    turnos_ativos: int = field(default=0, init=False)
    turnos_simultaneos_maximo: int = field(default=0, init=False)

    async def receber(self, texto: str) -> None:
        """Processa um turno. Serializa por conversa: a segunda chamada espera."""
        async with self._lock:
            self.turnos_ativos += 1
            self.turnos_simultaneos_maximo = max(
                self.turnos_simultaneos_maximo, self.turnos_ativos
            )
            relogio = self._iniciar_relogio()
            try:
                resposta = await self.agente(texto)
                if resposta:
                    await self._entregar(resposta, "agente")
            finally:
                relogio.cancel()
                self.turnos_ativos -= 1

    def _iniciar_relogio(self) -> asyncio.Task:
        """Dispara o aviso de demora do modelo se nada sair para o lead a tempo.

        **Desligado no estado `encaminhado`** — senão o lead que escreve depois do
        handoff recebe "só um instante" a cada 10 s, para sempre.
        """
        if self.estado == "encaminhado":
            fut: asyncio.Future = asyncio.get_running_loop().create_future()
            fut.cancel()
            return asyncio.ensure_future(_nada())
        return asyncio.ensure_future(self._avisar_apos(get_settings().aviso_sem_cotacao_s))

    async def _avisar_apos(self, segundos: float) -> None:
        await asyncio.sleep(segundos)
        await self._entregar(textos.AVISO_SEM_COTACAO, "sistema")

    async def _entregar(self, texto: str, autor: str) -> None:
        await self.entregar(texto, autor)

    def encaminhar(self) -> None:
        """Estado terminal: o agente para de responder e o relógio desliga."""
        self.estado = "encaminhado"


async def _nada() -> None:
    return None
