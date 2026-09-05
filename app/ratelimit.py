"""Limite de taxa para a superfície **pública**, em memória e sem dependência nova.

Três rotas não exigem autenticação, por desenho: `GET /api/health`,
`POST /api/conversations` e o WebSocket do chat. As duas últimas custam dinheiro —
cada mensagem do chat é uma inferência do modelo — e sem limite alguém com acesso à
porta esgota a chave da Anthropic sem nem precisar de um bug.

**O que este módulo não é.** Não é proteção contra um atacante distribuído, e não
substitui um proxy na frente. Ele é o controle que falta na aplicação: transforma
"gasto ilimitado" em "gasto limitado por origem", que é a diferença entre um incidente
e um aborrecimento.

**Por que em memória, e não Redis.** O compromisso do repositório é subir com um
comando e no máximo uma variável obrigatória. Um Redis só para contar requisições
trocaria um risco pequeno por um serviço a mais no `docker compose`, e o processo é
único — o contador global do processo É o contador global do sistema. Numa implantação
com réplicas isso deixa de valer, e o README declara.

**Token bucket, e não janela fixa.** A janela fixa deixa passar o dobro do limite na
virada: 30 requisições no último segundo de um minuto e 30 no primeiro do seguinte. O
balde acumula até a capacidade e repõe continuamente, então a rajada permitida é
exatamente a capacidade, sempre.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Balde:
    """Um token bucket por chave, com relógio injetável.

    O relógio é injetável para que o teste não durma: uma suíte que espera 60 s para
    provar reposição é uma suíte que ninguém roda.
    """

    capacidade: float
    #: Tokens repostos por segundo. `capacidade / periodo_s` no construtor de cima.
    reposicao_s: float
    relogio: object = time.monotonic

    _tokens: dict[str, float] = field(default_factory=dict, init=False)
    _visto: dict[str, float] = field(default_factory=dict, init=False)
    _trava: threading.Lock = field(default_factory=threading.Lock, init=False)

    def permite(self, chave: str, custo: float = 1.0) -> bool:
        """Consome um token e diz se a requisição passa.

        Sob trava porque o servidor atende em várias threads (rotas síncronas correm
        no threadpool do AnyIO) e um contador sem trava conta menos do que deveria —
        exatamente sob a carga em que o limite importa.
        """
        agora = self.relogio()  # type: ignore[operator]
        with self._trava:
            atual = self._tokens.get(chave, self.capacidade)
            decorrido = agora - self._visto.get(chave, agora)
            atual = min(self.capacidade, atual + decorrido * self.reposicao_s)
            self._visto[chave] = agora
            if atual < custo:
                self._tokens[chave] = atual
                return False
            self._tokens[chave] = atual - custo
            return True

    def esquecer(self, chave: str) -> None:
        with self._trava:
            self._tokens.pop(chave, None)
            self._visto.pop(chave, None)

    def limpar(self) -> None:
        """Zera tudo. Só para teste — o estado é global do processo."""
        with self._trava:
            self._tokens.clear()
            self._visto.clear()


def por_minuto(quantidade: int, *, relogio=time.monotonic) -> Balde:
    return Balde(capacidade=float(quantidade), reposicao_s=quantidade / 60.0,
                 relogio=relogio)


#: Criar conversa é barato para nós e é o portão de entrada de tudo: 20/min por origem
#: é folgado para uma pessoa e apertado para um laço.
CRIAR_CONVERSA = por_minuto(20)

#: **O caro.** Cada mensagem é uma inferência. 30/min por origem é mais do que
#: qualquer pessoa digita e ainda assim põe teto no gasto: um laço fica limitado a
#: ~30 inferências por minuto em vez de ilimitadas.
MENSAGEM_DO_CHAT = por_minuto(30)


def origem(request_ou_ws) -> str:
    """A chave do limite: o IP do cliente.

    ⚠️ **Sem confiar em `X-Forwarded-For`.** Um cabeçalho que o cliente escreve não
    pode ser a chave de um limite: bastaria variá-lo a cada requisição para ter limite
    infinito. Atrás de um proxy de verdade, quem deve reescrever o cliente é o
    servidor ASGI (`--proxy-headers` com `--forwarded-allow-ips`), e aí `request.client`
    já vem correto — o limite continua certo sem que este módulo confie em nada.
    """
    cliente = getattr(request_ou_ws, "client", None)
    return getattr(cliente, "host", None) or "desconhecido"
