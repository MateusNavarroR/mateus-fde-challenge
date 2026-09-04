"""Bronze: o parquet do desafio, lido de onde ele está.

Não existe cópia versionada e não existe transformação. A camada é literalmente "o
arquivo original, mais a garantia de que ele é o que dizemos que é" — daí
`conferir_forma`, que falha alto se o esquema mudar debaixo do pipeline em vez de
deixar o silver sair errado em silêncio.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import caminhos

#: As colunas de que o silver depende. Uma coluna a mais no parquet não é problema;
#: uma a menos é.
COLUNAS_EXIGIDAS = (
    "conversation_id",
    "message_index",
    "timestamp",
    "sender_role",
    "sender_name",
    "message_type",
    "message_body",
    "channel",
    "conversation_outcome",
    "lead_idade_informada",
    "veiculo_texto",
)


class BronzeIndisponivel(RuntimeError):
    """O parquet do desafio não está no caminho configurado.

    Erro próprio, e não `FileNotFoundError`, porque a suíte o converte em `skip`: quem
    clona só este repositório não tem o dataset, e uma suíte vermelha por falta de um
    arquivo externo ensina a ignorar vermelho.
    """


def caminho() -> Path:
    return caminhos.bronze_parquet()


def ler() -> list[dict[str, Any]]:
    """Todas as linhas do bronze, na ordem física do arquivo.

    Ordem física de propósito: quem ordena é o silver, e ordenar aqui esconderia se o
    silver deixasse de ordenar.
    """
    alvo = caminho()
    if not alvo.is_file():
        raise BronzeIndisponivel(
            f"dataset do desafio não encontrado em {alvo} — "
            "aponte DATASET_BRONZE_PARQUET para ele"
        )
    try:
        import pyarrow.parquet as pq
    except ImportError as e:  # pragma: no cover - caminho de ambiente
        raise BronzeIndisponivel(f"pyarrow ausente: {e}") from e

    tabela = pq.read_table(alvo)
    conferir_forma(tabela.column_names)
    return tabela.to_pylist()


def conferir_forma(colunas: list[str]) -> None:
    faltando = [c for c in COLUNAS_EXIGIDAS if c not in colunas]
    if faltando:
        raise BronzeIndisponivel(f"colunas ausentes no bronze: {faltando}")
