"""A tool `quote_plan` — a fronteira entre o que o modelo decide e o que o sistema
garante.

Estes testes batem na `/quote` real com `FAILURE_RATE=0` (a instância `lab-clean`).
Resiliência é a fatia 4; aqui o que se prova é a **fronteira**.
"""

import datetime as dt
import os
import re

import pytest

from app.agent.tools import ContextoDoTurno, make_quote_plan
from app.contracts.quote import QuoteRequest
from app.persistence import repo
from app.persistence.models import Message, Quote, QuoteAttempt
from app.quote.job import executar_job

pytestmark = [pytest.mark.db, pytest.mark.live]

QUOTE_LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")


@pytest.fixture(autouse=True)
def api_limpa(monkeypatch):
    """`lab-clean`: FAILURE_RATE=0. Sem isso um 5xx aleatório reprovaria o teste da
    fronteira, que não é sobre resiliência."""
    import httpx

    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "quote_api_url", QUOTE_LIMPA)
    try:
        httpx.get(f"{QUOTE_LIMPA}/health", timeout=2.0).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip(f"/quote limpa indisponível em {QUOTE_LIMPA}")


@pytest.fixture
def canal(sessao, conversa):
    return CanalFalso(sessao, conversa.id)


@pytest.fixture
def ctx(sessao, conversa, canal):
    return ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)


class CanalFalso:
    """Recebe o que a tool manda ao lead. Síncrono, como `ContextoDoTurno.enviar`."""

    def __init__(self, sessao, conversation_id):
        self.sessao, self.conversation_id = sessao, conversation_id
        self.enviadas = []

    def __call__(self, texto, quote_id=None, autor="sistema"):
        # Passa pelo mesmo ponto de estrangulamento que a produção usa: assim o
        # guardrail é exercitado no teste, não contornado por ele.
        m = repo.gravar_mensagem(
            self.sessao, self.conversation_id, autor=autor, conteudo=texto,
            status="sent", quote_id=quote_id,
        )
        self.enviadas.append({"text": m.conteudo, "quote_id": m.quote_id, "autor": autor})


# ─── o job e a persistência ──────────────────────────────────────────────────


def test_job_ok_persiste_quote_e_attempt(sessao, conversa):
    req = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
                       cep="07145-200", data_inicio=dt.date(2026, 10, 17))
    q = executar_job(sessao, conversa.id, req)
    assert q.status == "ok"
    assert float(q.premio_mensal) == 392.25
    assert q.payload is not None and q.carencia_dias == 30
    a = sessao.query(QuoteAttempt).one()
    assert a.attempt == 1 and a.http_status == 200 and a.outcome == "ok"


def test_tentativa_e_gravada_mesmo_quando_o_job_falha(sessao, conversa):
    """É justamente quando falha que a linha do tempo importa."""
    req = QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022)
    q = executar_job(sessao, conversa.id, req)
    assert q.status == "refused"
    assert sessao.query(QuoteAttempt).count() == 1


def test_render_se_reconstroi_so_da_linha_de_quotes(sessao, conversa):
    """O guardrail precisa recalcular o texto canônico anos depois, a partir do
    payload guardado — inclusive a data de início."""
    from app.quote.renderer import render_de_payload

    req = QuoteRequest(plano_id="completo", idade=28, veiculo_ano=2019,
                       cep="07145-200", data_inicio=dt.date(2026, 10, 17))
    q = executar_job(sessao, conversa.id, req)
    assert "R$ 189,80" in render_de_payload(q.payload)


# ─── a fronteira: o que a tool devolve ao modelo ─────────────────────────────


def test_retorno_nao_contem_numero_de_dinheiro(ctx):
    r = make_quote_plan(ctx)("completo", 28, 2019, "07145-200", "2026-10-17")
    assert "cotado" in r
    assert not re.search(r"\d{1,3}(?:\.\d{3})*,\d{2}", r)   # nenhum valor monetário
    assert "392" not in r and "3000" not in r
    assert "R$" not in r


def test_retorno_nao_expoe_status_http_nem_tentativa(ctx):
    """Um modelo exposto a 'recebi 503' improvisa."""
    r = make_quote_plan(ctx)("completo", 28, 2019, "07145-200", "2026-10-17")
    for vazamento in ("200", "503", "http", "tentativa", "attempt", "breaker", "retry"):
        assert vazamento not in r.lower()


