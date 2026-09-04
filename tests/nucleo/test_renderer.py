"""O renderer — a única origem de texto com valor monetário.

Os números dos testes são **reais**, vindos da `/quote`: Completo, 28 anos, veículo
2019, CEP de prefixo de alto risco, início em 17/10/2026 → prêmio 392,25, franquia
3.000, pro-rata 189,80 em 15 dos 31 dias.
"""

import datetime as dt

import pytest

from app.contracts.quote import QuotePayload
from app.quote.renderer import brl, render

PAYLOAD = {
    "plano_id": "completo", "plano_nome": "Completo", "premio_mensal": 392.25,
    "franquia": 3000,
    "coberturas": ["colisao", "roubo", "furto", "terceiros", "vidros"],
    "multiplicadores": {"faixa_etaria": 1.25, "idade_veiculo": 1.15, "regiao": 1.3},
    "carencia": {"coberturas": ["roubo", "furto"], "dias": 30, "observacao": "..."},
    "moeda": "BRL",
    "primeiro_pagamento_pro_rata": {
        "dias_no_mes": 31, "dias_cobrados": 15, "valor_primeiro_pagamento": 189.80
    },
}
INICIO = dt.date(2026, 10, 17)


@pytest.fixture
def payload():
    return QuotePayload.model_validate(PAYLOAD)


@pytest.fixture
def sem_pro_rata():
    p = dict(PAYLOAD)
    p.pop("primeiro_pagamento_pro_rata")
    return QuotePayload.model_validate(p)


def test_bloco_completo(payload):
    t = render(payload, INICIO)
    assert "R$ 392,25" in t
    assert "R$ 3.000" in t                     # franquia sempre
    assert "R$ 189,80" in t and "15 dos 31 dias" in t
    assert "30 dias" in t                      # carência


def test_preco_esta_na_primeira_linha_de_conteudo(payload):
    linhas = [linha for linha in render(payload, INICIO).splitlines() if linha.strip()]
    assert "R$ 392,25" in linhas[1]            # depois de "Fechei sua cotação"


def test_agravo_de_cep_nunca_e_mencionado(payload):
    t = render(payload, INICIO).lower()
    for proibido in ("agravo", "cep", "região", "regiao", "1,30", "alto risco"):
        assert proibido not in t


def test_carencia_tem_marcador_proprio(payload):
    """Impossível pular sem ver — é a ressalva que gera reclamação depois."""
    linha = [linha for linha in render(payload, INICIO).splitlines() if "30 dias" in linha]
    assert len(linha) == 1
    assert linha[0].startswith("⚠️")


def test_dia_primeiro_diz_que_o_mes_e_integral(sem_pro_rata):
    """A ausência do campo É informação: silenciar gera a pergunta."""
    t = render(sem_pro_rata, dt.date(2026, 11, 1))
    assert "integral" in t
    assert "proporcional" in t  # "não tem valor proporcional"
    assert "R$ 189,80" not in t


def test_render_e_deterministico(payload):
    assert render(payload, INICIO) == render(payload, INICIO)


@pytest.mark.parametrize(
    "valor,esperado",
    [(392.25, "R$ 392,25"), (1025.14, "R$ 1.025,14"), (119.90, "R$ 119,90"),
     (3.87, "R$ 3,87")],
)
def test_formato_brasileiro(valor, esperado):
    assert brl(valor) == esperado


def test_coberturas_saem_legiveis(payload):
    t = render(payload, INICIO)
    assert "colisão" in t and "carro_reserva" not in t


def test_carencia_aparece_em_qualquer_plano():
    """Ela vem em 100% das respostas 200, nos três planos — por isso entra no
    template e não fica a critério do modelo lembrar."""
    for plano, nome in [("essencial", "Essencial"), ("premium", "Premium")]:
        p = dict(PAYLOAD, plano_id=plano, plano_nome=nome)
        assert "30 dias" in render(QuotePayload.model_validate(p), INICIO)
