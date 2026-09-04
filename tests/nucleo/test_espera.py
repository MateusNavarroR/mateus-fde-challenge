"""A espera visível: aviso aos 6 s, reforço aos ~20 s.

O relógio é o do **lead** — conta da chegada da mensagem dele —, e o disparo é de
dentro da tool de cotação, não de um watchdog na camada de conversa.

Estes testes usam limiares encurtados e a instância lenta real: o objetivo é provar
**quando** o aviso sai, não simular o relógio.
"""

from __future__ import annotations

import datetime as dt
import os
import time

import httpx
import pytest

from app import textos
from app.contracts.quote import QuoteRequest
from app.quote import client
from app.quote.breaker import resetar_breaker
from app.quote.job import executar_job

pytestmark = [pytest.mark.db, pytest.mark.live, pytest.mark.serial]

LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
LENTA = os.getenv("QUOTE_API_LENTA", "http://localhost:8003")

REQ = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
                   cep="07145-200", data_inicio=dt.date(2026, 10, 17))


@pytest.fixture(autouse=True)
def bancada():
    for url in (LIMPA, FALHA, LENTA):
        try:
            httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
        except Exception:  # noqa: BLE001
            pytest.skip(f"bancada indisponível: {url}")
    resetar_breaker()
    client.resetar_semaforo()
    yield
    resetar_breaker()
    client.resetar_semaforo()


class Coletor:
    def __init__(self):
        self.msgs: list[tuple[float, str]] = []
        self.t0 = time.monotonic()

    def __call__(self, texto: str) -> None:
        self.msgs.append((time.monotonic() - self.t0, texto))

    @property
    def textos(self):
        return [t for _, t in self.msgs]


def _cfg(monkeypatch, url, **kw):
    from app.config import get_settings

    c = get_settings()
    monkeypatch.setattr(c, "quote_api_url", url)
    for k, v in kw.items():
        monkeypatch.setattr(c, k, v)
    return c


def test_falha_rapida_com_retry_rapido_nao_avisa(sessao, conversa, monkeypatch):
    """O 5xx volta em ~2 ms e o retry responde ~250 ms depois — o lead não percebe.

    É por isso que o gatilho é por **tempo**, e não por falha de tentativa: um aviso
    disparado pela falha cairia nessa janela e produziria "tô verificando…" seguido do
    preço um quarto de segundo depois. Ruído, não cuidado.
    """
    _cfg(monkeypatch, FALHA, aviso_espera_s=6.0, reforco_espera_s=20.0,
         quote_backoff_teto_s=0.01)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos == []


def test_aviso_sai_na_espera_longa(sessao, conversa, monkeypatch):
    """Instância lenta: 8 s de sono. Com o limiar em 1 s, o aviso tem que sair."""
    _cfg(monkeypatch, LENTA, aviso_espera_s=1.0, reforco_espera_s=99.0)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert textos.AVISO_ESPERA in col.textos


def test_aviso_e_reforco_na_ordem(sessao, conversa, monkeypatch):
    _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
         quote_backoff_teto_s=0.2)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]


def test_cada_aviso_sai_uma_vez_so(sessao, conversa, monkeypatch):
    """Três tentativas com o limiar baixo poderiam repetir o aviso a cada laço."""
    _cfg(monkeypatch, FALHA, aviso_espera_s=0.01, reforco_espera_s=0.02,
         quote_backoff_teto_s=0.2)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos.count(textos.AVISO_ESPERA) == 1
    assert col.textos.count(textos.REFORCO) == 1


def test_relogio_e_o_do_lead_nao_o_da_tool(sessao, conversa, monkeypatch):
    """O turno gasta a latência do modelo ANTES da tool. Contando do início da tool,
    o lead ficaria 8 s no escuro antes do aviso."""
    _cfg(monkeypatch, LIMPA, aviso_espera_s=2.0, reforco_espera_s=99.0)
    col = Coletor()
    # o lead escreveu 3 s atrás; a /quote limpa responde em milissegundos
    executar_job(sessao, conversa.id, REQ,
                 chegada_do_lead=time.monotonic() - 3.0, avisar=col)
    assert textos.AVISO_ESPERA in col.textos


def test_sucesso_rapido_nao_avisa(sessao, conversa, monkeypatch):
    _cfg(monkeypatch, LIMPA, aviso_espera_s=6.0, reforco_espera_s=20.0)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos == []


def test_a_sequencia_degradada_completa(sessao, conversa, monkeypatch):
    """O que o avaliador vai ler no transcript degradado: aviso, reforço, e o job
    terminando `failed` — nunca um preço inventado."""
    _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
         quote_backoff_teto_s=0.2)
    col = Coletor()
    q = executar_job(sessao, conversa.id, REQ, avisar=col)
    assert q.status == "failed"
    assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]
    assert not any("R$" in t for t in col.textos)
