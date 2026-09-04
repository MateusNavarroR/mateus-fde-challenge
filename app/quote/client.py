"""Cliente HTTP da `/quote`.

Tudo que é status, tentativa, backoff e semáforo vive **abaixo da fronteira da tool**.
Um modelo exposto a "recebi 503" improvisa, e improvisar aí é a falha que esta
arquitetura existe para impedir.

O `read timeout` é maior que `QUOTE_SLOW_SECONDS`: 10% das chamadas dormem 8,004 s e
devolvem **200 correto**, e um timeout menor converte sucesso em falha — que o retry
então reproduz, porque o próximo sorteio pode cair de novo na faixa lenta.

O **semáforo** existe porque o handler do legado é síncrono e roda no threadpool do
AnyIO, cujo limite é 40. Medido: 60 chamadas lentas simultâneas → 40 em ~8,8 s e 20
enfileiradas para ~16,6 s, acima do nosso timeout. Sem limitar, o dimensionamento do
timeout deixa de valer exatamente quando há mais leads — e o modo de falha é o pior
possível: falha artificial em massa.
"""

from __future__ import annotations

import random
import threading
import time

import httpx

from app.api.schemas import UpstreamHealth
from app.config import get_settings
from app.contracts.quote import QuoteError, QuoteRequest, classificar_erro

NOTA_HEALTH = (
    "O /health do legado responde 200 mesmo com 100% das cotações falhando. "
    "A saúde real está na janela de tentativas abaixo."
)


class Resposta:
    """O que uma tentativa produziu, sem interpretação."""

    def __init__(self, http_status: int | None, corpo: dict | None,
                 latency_ms: int, timeout: bool = False) -> None:
        self.http_status = http_status
        self.corpo = corpo
        self.latency_ms = latency_ms
        self.timeout = timeout

    @property
    def ok(self) -> bool:
        return self.http_status == 200

    def erro(self) -> QuoteError:
        return classificar_erro(self.http_status, self.corpo, timeout=self.timeout)


class Semaforo:
    """Limita as chamadas em voo contra a `/quote`.

    Expõe `maximo_em_voo` porque a asserção que prova o semáforo é sobre o **máximo
    simultâneo**, não sobre a latência final: com menos de 40 chamadas o legado não
    degrada, e um teste que só olha latência passaria com a feature ausente.
    """

    def __init__(self, limite: int) -> None:
        self._sem = threading.Semaphore(limite)
        self._lock = threading.Lock()
        self.em_voo = 0
        self.maximo_em_voo = 0

    def __enter__(self):
        self._sem.acquire()
        with self._lock:
            self.em_voo += 1
            self.maximo_em_voo = max(self.maximo_em_voo, self.em_voo)
        return self

    def __exit__(self, *exc) -> None:
        with self._lock:
            self.em_voo -= 1
        self._sem.release()

    def zerar(self) -> None:
        self.maximo_em_voo = 0


_semaforo: Semaforo | None = None


def semaforo() -> Semaforo:
    global _semaforo
    if _semaforo is None:
        _semaforo = Semaforo(get_settings().quote_max_concorrencia)
    return _semaforo


def resetar_semaforo() -> None:
    """Só para a suíte."""
    global _semaforo
    _semaforo = None


def calcular_backoff(tentativa: int) -> float:
    """Exponencial com **full jitter**, com teto.

    Não há `Retry-After` no 5xx do legado — o backoff é 100% nosso. O jitter evita
    que várias conversas retentem no mesmo instante e sincronizem a carga.
    """
    cfg = get_settings()
    teto = min(cfg.quote_backoff_teto_s, cfg.quote_backoff_base_s * (2 ** (tentativa - 1)))
    return random.uniform(0, teto)


def chamar(req: QuoteRequest, *, url: str | None = None) -> Resposta:
    """Uma tentativa. Não retenta, não classifica além do necessário.

    O `read timeout` é **maior que `QUOTE_SLOW_SECONDS`**: 10% das chamadas dormem
    8,004 s e devolvem 200 correto, e um timeout menor converte sucesso em falha — que
    o retry então reproduz.
    """
    cfg = get_settings()
    base = url or cfg.quote_api_url
    with semaforo():
        return _chamar_sem_semaforo(req, base, cfg)


def _chamar_sem_semaforo(req: QuoteRequest, base: str, cfg) -> Resposta:
    # A espera no semáforo NÃO conta contra o read timeout: é fila nossa, não latência
    # do legado. O cronômetro começa aqui.
    t0 = time.monotonic()
    try:
        r = httpx.post(
            f"{base}/quote",
            json=req.to_api_payload(),
            timeout=httpx.Timeout(
                connect=cfg.quote_connect_timeout_s, read=cfg.quote_read_timeout_s,
                write=cfg.quote_connect_timeout_s, pool=cfg.quote_connect_timeout_s,
            ),
        )
    except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
        return Resposta(None, None, int((time.monotonic() - t0) * 1000), timeout=True)
    ms = int((time.monotonic() - t0) * 1000)
    try:
        corpo = r.json()
    except Exception:  # noqa: BLE001
        corpo = None
    return Resposta(r.status_code, corpo, ms)


def sondar_upstream(url: str | None = None) -> UpstreamHealth:
    """`GET /health` do legado. Não passa pelo sorteio de instabilidade — e é
    exatamente por isso que ele não mede a saúde da cotação."""
    base = url or get_settings().quote_api_url
    t0 = time.monotonic()
    try:
        r = httpx.get(f"{base}/health", timeout=3.0)
        r.raise_for_status()
        return UpstreamHealth(status="ok",
                              latency_ms=int((time.monotonic() - t0) * 1000),
                              nota=NOTA_HEALTH)
    except Exception:  # noqa: BLE001
        return UpstreamHealth(status="unreachable", latency_ms=None, nota=NOTA_HEALTH)
