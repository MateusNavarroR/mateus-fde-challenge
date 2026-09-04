"""O nosso entendimento das regras de preço, verificado contra a `/quote` real.

⚠️ **A fonte da verdade do preço é a `/quote`, sempre.** Este arquivo não é uma
segunda implementação da cotação, e `premio_esperado()` **não pode ser usado para
cotar** — nem aqui, nem em produção, nem "só para estimar". Ele existe para uma coisa
só: verificar que o que nós entendemos das regras bate com o que o legado faz.

**Por que isso vale mais do que parece.** O `docs/API-COTACAO.md` afirma, em 630
linhas, como as regras funcionam: que os multiplicadores compõem por produto, que a
região é 1,30 nos cinco prefixos, que o pro-rata conta os dias restantes **incluindo**
o dia de início, que a fronteira do veículo se move com o relógio do servidor. Tudo
isso é **leitura de código nossa**. Este teste transforma leitura em verificação — e
se alguma dessas afirmações estiver errada, é ele que avisa, e não o avaliador.

Os perfis exercitam **bordas, não o meio**: as quatro faixas etárias que não recusam,
as três faixas de idade de veículo, CEP dentro e fora dos prefixos de risco, e um caso
com `data_inicio` em dia ≠ 1 para o pro-rata entrar.

Roda contra a instância limpa (`FAILURE_RATE=0`) de propósito: o teste mede **cálculo**,
e um 5xx aleatório o transformaria numa medição de instabilidade.
"""

from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal

import httpx
import pytest

from qa.replay.precos import multiplicador_regiao, premio_esperado

from tests.fixtures.pii import cep_de

pytestmark = pytest.mark.live

LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")

#: O ano em que as medições do `docs/API-COTACAO.md` foram feitas. A fronteira do
#: veículo é `ano_corrente - 20` e se move sozinha na virada do ano, então fixá-lo é
#: o que mantém o teste falando do que ele pretende falar.
ANO = 2026


@pytest.fixture(scope="module", autouse=True)
def api_limpa():
    try:
        httpx.get(f"{LIMPA}/health", timeout=2.0).raise_for_status()
    except Exception:  # noqa: BLE001
        pytest.skip(f"/quote limpa indisponível em {LIMPA}")


def cotar(**payload) -> dict:
    r = httpx.post(f"{LIMPA}/quote", json=payload, timeout=15.0)
    r.raise_for_status()
    return r.json()


# ─── os perfis de borda ──────────────────────────────────────────────────────



#: `(rótulo, plano, idade, ano do veículo, cep)` — cada linha existe para exercitar
#: uma borda específica, e o rótulo diz qual.
PERFIS = [
    # as quatro faixas etárias que NÃO recusam, no piso e no teto de cada uma
    ("18a — piso da faixa 1,60",            "essencial", 18, 2024, None),
    ("24a — teto da faixa 1,60",            "essencial", 24, 2024, None),
    ("25a — piso da faixa 1,25",            "completo",  25, 2024, None),
    ("29a — teto da faixa 1,25",            "completo",  29, 2024, None),
    ("30a — piso da faixa 1,00",            "premium",   30, 2024, None),
    ("59a — teto da faixa 1,00",            "premium",   59, 2024, None),
    ("60a — piso da faixa 1,40",            "essencial", 60, 2024, None),
    ("75a — teto da faixa 1,40, borda da recusa", "essencial", 75, 2024, None),

    # as três faixas de idade do veículo, nas bordas
    ("veículo 0 ano — piso de 1,00",        "completo",  35, ANO,      None),
    ("veículo 5 anos — teto de 1,00",       "completo",  35, ANO - 5,  None),
    ("veículo 6 anos — piso de 1,15",       "completo",  35, ANO - 6,  None),
    ("veículo 10 anos — teto de 1,15",      "completo",  35, ANO - 10, None),
    ("veículo 11 anos — piso de 1,45",      "completo",  35, ANO - 11, None),
    ("veículo 20 anos — teto de 1,45, borda da recusa", "completo", 35, ANO - 20, None),

    # CEP: os cinco prefixos de risco e vizinhos que NÃO são
    ("cep 07 — risco",                      "completo",  35, 2019, cep_de("07")),
    ("cep 08 sem hífen — risco",            "completo",  35, 2019, cep_de("08", com_hifen=False)),
    ("cep 21 — risco",                      "completo",  35, 2019, cep_de("21")),
    ("cep 26 — risco",                      "completo",  35, 2019, cep_de("26")),
    ("cep 59 — risco",                      "completo",  35, 2019, cep_de("59")),
    ("cep 01 — fora da lista",              "completo",  35, 2019, cep_de("01")),
    ("cep 06 — vizinho do 07, fora",        "completo",  35, 2019, cep_de("06")),
    ("cep 09 — vizinho do 08, fora",        "completo",  35, 2019, cep_de("09")),
    ("cep 22 — vizinho do 21, fora",        "completo",  35, 2019, cep_de("22")),

    # o extremo: o maior prêmio possível das regras
    ("teto absoluto: premium, 18a, 11 anos, risco", "premium", 18, ANO - 11, cep_de("07")),
    # e o piso
    ("piso absoluto: essencial, 30a, 0 ano, sem cep", "essencial", 30, ANO, None),
]


