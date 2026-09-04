"""Fixtures da suíte de dados.

O bronze é externo a este repositório (é o parquet do desafio, somente leitura). Quando
ele não está no caminho configurado a suíte **pula** em vez de falhar: uma suíte
vermelha por falta de um arquivo que o repositório de propósito não versiona ensina a
ignorar vermelho.

Os testes que não dependem do bronze — mascaramento e ordenação — rodam sempre, sobre
linhas sintéticas com PII do gerador semeado de `tests/fixtures/pii.py` (CLAUDE.md 13b).
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def bronze_linhas():
    from qa.dataset import bronze

    try:
        return bronze.ler()
    except bronze.BronzeIndisponivel as e:
        pytest.skip(str(e))


@pytest.fixture(scope="session")
def silver(bronze_linhas):
    """Silver com o ano fixado em 2026.

    As medições de `docs/API-COTACAO.md` §8.1 foram feitas com esse ano corrente, e a
    fronteira do veículo é `ano_corrente - 20`. Fixar aqui é o que torna a asserção de
    751 incotáveis estável em 2027 — o código continua derivando a fronteira, o teste é
    que congela o relógio contra o qual a medição foi tirada.
    """
    from qa.dataset.silver import construir

    return construir(bronze_linhas, ano_corrente=2026)


@pytest.fixture(scope="session")
def casos_replay(bronze_linhas):
    """Os casos de replay do parquet, com o ano fixado em 2026.

    Mesmo motivo do fixture `silver`: as medições de `docs/API-COTACAO.md` §8.1 foram
    tiradas com esse ano corrente, e a fronteira do veículo é `ano_corrente - 20`. O
    código continua derivando a fronteira; o teste é que congela o relógio contra o qual
    a medição existe.

    Os casos carregam as falas **cruas** (o replay lê o bronze, não o silver — ver
    `qa/replay/casos.py`). Eles vivem em memória durante a sessão de teste e nada daqui
    é escrito em disco.
    """
    from qa.replay.casos import montar

    return montar(bronze_linhas, ano_corrente=2026)
