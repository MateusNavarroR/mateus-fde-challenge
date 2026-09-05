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

from tests.fixtures.pii import cep_de

pytestmark = [pytest.mark.db, pytest.mark.live, pytest.mark.serial]

LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")
LENTA = os.getenv("QUOTE_API_LENTA", "http://localhost:8003")

REQ = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
                   cep=cep_de("07"), data_inicio=dt.date(2026, 10, 17))


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
    # O piso entra comprimido junto com os limiares: quem encolhe o relógio tem
    # de encolher a política inteira, senão o teste mede uma mistura dos dois.
    _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
         piso_aviso_s=0.01)
    # Backoff FIXO: `calcular_backoff` é `uniform(0, teto)`, então o mínimo é zero e
    # o job de falha rápida pode terminar em ~10 ms — antes do reforço. O teste
    # falhava em ~1 execução a cada 4 medindo o jitter, e não a sequência de avisos.
    monkeypatch.setattr(client, "calcular_backoff", lambda _n: 0.15)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]


def test_cada_aviso_sai_uma_vez_so(sessao, conversa, monkeypatch):
    """Três tentativas com o limiar baixo poderiam repetir o aviso a cada laço."""
    _cfg(monkeypatch, FALHA, aviso_espera_s=0.01, reforco_espera_s=0.02,
         piso_aviso_s=0.005)
    # Backoff FIXO: `calcular_backoff` é `uniform(0, teto)`, então o mínimo é zero e
    # o job de falha rápida pode terminar em ~10 ms — antes do reforço. O teste
    # falhava em ~1 execução a cada 4 medindo o jitter, e não a sequência de avisos.
    monkeypatch.setattr(client, "calcular_backoff", lambda _n: 0.15)

    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos.count(textos.AVISO_ESPERA) == 1
    assert col.textos.count(textos.REFORCO) == 1


def test_relogio_e_o_do_lead_nao_o_da_tool(sessao, conversa, monkeypatch):
    """O turno gasta a latência do modelo ANTES da tool. Contando do início da tool,
    o lead ficaria 8 s no escuro antes do aviso.

    ⚠️ Este teste usava a instância LIMPA e afirmava que uma cotação de
    milissegundos, com o prazo do lead já vencido, deveria avisar. Isso é o
    contrário da decisão 1: o aviso sairia 0,1 s antes do preço. A propriedade que
    ele quer provar — que o relógio é o do lead — é real, e se prova com a instância
    LENTA, onde a espera existe de fato: o lead escreveu 5 s atrás, o limiar é 6 s,
    então o aviso sai ~1 s depois de a tool começar, e não 6 s depois.
    """
    _cfg(monkeypatch, LENTA, aviso_espera_s=6.0, reforco_espera_s=99.0,
         piso_aviso_s=0.2)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ,
                 chegada_do_lead=time.monotonic() - 5.0, avisar=col)

    assert textos.AVISO_ESPERA in col.textos
    quando = next(t for t, txt in col.msgs if txt == textos.AVISO_ESPERA)
    assert quando < 3.0, (
        f"o aviso saiu {quando:.1f}s depois do início da tool. Se o relógio fosse o "
        "da tool, sairia aos 6,0 s — os 5 s que o lead já esperou seriam ignorados."
    )


def test_sucesso_rapido_nao_avisa(sessao, conversa, monkeypatch):
    _cfg(monkeypatch, LIMPA, aviso_espera_s=6.0, reforco_espera_s=20.0)
    col = Coletor()
    executar_job(sessao, conversa.id, REQ, avisar=col)
    assert col.textos == []


def test_a_sequencia_degradada_completa(sessao, conversa, monkeypatch):
    """O que o avaliador vai ler no transcript degradado: aviso, reforço, e o job
    terminando `failed` — nunca um preço inventado."""
    _cfg(monkeypatch, FALHA, aviso_espera_s=0.05, reforco_espera_s=0.10,
         piso_aviso_s=0.01)
    # Backoff FIXO: `calcular_backoff` é `uniform(0, teto)`, então o mínimo é zero e
    # o job de falha rápida pode terminar em ~10 ms — antes do reforço. O teste
    # falhava em ~1 execução a cada 4 medindo o jitter, e não a sequência de avisos.
    monkeypatch.setattr(client, "calcular_backoff", lambda _n: 0.15)
    col = Coletor()
    q = executar_job(sessao, conversa.id, REQ, avisar=col)
    assert q.status == "failed"
    assert col.textos == [textos.AVISO_ESPERA, textos.REFORCO]
    assert not any("R$" in t for t in col.textos)


# ─── e agora pelo caminho de produção, que é onde estava quebrado ────────────