def test_a_tool_envia_o_bloco_ela_mesma(ctx, sessao, canal):
    make_quote_plan(ctx)("completo", 28, 2019, "07145-200", "2026-10-17")
    msg = sessao.query(Message).filter(Message.quote_id.isnot(None)).one()
    assert msg.autor == "sistema"
    assert "R$ 392,25" in msg.conteudo
    assert canal.enviadas[-1]["quote_id"] == msg.quote_id


def test_texto_do_modelo_e_descartado_apos_a_tool_falar(ctx):
    """Tudo que o lead precisava já foi dito deterministicamente; o que o modelo
    acrescentar é texto não verificado sobre uma cotação."""
    assert ctx.ja_enviou is False
    make_quote_plan(ctx)("completo", 28, 2019, "07145-200", "2026-10-17")
    assert ctx.ja_enviou is True


def test_descarte_vale_tambem_na_recusa(ctx):
    """Sem exceção: na recusa o risco não é preço alucinado, é promessa falsa."""
    make_quote_plan(ctx)("completo", 80, 2022)
    assert ctx.ja_enviou is True


def test_mensagem_de_preco_bate_byte_a_byte_com_o_render(ctx, sessao):
    """A verificação 3 do guardrail, ponta a ponta: se a mensagem persistida não
    fosse o render exato, `gravar_mensagem` teria levantado."""
    from app.quote.renderer import render_de_payload

    make_quote_plan(ctx)("completo", 28, 2019, "07145-200", "2026-10-17")
    msg = sessao.query(Message).filter(Message.quote_id.isnot(None)).one()
    q = sessao.get(Quote, msg.quote_id)
    assert msg.conteudo == render_de_payload(q.payload)


# ─── os quatro desfechos ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "args,esperado,motivo",
    [
        (("completo", 80, 2022), "recusado", "idade_acima_do_limite"),
        (("completo", 17, 2022), "recusado", "idade_abaixo_do_minimo"),
        (("completo", 35, 2000), "recusado", "veiculo_acima_de_20_anos"),
    ],
)
def test_recusas_reais(ctx, sessao, args, esperado, motivo):
    r = make_quote_plan(ctx)(*args)
    assert esperado in r and motivo in r
    assert sessao.query(Quote).one().motivo_recusa == motivo


@pytest.mark.parametrize(
    "args,porque",
    [
        (("ouro", 35, 2019), "plano inexistente: fomos NÓS que escolhemos"),
        (("completo", 35, 2030), "ano futuro: o dado está errado, o lead não é inelegível"),
        (("completo", 35, 2019, None, "15/07/2020"), "data no passado"),
    ],
)
def test_o_que_parece_recusa_e_nao_e(ctx, sessao, args, porque):
    """Dizer 'seu veículo não é aceito' a quem informou 2030 é mentir para ele."""
    from app import textos

    r = make_quote_plan(ctx)(*args)
    assert "dados_invalidos" in r, porque
    enviadas = [m.conteudo for m in sessao.query(Message).all()]
    assert not any(t in enviadas for t in textos.RECUSAS), porque


def test_recusa_envia_o_texto_do_mapa_fixo(ctx, sessao):
    from app import textos

    make_quote_plan(ctx)("completo", 80, 2022)
    msg = sessao.query(Message).one()
    assert msg.conteudo == textos.RECUSA_IDADE_ACIMA
    assert msg.autor == "sistema"


def test_texto_cru_da_api_nunca_chega_ao_lead(ctx, sessao):
    make_quote_plan(ctx)("completo", 80, 2022)
    conteudo = sessao.query(Message).one().conteudo
    assert "cotacao_recusada" not in conteudo
    assert "Idade acima do limite de aceitacao" not in conteudo  # sem acento, da API


def test_argumento_divergente_do_perfil_e_bad_request(ctx, sessao):
    """A redundância dos cinco argumentos vira checagem cruzada: divergir do que
    `qualify_lead` gravou é bug de extração, não cotação válida."""
    from app.agent.tools import make_qualify_lead

    make_qualify_lead(ctx)(idade=28)
    r = make_quote_plan(ctx)("completo", 45, 2019, "07145-200", "2026-10-17")
    assert "dados_invalidos" in r
    assert sessao.query(Quote).count() == 0


def test_estado_da_conversa_vira_cotado(ctx, sessao):
    make_quote_plan(ctx)("completo", 28, 2019, "07145-200", "2026-10-17")
    assert repo.obter_conversa(sessao, ctx.conversation_id).state == "cotado"
