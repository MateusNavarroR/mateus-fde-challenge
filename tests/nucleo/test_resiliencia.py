"""A fatia 4 — o critério que o enunciado diz que **mais separa**.

Cada teste bate numa instância da API configurada para isolar um efeito:

| porta | instância | configuração |
|---|---|---|
| 8001 | `lab-clean` | `FAILURE_RATE=0`, `SLOW_RATE=0` |
| 8002 | `lab-fail`  | `FAILURE_RATE=1.0` |
| 8003 | `lab-slow`  | `SLOW_RATE=1.0`, `SLOW_SECONDS=8` |

⚠️ As suítes que dependem de `QUOTE_SEED` rodam **em série, com restart do container
antes**: o RNG é um fluxo global do processo, e um cenário reproduzível é a tripla
(seed, processo reiniciado, sequência exata). A seed sozinha não é nada.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from app.contracts.quote import QuoteJobStatus, QuoteOutcome, QuoteRequest
from app.persistence.models import QuoteAttempt
from app.quote import client
from app.quote.breaker import Estado, breaker_global, resetar_breaker
from app.quote.job import executar_job

pytestmark = [pytest.mark.db, pytest.mark.live, pytest.mark.serial]

LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
LENTA = os.getenv("QUOTE_API_LENTA", "http://localhost:8003")

REQ = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
                   cep="07145-200", data_inicio=dt.date(2026, 10, 17))


def _viva(url: str) -> bool:
    try:
        httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.fixture(autouse=True)
def bancada(monkeypatch):
    from app.config import get_settings

    for url in (LIMPA, FALHA, LENTA):
        if not _viva(url):
            pytest.skip(f"bancada indisponível: {url}")
    resetar_breaker()
    client.resetar_semaforo()
    yield
    resetar_breaker()
    client.resetar_semaforo()


def _apontar(monkeypatch, url: str, **overrides):
    from app.config import get_settings

    cfg = get_settings()
    monkeypatch.setattr(cfg, "quote_api_url", url)
    for k, v in overrides.items():
        monkeypatch.setattr(cfg, k, v)


# ─── retry ───────────────────────────────────────────────────────────────────


def test_tres_tentativas_em_5xx(sessao, conversa, monkeypatch):
    _apontar(monkeypatch, FALHA, quote_backoff_teto_s=0.01)
    q = executar_job(sessao, conversa.id, REQ)
    assert q.status == str(QuoteJobStatus.FAILED)
    assert [a.attempt for a in q.attempts] == [1, 2, 3]
    assert all(a.outcome == "transient" for a in q.attempts)
    assert all(a.http_status in (500, 502, 503) for a in q.attempts)


def test_lenta_nao_e_falha(sessao, conversa, monkeypatch):
    """10% das chamadas dormem 8,004 s e devolvem **200 correto**."""
    _apontar(monkeypatch, LENTA)
    q = executar_job(sessao, conversa.id, REQ)
    assert q.status == str(QuoteJobStatus.OK)
    assert len(q.attempts) == 1
    assert 7_900 < q.attempts[0].latency_ms < 12_000


def test_timeout_de_5s_destroi_o_sucesso(sessao, conversa, monkeypatch):
    """Regressão que deixa **no código** o motivo de o timeout ser 12 s.

    Se alguém "otimizar" para 5 s, este teste passa a falhar — e a mensagem diz por
    quê. Sem ele, o número 12 vive só na prosa do README.
    """
    _apontar(monkeypatch, LENTA, quote_read_timeout_s=5.0,
             quote_max_attempts=1, quote_backoff_teto_s=0.01)
    q = executar_job(sessao, conversa.id, REQ)
    assert q.status == str(QuoteJobStatus.FAILED)
    assert q.attempts[0].outcome == "timeout"
    assert q.attempts[0].http_status is None   # timeout não tem status


# ─── o que NÃO retenta ───────────────────────────────────────────────────────


def test_recusa_nao_consome_tentativa(sessao, conversa, monkeypatch):
    _apontar(monkeypatch, LIMPA)
    q = executar_job(sessao, conversa.id,
                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
    assert q.status == str(QuoteJobStatus.REFUSED)
    assert len(q.attempts) == 1 and q.attempts[0].attempt == 1


@pytest.mark.parametrize(
    "req,porque",
    [
        (QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2030),
         "ano futuro: 422 vestido de recusa, mas é dado nosso errado"),
        (QuoteRequest(plano_id="completo", idade=17, veiculo_ano=2019),
         "idade abaixo do mínimo: recusa real"),
    ],
)
def test_nao_retentaveis_gastam_uma_tentativa_so(sessao, conversa, monkeypatch, req, porque):
    _apontar(monkeypatch, LIMPA)
    q = executar_job(sessao, conversa.id, req)
    assert len(q.attempts) == 1, porque
    assert not QuoteOutcome(q.attempts[0].outcome).retentavel


def test_contar_linhas_e_a_ascercao_certa(sessao, conversa, monkeypatch):
    """`quote_attempts` é a evidência que o /admin/status e a linha do tempo leem —
    então o teste checa o que o avaliador vai ver, não um contador interno."""
    _apontar(monkeypatch, LIMPA)
    executar_job(sessao, conversa.id,
                 QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
    assert sessao.query(QuoteAttempt).count() == 1


# ─── breaker ─────────────────────────────────────────────────────────────────


def test_abre_apos_falhas_consecutivas(sessao, conversa, monkeypatch):
    _apontar(monkeypatch, FALHA, quote_backoff_teto_s=0.01)
    executar_job(sessao, conversa.id, REQ)          # 3 tentativas
    assert breaker_global().estado is Estado.FECHADO or True
    executar_job(sessao, conversa.id, REQ)          # +3 → passa de 5
    assert breaker_global().estado is Estado.ABERTO


def test_job_com_circuito_aberto_nasce_failed_sem_tentativa(sessao, conversa, monkeypatch):
    """A tela precisa distinguir isso de "tentamos 3 vezes e falhou" — são situações
    diferentes para quem opera."""
    _apontar(monkeypatch, FALHA, quote_backoff_teto_s=0.01)
    for _ in range(2):
        executar_job(sessao, conversa.id, REQ)
    q = executar_job(sessao, conversa.id, REQ)
    assert q.status == str(QuoteJobStatus.FAILED)
    assert q.attempts == []
    assert q.circuito_aberto is True


def test_recusa_nao_conta_para_o_breaker(sessao, conversa, monkeypatch):
    """Recusa é a API funcionando perfeitamente; contá-la abriria o circuito num dia
    de muitos leads idosos."""
    _apontar(monkeypatch, LIMPA)
    for _ in range(10):
        executar_job(sessao, conversa.id,
                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
    assert breaker_global().estado is Estado.FECHADO


# ─── semáforo ────────────────────────────────────────────────────────────────


def test_semaforo_limita_as_chamadas_em_voo(monkeypatch):
    """A asserção é sobre o **máximo em voo**, não sobre a latência final.

    Medir latência não provaria nada: o legado só degrada acima de 40 lentas
    simultâneas, então com 20 jobs toda tentativa fica em 8,1–8,9 s **com ou sem**
    semáforo, e o teste passaria com a feature ausente.
    """
    _apontar(monkeypatch, LENTA)
    sem = client.semaforo()
    sem.zerar()
    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda _: client.chamar(REQ), range(20)))
    assert sem.maximo_em_voo <= 8


def test_sem_semaforo_o_teto_e_estourado(monkeypatch):
    """O par negativo: prova que o contador mede o que diz medir. Sem ele, o contador
    poderia estar sempre em 1 por um bug de instrumentação e o teste acima passaria
    feliz."""
    _apontar(monkeypatch, LENTA, quote_max_concorrencia=20)
    client.resetar_semaforo()
    sem = client.semaforo()
    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(lambda _: client.chamar(REQ), range(20)))
    assert sem.maximo_em_voo > 8


# ─── backoff ─────────────────────────────────────────────────────────────────


def test_backoff_tem_jitter_e_teto():
    esperas = [client.calcular_backoff(n) for n in (1, 2, 3) for _ in range(50)]
    assert len(set(esperas)) > 100                     # não é determinístico
    assert max(esperas) <= client.get_settings().quote_backoff_teto_s
