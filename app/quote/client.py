"""Cliente HTTP da `/quote`.

Tudo que é status, tentativa, backoff e semáforo vive **abaixo da fronteira da tool**.
Um modelo exposto a "recebi 503" improvisa, e improvisar aí é a falha que esta
arquitetura existe para impedir.

Nesta fatia o cliente só chama e classifica. Retry, backoff e semáforo chegam na
fatia 4 — construir tudo agora seria construir muito antes de qualquer coisa rodar.
"""

from __future__ import annotations

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


def chamar(req: QuoteRequest, *, url: str | None = None) -> Resposta:
    """Uma tentativa. Não retenta, não classifica além do necessário.

    O `read timeout` é **maior que `QUOTE_SLOW_SECONDS`**: 10% das chamadas dormem
    8,004 s e devolvem 200 correto, e um timeout menor converte sucesso em falha — que
    o retry então reproduz.
    """
    cfg = get_settings()
    base = url or cfg.quote_api_url
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
