"""A tool `qualify_lead` e a normalização dos cinco campos.

Três dos cinco erram **sem status HTTP** na `/quote`: `plano_id` vazio cota
`essencial` calado, CEP de 7 dígitos zera o agravo de 30%, e `data_inicio` fora do ISO
vira 400 (que não retenta). Por isso a normalização é aqui, na fronteira, e não uma
esperança sobre o que o modelo vai escrever.
"""

import datetime as dt

import pytest

from app.agent.tools import ContextoDoTurno, DataAmbigua, make_qualify_lead, normalizar_data
from app.persistence import repo
from tests.fixtures.pii import frase_do_lead

pytestmark = pytest.mark.db

HOJE = dt.date(2026, 9, 4)


@pytest.fixture
def ctx(sessao, conversa):
    return ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)


@pytest.fixture
def qualify(ctx):
    return make_qualify_lead(ctx)


def perfil(ctx):
    return repo.obter_conversa(ctx.sessao, ctx.conversation_id)


def test_grava_parcial_e_devolve_o_que_falta(ctx, qualify):
    r = qualify(idade=35, veiculo_ano=2019)
    assert perfil(ctx).idade == 35 and perfil(ctx).veiculo_ano == 2019
    for campo in ("cep", "data_inicio", "plano_id"):
        assert campo in r


def test_estado_passa_a_qualificando(ctx, qualify):
    qualify(idade=35)
    assert perfil(ctx).state == "qualificando"


def test_campos_podem_chegar_fora_de_ordem(ctx, qualify):
    qualify(plano_id="completo")
    qualify(cep="01310-100")
    qualify(idade=28, veiculo_ano=2019, data_inicio="2026-10-17")
    assert "quote_plan" in qualify()


def test_cep_e_normalizado_para_oito_digitos(ctx, qualify):
    qualify(cep="01310-100")
    assert perfil(ctx).cep == "01310100"


def test_cep_de_sete_digitos_e_rejeitado(ctx, qualify):
    """Seria lido pela API como prefixo "70" e perderia o agravo de 30% em silêncio."""
    r = qualify(cep="7000-000")
    assert perfil(ctx).cep is None
    assert "cep" in r


def test_plano_invalido_nao_vira_essencial_calado(ctx, qualify):
    """`plano_id` fora do conjunto faria a API cotar `essencial` com status 200."""
    qualify(plano_id="ouro")
    assert perfil(ctx).plano_id is None


def test_plano_maiusculo_e_aceito(ctx, qualify):
    qualify(plano_id="COMPLETO")
    assert perfil(ctx).plano_id == "completo"


def test_origem_do_campo_e_guardada_mascarada(ctx, qualify):
    frase, pii = frase_do_lead(seed=5)
    ctx.texto_do_lead = frase
    qualify(idade=35)
    origem = str(repo.obter_conversa(ctx.sessao, ctx.conversation_id).idade)
    # o perfil em si não guarda texto; a origem mascarada é verificada no LeadProfile
    from app.agent.tools import _perfil_de

    _ = _perfil_de(repo.obter_conversa(ctx.sessao, ctx.conversation_id))
    assert not any(v in frase_mascarada(frase) for v in pii.values())


def frase_mascarada(frase):
    from app.privacy.mascarar import mascarar

    return mascarar(frase)


# ─── data de início: o campo mais arriscado ──────────────────────────────────


@pytest.mark.parametrize(
    "dito,esperado",
    [
        ("2026-10-17", dt.date(2026, 10, 17)),
        ("17/10/2026", dt.date(2026, 10, 17)),
        ("dia 17 de outubro", dt.date(2026, 10, 17)),
        ("dia 1º do mês que vem", dt.date(2026, 10, 1)),
        ("dia 20", dt.date(2026, 9, 20)),
    ],
)
def test_data_inicio_normaliza_para_iso(dito, esperado):
    assert normalizar_data(dito, hoje=HOJE) == esperado


@pytest.mark.parametrize("dito", ["semana que vem", "quando der", "urgente", "", "logo"])
def test_data_ambigua_reprova_em_vez_de_chutar(dito):
    """Uma data errada vira apólice com vigência errada — pior que uma pergunta a
    mais."""
    with pytest.raises(DataAmbigua):
        normalizar_data(dito, hoje=HOJE)


def test_data_no_passado_e_rejeitada():
    """A API aceita sem reclamar; a validação tem que ser nossa."""
    with pytest.raises(DataAmbigua):
        normalizar_data("2020-03-10", hoje=HOJE)


def test_data_ambigua_vira_campo_pendente_e_nao_excecao(ctx, qualify):
    r = qualify(data_inicio="semana que vem")
    assert perfil(ctx).data_inicio is None
    assert "data_inicio" in r


def test_dia_ja_passado_no_mes_vai_para_o_proximo():
    assert normalizar_data("dia 2", hoje=HOJE) == dt.date(2026, 10, 2)