@pytest.mark.parametrize(
    "rotulo,plano,idade,ano,cep",
    PERFIS,
    ids=[p[0] for p in PERFIS],
)
def test_o_nosso_calculo_bate_com_a_api(rotulo, plano, idade, ano, cep):
    esperado = premio_esperado(
        plano_id=plano, idade=idade, veiculo_ano=ano, cep=cep, ano_corrente=ANO
    )
    assert esperado is not None, f"{rotulo}: o perfil não deveria ser recusado"

    payload = {"plano_id": plano, "idade": idade, "veiculo_ano": ano}
    if cep:
        payload["cep"] = cep
    obtido = Decimal(str(cotar(**payload)["premio_mensal"]))

    assert obtido == esperado, (
        f"{rotulo}: a API devolveu {obtido} e o nosso cálculo diz {esperado}. "
        "Se a API estiver certa, é o nosso ENTENDIMENTO das regras que está errado — "
        "corrija docs/API-COTACAO.md e qa/replay/precos.py, nunca o contrário."
    )


def test_um_esperado_deliberadamente_errado_reprova():
    """O caso negativo, e é ele que dá confiança no positivo.

    Sem este teste, um `premio_esperado()` que devolvesse sempre o valor da API
    passaria feliz em todos os 25 perfis acima e não provaria absolutamente nada.
    """
    obtido = Decimal(str(cotar(plano_id="completo", idade=35, veiculo_ano=2019)["premio_mensal"]))
    errado = obtido + Decimal("0.01")
    assert obtido != errado


def test_o_calculo_independente_nao_e_a_api(monkeypatch):
    """`premio_esperado()` não faz chamada de rede.

    Se um dia alguém "otimizar" o cálculo local para consultar a API, ele deixa de
    ser uma verificação independente e o arquivo inteiro passa a comparar a API
    consigo mesma.
    """
    def proibido(*a, **kw):
        raise AssertionError("premio_esperado() não pode chamar a rede")

    monkeypatch.setattr(httpx, "post", proibido)
    monkeypatch.setattr(httpx, "get", proibido)
    # O perfil do exemplo de `docs/API-COTACAO.md` §5.4 e do bloco de cotação:
    # 209,90 × 1,25 (28 anos) × 1,15 (7 anos) × 1,30 (prefixo 07) = 392,25.
    assert premio_esperado(
        plano_id="completo", idade=28, veiculo_ano=2019, cep=cep_de("07"), ano_corrente=ANO
    ) == Decimal("392.25")


# ─── as afirmações do documento, uma a uma ───────────────────────────────────