def test_o_aviso_sai_PELA_TOOL_e_nao_so_pelo_job(sessao, conversa, monkeypatch):
    """Todo teste acima passa `avisar=` direto para `executar_job`. Nenhum atravessa
    `quote_plan` — e era exatamente ali que a fiação estava quebrada.

    `make_quote_plan` montava `avisar=(lambda t: enviar(t))` **antes** de `def
    enviar`. O closure via um nome não vinculado, e quem o executa é uma
    `threading.Timer`: a `NameError` morria na thread do timer, sem subir para lugar
    nenhum. O turno seguia normal, o preço chegava no fim, e o aviso de espera nunca
    saía — em produção, em 100 % das cotações lentas.

    A suíte inteira ficou verde durante isso. Achado gerando o transcript.
    """
    from app.agent.tools import ContextoDoTurno, make_quote_plan

    _cfg(monkeypatch, LENTA, aviso_espera_s=1.0, reforco_espera_s=99.0)

    recebidas: list[str] = []
    ctx = ContextoDoTurno(
        sessao=sessao,
        conversation_id=conversa.id,
        enviar=lambda texto, quote_id=None, autor="sistema": recebidas.append(texto),
        chegada_do_lead=time.monotonic(),
    )
    # O perfil precisa bater com o argumento: a tool faz checagem cruzada.
    conversa.idade, conversa.veiculo_ano = 28, 2019
    sessao.flush()

    make_quote_plan(ctx)(
        plano_id="completo", idade=28, veiculo_ano=2019,
        cep=cep_de("07"), data_inicio="2026-10-17",
    )

    assert textos.AVISO_ESPERA in recebidas, (
        "o aviso de espera não chegou ao canal pelo caminho da tool. "
        f"Saiu: {recebidas}"
    )


def test_o_aviso_vem_ANTES_do_preco(sessao, conversa, monkeypatch):
    """A ordem é o ponto: um aviso de espera entregue depois do preço é pior do que
    nenhum — ele avisa sobre uma espera que já acabou."""
    from app.agent.tools import ContextoDoTurno, make_quote_plan

    _cfg(monkeypatch, LENTA, aviso_espera_s=1.0, reforco_espera_s=99.0)

    recebidas: list[str] = []
    ctx = ContextoDoTurno(
        sessao=sessao,
        conversation_id=conversa.id,
        enviar=lambda texto, quote_id=None, autor="sistema": recebidas.append(texto),
        chegada_do_lead=time.monotonic(),
    )
    conversa.idade, conversa.veiculo_ano = 28, 2019
    sessao.flush()

    make_quote_plan(ctx)(
        plano_id="completo", idade=28, veiculo_ano=2019,
        cep=cep_de("07"), data_inicio="2026-10-17",
    )

    assert len(recebidas) == 2, recebidas
    assert recebidas[0] == textos.AVISO_ESPERA
    assert "R$" in recebidas[1], "a segunda mensagem tem que ser o bloco de cotação"


def test_cotacao_rapida_nunca_avisa_mesmo_com_o_prazo_ja_vencido(
    sessao, conversa, monkeypatch
):
    """O aviso não pode correr com a resposta.

    Medido gerando o transcript do caminho feliz: o modelo levou 6,5 s para chegar à
    tool, o prazo do relógio do lead já tinha vencido, o atraso calculado deu 0 e o
    `Timer(0)` disparou 0,1 s ANTES de a `/quote` responder em 31 ms. O lead leu «tô
    buscando o valor» e, na linha seguinte, o preço.

    É o «só um instante» seguido da resposta que a decisão 1 rejeita — e o motivo de
    o aviso não ser um watchdog na camada de conversa. O piso resolve por construção.
    """
    col = Coletor()
    # Prazo VENCIDO: o lead já esperou 30 s antes de a tool começar.
    _cfg(monkeypatch, LIMPA, aviso_espera_s=6.0, reforco_espera_s=20.0,
         piso_aviso_s=1.0)

    executar_job(sessao, conversa.id, REQ,
                 chegada_do_lead=time.monotonic() - 30.0, avisar=col)

    assert col.textos == [], (
        "a /quote respondeu em milissegundos; nenhum aviso podia ter saído. "
        f"Saiu: {col.textos}"
    )


def test_o_piso_nao_engole_o_aviso_de_uma_espera_de_verdade(
    sessao, conversa, monkeypatch
):
    """O negativo: um piso alto demais mataria a política inteira em silêncio."""
    col = Coletor()
    _cfg(monkeypatch, LENTA, aviso_espera_s=6.0, reforco_espera_s=99.0,
         piso_aviso_s=1.0)

    executar_job(sessao, conversa.id, REQ,
                 chegada_do_lead=time.monotonic() - 30.0, avisar=col)

    assert textos.AVISO_ESPERA in col.textos
    # E saiu DEPOIS do piso, não na hora.
    quando = next(t for t, txt in col.msgs if txt == textos.AVISO_ESPERA)
    assert quando >= 0.9, f"o aviso saiu em {quando:.2f}s, antes do piso de 1,0 s"
