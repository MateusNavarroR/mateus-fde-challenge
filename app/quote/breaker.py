"""Circuit breaker da `/quote`.

**Global por processo**, não por conversa: a instabilidade é do legado, e descobri-la
numa conversa deve poupar as outras.

**Só `transient` e `timeout` contam.** Uma recusa de negócio é a API funcionando
perfeitamente — contá-la abriria o circuito num dia de muitos leads idosos. Um
`bad_request` é defeito nosso — contá-lo esconderia o bug atrás de um "legado fora".

Com `p=0,20`, cinco falhas consecutivas por acaso têm probabilidade de 0,032%: o
breaker praticamente não abre por azar. Com `p=1,0` (a suíte degradada), abre depois
de dois jobs.
"""

from __future__ import annotations

import datetime as dt
import enum
import time
from dataclasses import dataclass, field

from app.config import get_settings


class Estado(enum.StrEnum):
    FECHADO = "fechado"
    ABERTO = "aberto"
    MEIA_ABERTURA = "meia_abertura"


@dataclass
class Breaker:
    limiar: int
    cooldown_s: float
    relogio: object = time.monotonic

    falhas_consecutivas: int = 0
    _aberto_em: float | None = field(default=None, init=False)
    _aberto_desde_wall: dt.datetime | None = field(default=None, init=False)

    @property
    def estado(self) -> Estado:
        if self._aberto_em is None:
            return Estado.FECHADO
        if self.relogio() - self._aberto_em >= self.cooldown_s:
            # Meia-abertura: a sonda é a PRÓXIMA COTAÇÃO REAL, não uma requisição
            # sintética — assim ela não é desperdiçada.
            return Estado.MEIA_ABERTURA
        return Estado.ABERTO

    def permite_chamada(self) -> bool:
        return self.estado is not Estado.ABERTO

    def registrar_sucesso(self) -> None:
        self.falhas_consecutivas = 0
        self._aberto_em = None
        self._aberto_desde_wall = None

    def registrar_falha_transitoria(self) -> None:
        if self.estado is Estado.MEIA_ABERTURA:
            self._abrir()
            return
        self.falhas_consecutivas += 1
        if self.falhas_consecutivas >= self.limiar:
            self._abrir()

    def registrar_desfecho_de_negocio(self) -> None:
        """Recusa e bad_request: a API respondeu. Zera o contador de consecutivas
        sem fechar um circuito aberto — o legado estar respondendo 422 é sinal de
        saúde, não de recuperação de uma queda."""
        self.falhas_consecutivas = 0

    def _abrir(self) -> None:
        self._aberto_em = self.relogio()
        self._aberto_desde_wall = dt.datetime.now(dt.UTC)
        self.falhas_consecutivas = self.limiar

    def estado_para_api(self) -> dict:
        reabre = None
        if self._aberto_desde_wall is not None and self.estado is Estado.ABERTO:
            reabre = self._aberto_desde_wall + dt.timedelta(seconds=self.cooldown_s)
        return {
            "estado": str(self.estado),
            "falhas_consecutivas": self.falhas_consecutivas,
            "aberto_desde": self._aberto_desde_wall,
            "reabre_em": reabre,
        }


_breaker: Breaker | None = None


def breaker_global() -> Breaker:
    global _breaker
    if _breaker is None:
        s = get_settings()
        _breaker = Breaker(limiar=s.breaker_limiar, cooldown_s=s.breaker_cooldown_s)
    return _breaker


def resetar_breaker() -> None:
    """Só para a suíte: o breaker é global por processo de propósito."""
    global _breaker
    _breaker = None
