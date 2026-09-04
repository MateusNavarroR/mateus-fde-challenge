"""Silver: uma linha por mensagem, com PII mascarada e elegibilidade por conversa.

Três propriedades definem esta camada, e cada uma existe por causa de uma medição:

1. **PII mascarada por `app.privacy.mascarar.mascarar`** — CPF e CEP em 100% das
   conversas, telefone e e-mail em 55%, placa em 34% (API-COTACAO §8.3). Nenhum regex
   é reescrito aqui: uma segunda definição de "o que é PII" divergiria da primeira, e
   a varredura de `tests/nucleo/test_repo_publico.py` usa a primeira.
2. **Ordenação por `conversation_id` e `message_index`, nunca por `timestamp`** —
   2.495 das 2.500 conversas têm timestamp não monotônico. Ordenar pelo relógio
   embaralha 99,8% do corpus, e o replay literal (DECISOES-FECHADAS §9) depende da
   ordem certa das falas.
3. **Elegibilidade por conversa**, das regras de `plans.json`, com os dois eixos
   separados — 280 por idade, 531 por veículo, 60 pelos dois, 751 = 30,0% no total.

O silver **não é versionado**: é gerado sob demanda por `materializar()`, e o destino
default carrega o próprio `.gitignore` (ver `caminhos.dir_saida`). Um derivado de 26.470
mensagens é o maior artefato que este repositório poderia produzir, e um repositório
público não é lugar para ele mesmo mascarado.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Iterable

from app.privacy.mascarar import mascarar

from . import bronze, caminhos
from .elegibilidade import Elegibilidade, avaliar, carregar_regras

#: As colunas de texto livre do bronze. São as que carregam PII e as únicas que passam
#: pelo mascaramento — idade, ano do veículo, plano e data de início são dados de
#: qualificação e não são mascarados (docstring de `app/privacy/mascarar.py`).
COLUNAS_MASCARADAS = ("message_body", "veiculo_texto", "sender_name")

COLUNAS_SILVER = (
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
    "veiculo_ano",
    "veiculo_idade",
    "conversa_cotavel",
    "recusa_por_idade",
    "recusa_por_veiculo",
    "motivo_recusa",
    "timestamp_monotonico",
)


def _chave(linha: dict[str, Any]) -> tuple[str, int]:
    """A ordem canônica. `timestamp` não aparece aqui, e é o ponto inteiro."""
    return (str(linha["conversation_id"]), int(linha["message_index"]))


def _monotonico(mensagens: list[dict[str, Any]]) -> bool:
    """O relógio acompanha `message_index` nesta conversa?

    Vira coluna do silver em vez de virar descarte: é o rótulo que permite a um teste
    encontrar uma conversa fora de ordem sem fabricar uma, e é a evidência dos 99,8%
    ficando visível no artefato em vez de só na prosa.
    """
    ts = [m["timestamp"] for m in mensagens]
    return all(a <= b for a, b in zip(ts, ts[1:]))


def construir(
    linhas: Iterable[dict[str, Any]] | None = None,
    *,
    ano_corrente: int | None = None,
) -> list[dict[str, Any]]:
    """Bronze → silver, em memória.

    `ano_corrente` é injetável porque a fronteira do veículo é `ano_corrente - 20`: a
    medição de referência foi feita em 2026, e um teste que a confere precisa fixar o
    ano em vez de depender do relógio da máquina. Em produção o default é
    `date.today().year`, que é o mesmo relógio que a `/quote` usa.
    """
    brutas = list(linhas if linhas is not None else bronze.ler())
    ano_corrente = ano_corrente or date.today().year
    regras = carregar_regras()

    brutas.sort(key=_chave)

    por_conversa: dict[str, list[dict[str, Any]]] = {}
    for linha in brutas:
        por_conversa.setdefault(str(linha["conversation_id"]), []).append(linha)

    saida: list[dict[str, Any]] = []
    for conv_id, mensagens in por_conversa.items():
        cabeca = mensagens[0]
        veredito: Elegibilidade = avaliar(
            idade=cabeca["lead_idade_informada"],
            veiculo_texto=cabeca["veiculo_texto"],
            ano_corrente=ano_corrente,
            regras=regras,
        )
        monotonico = _monotonico(mensagens)
        for m in mensagens:
            saida.append(
                {
                    "conversation_id": conv_id,
                    "message_index": int(m["message_index"]),
                    "timestamp": m["timestamp"],
                    "sender_role": m["sender_role"],
                    "message_type": m["message_type"],
                    "channel": m["channel"],
                    "conversation_outcome": m["conversation_outcome"],
                    "lead_idade_informada": m["lead_idade_informada"],
                    **{c: mascarar(m[c]) for c in COLUNAS_MASCARADAS},
                    "veiculo_ano": veredito.ano_veiculo,
                    "veiculo_idade": veredito.idade_veiculo,
                    "conversa_cotavel": veredito.cotavel,
                    "recusa_por_idade": veredito.por_idade,
                    "recusa_por_veiculo": veredito.por_veiculo,
                    "motivo_recusa": (
                        str(veredito.motivo) if veredito.motivo is not None else None
                    ),
                    "timestamp_monotonico": monotonico,
                }
            )
    return saida


def resumo_elegibilidade(silver: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Contagem por conversa, não por mensagem — é a unidade das medições da §8.1."""
    vistas: dict[str, dict[str, Any]] = {}
    for linha in silver:
        vistas.setdefault(linha["conversation_id"], linha)
    idade = sum(1 for v in vistas.values() if v["recusa_por_idade"])
    veiculo = sum(1 for v in vistas.values() if v["recusa_por_veiculo"])
    ambos = sum(
        1 for v in vistas.values() if v["recusa_por_idade"] and v["recusa_por_veiculo"]
    )
    return {
        "conversas": len(vistas),
        "idade": idade,
        "veiculo": veiculo,
        "ambos": ambos,
        "incotaveis": sum(1 for v in vistas.values() if not v["conversa_cotavel"]),
    }


def materializar(
    destino: Path | None = None, *, ano_corrente: int | None = None
) -> Path:
    """Escreve o silver em parquet. Chamado sob demanda, nunca por import.

    O destino default é ignorado pelo Git por construção — ver `caminhos.dir_saida`.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    dados = construir(ano_corrente=ano_corrente)
    diretorio = destino or caminhos.dir_saida()
    diretorio.mkdir(parents=True, exist_ok=True)
    alvo = diretorio / "conversations_silver.parquet"

    tabela = pa.Table.from_pylist(dados)
    faltando = [c for c in COLUNAS_SILVER if c not in tabela.column_names]
    if faltando:  # pragma: no cover - guarda de programação
        raise RuntimeError(f"silver sem colunas esperadas: {faltando}")
    pq.write_table(tabela.select(list(COLUNAS_SILVER)), alvo)
    return alvo
