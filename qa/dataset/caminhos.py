"""Onde estão o bronze, o `plans.json` e a saída do silver.

Três decisões que valem o arquivo separado:

1. **Nenhum caminho absoluto local em código** (CLAUDE.md 13 — o repositório é
   público, e um `/home/<alguém>/...` no fonte é um nome vazando). Os defaults são
   relativos à raiz deste repositório e apontam para o repositório do desafio como
   diretório irmão, que é a disposição real.
2. **Tudo sobrescrevível por variável de ambiente**, para que a suíte rode em uma
   máquina que organize as pastas de outro jeito sem editar código.
3. **A saída do silver mora em diretório ignorado pelo Git**, e o `.gitignore` que a
   ignora vive dentro dela — ver `DIR_SAIDA` abaixo.
"""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

#: O repositório do desafio, como irmão deste. Somente leitura, sempre.
_DESAFIO_PADRAO = RAIZ.parent / "namastex-fde-challenge"


def _do_ambiente(var: str, padrao: Path) -> Path:
    bruto = os.getenv(var)
    return Path(bruto).expanduser() if bruto else padrao


def bronze_parquet() -> Path:
    """O parquet original do desafio. Nunca escrito, nunca copiado para cá."""
    return _do_ambiente(
        "DATASET_BRONZE_PARQUET", _DESAFIO_PADRAO / "dataset" / "conversations.parquet"
    )


def plans_json() -> Path:
    """As regras de elegibilidade vêm do `plans.json` do serviço de cotação.

    Ler o arquivo em vez de transcrever os números é o que impede a nossa noção de
    "quem é recusado" de divergir silenciosamente da da API — que é quem de fato
    decide (DECISOES-FECHADAS §9)."""
    return _do_ambiente(
        "DATASET_PLANS_JSON", _DESAFIO_PADRAO / "quote-service" / "data" / "plans.json"
    )


def dir_saida() -> Path:
    """Diretório do silver materializado.

    **Por que dentro de `qa/_saida/` e não em `data/`.** O silver é derivado do bronze:
    mesmo mascarado, é o artefato de maior volume que este repositório poderia produzir,
    e `tests/nucleo/test_repo_publico.py` varre justamente esse tipo de arquivo. A
    defesa escolhida é não deixar que ele possa ser versionado por acidente: o
    diretório carrega o próprio `.gitignore` com `*`, então `git add` não o alcança e a
    varredura não tem o que achar. A alternativa — depender de uma linha no `.gitignore`
    da raiz — protege igual enquanto ninguém mexe nela, e este arquivo é auto-suficiente.

    O silver também é **gerado sob demanda**: nenhum teste depende de ele já existir.
    """
    return _do_ambiente("DATASET_SILVER_DIR", RAIZ / "qa" / "_saida" / "silver")