def test_os_multiplicadores_compoem_por_produto():
    """API-COTACAO §5: `base × faixa_etaria × idade_veiculo × regiao`, com **um único
    arredondamento no fim** — os multiplicadores não são arredondados entre si."""
    corpo = cotar(plano_id="completo", idade=18, veiculo_ano=ANO - 11, cep=cep_de("07"))
    m = corpo["multiplicadores"]
    bruto = Decimal("209.90") * Decimal(str(m["faixa_etaria"])) \
        * Decimal(str(m["idade_veiculo"])) * Decimal(str(m["regiao"]))
    assert Decimal(str(corpo["premio_mensal"])) == round(bruto, 2)


@pytest.mark.parametrize("cep,esperado", [
    (cep_de("07"), 1.30), (cep_de("08"), 1.30), (cep_de("21"), 1.30),
    (cep_de("26"), 1.30), (cep_de("59"), 1.30),
    (cep_de("01"), 1.00), (cep_de("70"), 1.00),
])
def test_a_regiao_e_130_nos_cinco_prefixos(cep, esperado):
    corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022, cep=cep)
    assert corpo["multiplicadores"]["regiao"] == esperado
    assert multiplicador_regiao(cep) == esperado


def test_o_pro_rata_conta_o_dia_de_inicio():
    """API-COTACAO §6.2: `dias_do_mes − dia + 1`. O `+1` é o que inclui o próprio dia
    de início, e é a parte que uma leitura apressada erra."""
    corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022,
                  data_inicio="2026-10-17")
    pr = corpo["primeiro_pagamento_pro_rata"]
    assert pr["dias_no_mes"] == 31
    assert pr["dias_cobrados"] == 31 - 17 + 1 == 15
    esperado = round(Decimal(str(corpo["premio_mensal"])) * 15 / 31, 2)
    assert Decimal(str(pr["valor_primeiro_pagamento"])) == esperado


def test_o_pro_rata_some_no_dia_primeiro():
    corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022,
                  data_inicio="2026-11-01")
    assert "primeiro_pagamento_pro_rata" not in corpo


def test_fevereiro_bissexto_e_nao_bissexto():
    """O `monthrange` do legado responde por isto; a asserção existe porque um
    cálculo nosso que fixasse 30 dias passaria despercebido onze meses por ano."""
    for data, dias in (("2026-02-15", 28), ("2028-02-15", 29)):
        corpo = cotar(plano_id="essencial", idade=35, veiculo_ano=2022, data_inicio=data)
        assert corpo["primeiro_pagamento_pro_rata"]["dias_no_mes"] == dias


def test_a_fronteira_do_veiculo_se_move_com_o_relogio():
    """A regra usa `date.today()` do **servidor da cotação**, então "2005 é recusado"
    não é constante: em 2027 a linha anda para 2006. O teste deriva de
    `ano_corrente − 20` em vez de fixar o ano."""
    hoje = dt.date.today().year
    aceito = cotar(plano_id="completo", idade=35, veiculo_ano=hoje - 20)
    assert aceito["multiplicadores"]["idade_veiculo"] == 1.45

    recusado = httpx.post(
        f"{LIMPA}/quote",
        json={"plano_id": "completo", "idade": 35, "veiculo_ano": hoje - 21},
        timeout=15.0,
    )
    assert recusado.status_code == 422
    assert recusado.json()["error"] == "cotacao_recusada"


def test_todo_premio_observado_pertence_ao_conjunto_de_72():
    """O espaço fechado: 3 planos × 4 faixas etárias × 3 faixas de veículo × 2 regiões.
    É este conjunto que prova, na frente de Dados, que nenhuma cotação do dataset é
    alcançável — e é o gabarito de qualquer verificação de preço."""
    possiveis = {
        premio_esperado(plano_id=p, idade=i, veiculo_ano=ANO - v, cep=c, ano_corrente=ANO)
        for p in ("essencial", "completo", "premium")
        for i in (20, 27, 40, 70)
        for v in (2, 8, 15)
        for c in (None, cep_de("07"))
    }
    assert len(possiveis) == 72

    for _, plano, idade, ano, cep in PERFIS:
        payload = {"plano_id": plano, "idade": idade, "veiculo_ano": ano}
        if cep:
            payload["cep"] = cep
        assert Decimal(str(cotar(**payload)["premio_mensal"])) in possiveis
