"""A conferência de preço — a única parte do replay que é cálculo puro.

Cada teste aqui existe contra uma medição de `docs/API-COTACAO.md` §5, não contra uma
intuição: as cinco contas feitas à mão da §5.4, o tamanho do conjunto fechado, e a
constatação da §8.2 de que nenhum dos 8 preços do dataset pertence a ele.

Nenhum juiz de modelo aparece neste arquivo, e é isso que o `CLAUDE.md` 27 pede: harness
próprio só para o que é cálculo.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from qa.dataset import caminhos
from qa.replay import precos

pytestmark = pytest.mark.skipif(
    not caminhos.plans_json().is_file(),
    reason=f"plans.json do desafio não encontrado em {caminhos.plans_json()}",
)

#: `docs/API-COTACAO.md` §5.4 — calculados à mão e conferidos contra a resposta da API.
CONFERENCIA_A_MAO = [
    ("premium", 22, 2015, "08123-456", "1025.14"),
    ("essencial", 65, 2018, "01310-100", "193.04"),
    ("completo", 28, 2012, "21041-010", "494.58"),
    ("premium", 30, 2026, None, "339.90"),
    ("essencial", 75, 2006, "59015-000", "316.42"),
]

#: §8.2 — os 8 preços que o gerador do dataset sorteia, independentes do perfil.
PRECOS_DO_DATASET = [
    "129.90", "159.90", "189.90", "219.90", "259.90", "299.90", "349.90", "389.90",
]


@pytest.mark.parametrize("plano,idade,ano,cep,esperado", CONFERENCIA_A_MAO)
def test_cinco_casos_calculados_a_mao(plano, idade, ano, cep, esperado):
    """O gabarito da §5.4, reproduzido pelo nosso cálculo.

    É este teste que autoriza o resto do módulo a existir: se ele passa, a conta que
    gera os 72 valores é a mesma que a API roda, e a pertinência ao conjunto vira uma
    afirmação sobre a API e não sobre a nossa aritmética.
    """
    obtido = precos.premio_esperado(
        plano_id=plano, idade=idade, veiculo_ano=ano, cep=cep, ano_corrente=2026
    )
    assert obtido == Decimal(esperado)


def test_o_conjunto_fechado_tem_72_valores():
    """3 planos × 4 faixas etárias × 3 faixas de veículo × 2 regiões."""
    conjunto = precos.premios_possiveis()
    assert len(conjunto) == 72
    assert min(conjunto) == Decimal("119.90")
    assert max(conjunto) == Decimal("1025.14")


@pytest.mark.parametrize("preco", PRECOS_DO_DATASET)
def test_nenhum_preco_do_dataset_e_alcancavel(preco):
    """A prova da §8.2, em código: 2.500 de 2.500 cotações são impossíveis.

    É o teste que sustenta o `CLAUDE.md` 5 — o dataset nunca é few-shot de cotação.
    Sem ele, a afirmação seria uma linha de README.
    """
    assert not precos.e_alcancavel(Decimal(preco))


def test_cep_de_sete_digitos_subcota_sem_sinal_de_erro():
    """A segunda causa da subcotação (§8, fato 8): o zero à esquerda perdido.

    `"7000-000"` tem 7 dígitos, o prefixo lido vira `"70"`, o agravo some — e a API
    devolve 200. O prêmio resultante **pertence ao conjunto fechado**, o que é
    exatamente o que torna a pertinência sozinha insuficiente: só a comparação com o
    prêmio do perfil vê o erro.
    """
    correto = precos.premio_esperado(
        plano_id="essencial", idade=30, veiculo_ano=2024,
        cep="07000-000", ano_corrente=2026,
    )
    subcotado = precos.premio_esperado(
        plano_id="essencial", idade=30, veiculo_ano=2024,
        cep="7000-000", ano_corrente=2026,
    )
    assert correto != subcotado
    assert precos.e_alcancavel(subcotado)  # passa na conferência fraca...

    conferencia = precos.conferir(
        premio=subcotado, plano_id="essencial", idade=30, veiculo_ano=2024,
        cep="07000-000", ano_corrente=2026,
    )
    assert conferencia.alcancavel  # ...e mesmo assim
    assert not conferencia.exato   # é reprovado pela forte.
    assert not conferencia.ok


def test_cep_ausente_tambem_subcota():
    """"A omissão do CEP subcota em até 30%" (§5.3), em número."""
    com = precos.premio_esperado(
        plano_id="premium", idade=30, veiculo_ano=2024, cep="21041-010",
        ano_corrente=2026,
    )
    sem = precos.premio_esperado(
        plano_id="premium", idade=30, veiculo_ano=2024, cep=None, ano_corrente=2026
    )
    assert com == sem * Decimal("1.30")


@pytest.mark.parametrize("idade,ano", [(76, 2024), (17, 2024), (30, 2005)])
def test_perfil_recusado_nao_tem_premio(idade, ano):
    """Fora das faixas aceitas não existe prêmio — e `None` não é zero.

    Devolver `Decimal("0")` faria um perfil recusado passar por "grátis" em qualquer
    soma feita depois.
    """
    assert precos.premio_esperado(
        plano_id="essencial", idade=idade, veiculo_ano=ano, ano_corrente=2026
    ) is None


def test_plano_inexistente_nao_cota():
    """`plano_id: ""` cota `essencial` calado na API (§4.1) — aqui, não.

    O gabarito não repete o defeito da API de propósito: se o nosso cálculo também
    caísse para `essencial`, o replay nunca veria a cotação errada que esse defeito
    produz.
    """
    assert precos.premio_esperado(
        plano_id="", idade=30, veiculo_ano=2024, ano_corrente=2026
    ) is None
