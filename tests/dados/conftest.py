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


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Pula a suíte de dados INTEIRA quando o material do desafio não está ao lado.

    O `plans.json` e o parquet vivem no repositório do desafio, como diretório irmão —
    decisão consciente: copiá-los para cá poria material de terceiro num repositório
    público, e um caminho absoluto no fonte violaria o invariante 13.

    O que faltava era o COMPORTAMENTO quando eles não estão lá. A fixture de bronze já
    pulava; quem depende do `plans.json` estourava `FileNotFoundError`. Numa avaliação
    externa, quem clonou o repositório público e rodou o comando do README recebeu 34
    tracebacks — e um traceback diz "está quebrado", enquanto um skip com motivo diz
    "isto aqui precisa de um arquivo que você não tem, e eis como obtê-lo".

    O `DATASET_PLANS_JSON` e o `DATASET_BRONZE_PARQUET` continuam sobrescrevendo, para
    quem organiza as pastas de outro jeito.
    """
    from qa.dataset.caminhos import plans_json

    caminho = plans_json()
    if caminho.is_file():
        return

    motivo = pytest.mark.skip(
        reason=(
            f"o material do desafio não está em {caminho}. Ele é externo a este "
            "repositório de propósito (é material de terceiro, e o repositório é "
            "público). Clone o repositório do desafio como diretório IRMÃO deste, ou "
            "aponte DATASET_PLANS_JSON e DATASET_BRONZE_PARQUET para onde ele estiver."
        )
    )
    for item in items:
        if "tests/dados" in str(getattr(item, "fspath", "")):
            item.add_marker(motivo)


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
