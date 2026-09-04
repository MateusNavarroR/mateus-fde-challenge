"""Adaptador de console — a implementação determinística da porta `ChannelAdapter`.

É ele que gera o **log de execução completa** (entregável nº 4) e que roda no CI.

Duas decisões que o distinguem do adaptador `web`:

- **`typing` é no-op.** O indicador de digitando é sinalização visível de tela; num log
  ele documentaria a coisa errada. O que prova a degradação no transcript são as
  mensagens reais de aviso, reforço e encaminhamento, que existem nos dois canais.
- **O transcript marca tempo relativo por linha** (`[+6.2s]`). É isso que faltava, não
  o indicador: com o tempo, o avaliador lê a política funcionando com número em vez de
  acreditar na descrição. `[digitando...]` seria decoração; `[+37.1s]` é informação.

O relógio é injetável para que a suíte não durma de verdade — uma suíte que espera 37 s
ninguém roda, e uma que ninguém roda não protege nada.
"""

from __future__ import annotations

import sys
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

from app.contracts.conversa import TipoMidia


@dataclass
class MensagemConsole:
    """Implementa o protocolo `InboundMessage`."""

    conversation_id: str
    external_id: str
    tipo: TipoMidia
    texto: str


@dataclass
class LinhaTranscript:
    segundos: float
    autor: str
    conteudo: str

    def render(self) -> str:
        return f"[{self.segundos:+.1f}s] {self.autor:<8} {self.conteudo}"


@dataclass
class ConsoleAdapter:
    """Porta `ChannelAdapter` sobre stdin/stdout."""

    name: str = "console"
    #: Quando ligado, acumula as linhas com tempo relativo em vez de só imprimir.
    transcript: bool = False
    #: Injetável: `time.monotonic` em produção, um relógio falso no teste.
    relogio: Callable[[], float] = time.monotonic
    saida = sys.stdout

    _t0: float | None = field(default=None, init=False)
    linhas: list[LinhaTranscript] = field(default_factory=list, init=False)
    #: Tudo que saiu, para as asserções da suíte.
    enviadas: list[dict] = field(default_factory=list, init=False)

    def marcar_inicio(self) -> None:
        """Zera o relógio relativo. Chamado quando a conversa começa."""
        self._t0 = self.relogio()

    def _decorrido(self) -> float:
        if self._t0 is None:
            self.marcar_inicio()
        return self.relogio() - self._t0

    async def send(
        self,
        conversation_id: str,
        text: str,
        *,
        message_id: str,
        quote_id: str | None = None,
        autor: str = "agente",
    ) -> str:
        """Envia e devolve o `external_id` atribuído pelo canal.

        A linha em `messages` é criada com status `pending` **antes** desta chamada e
        passa a `sent` com o retorno — assim uma falha de canal deixa rastro em vez de
        sumir. Quem faz isso é o runtime; o adaptador só entrega.
        """
        linha = LinhaTranscript(self._decorrido(), autor, text)
        self.linhas.append(linha)
        self.enviadas.append(
            {"conversation_id": conversation_id, "text": text,
             "message_id": message_id, "quote_id": quote_id, "autor": autor}
        )
        print(linha.render() if self.transcript else f"{autor}: {text}",
              file=self.saida, flush=True)
        return f"console:{message_id}"

    async def typing(self, conversation_id: str, *, ativo: bool) -> None:
        """No-op. Ver o docstring do módulo.

        Falhar aqui nunca interromperia o turno — é sinalização, não conteúdo —, e
        aqui não há nem o que falhar.
        """
        return None

    async def receive(self) -> AsyncIterator[MensagemConsole]:  # pragma: no cover
        """Lê stdin até EOF. Exercitado pelo `console_main`, não pela suíte."""
        i = 0
        loop_leitura = __import__("asyncio").get_running_loop()
        while True:
            linha = await loop_leitura.run_in_executor(None, sys.stdin.readline)
            if not linha:
                return
            texto = linha.rstrip("\n")
            if not texto:
                continue
            if self.transcript:
                self.linhas.append(LinhaTranscript(self._decorrido(), "lead", texto))
            yield MensagemConsole(
                conversation_id="", external_id=f"console:{i}", tipo="text", texto=texto
            )
            i += 1

    def transcript_texto(self) -> str:
        return "\n".join(linha.render() for linha in self.linhas)
