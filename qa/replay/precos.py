"""O conjunto fechado de 72 prêmios, e a conferência de preço **por cálculo**.

`docs/DECISOES-FECHADAS.md` §6 e `CLAUDE.md` 27 dizem a mesma coisa com palavras
diferentes: harness próprio só para o que é cálculo. Preço é cálculo. Perguntar a um
juiz de modelo se R$ 494,58 está certo é trocar uma conta exata por uma opinião cara.

**Os números saem de `plans.json`**, o mesmo arquivo que o serviço de cotação lê — não
transcritos daqui. É o que impede a nossa noção de preço de divergir silenciosamente da
da API, exatamente como em `qa/dataset/elegibilidade.py`.

Duas conferências, e as duas importam:

- **pertinência ao conjunto** (`e_alcancavel`): 3 planos × 4 faixas etárias × 3 faixas de
  veículo × 2 regiões = 72 valores, de R$ 119,90 a R$ 1.025,14. É o teste que prova, na
  `docs/API-COTACAO.md` §8.2, que as 2.500 cotações do dataset são impossíveis — os 8
  preços dele não pertencem ao conjunto em nenhum plano;
- **igualdade ao prêmio do perfil** (`premio_esperado`): mais forte, e é a que pega a
  subcotação por CEP. Um CEP omitido ou de 7 dígitos produz um prêmio que **pertence ao
  conjunto** e mesmo assim está 30% abaixo do certo (API-COTACAO §5.3). Só a segunda
  conferência vê isso.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from qa.dataset import caminhos

#: Só dígitos. O CEP chega como o lead falou, e a API lê os dois primeiros dígitos do
#: que sobra — é assim que `"7000-000"` vira prefixo `"70"` e perde o agravo.
_SO_DIGITOS = re.compile(r"\D")


@dataclass(frozen=True)
class TabelaDePreco:
    """O recorte de `plans.json` que decide preço. As regras de recusa não entram:
    elas já têm dono em `qa.dataset.elegibilidade`, e um segundo lugar para a mesma
    fronteira é um segundo lugar para ela divergir."""

    bases: dict[str, Decimal]
    #: `(idade_min, idade_max, multiplicador)`, só as faixas que não recusam.
    faixas_etarias: tuple[tuple[int, int, float], ...]
    #: `(anos_min, anos_max, multiplicador)`, idem.
    faixas_veiculo: tuple[tuple[int, int, float], ...]
    prefixos_agravados: frozenset[str]
    multiplicador_regiao: float


@lru_cache(maxsize=4)
def carregar_tabela(plans: Path | None = None) -> TabelaDePreco:
    dados = json.loads((plans or caminhos.plans_json()).read_text(encoding="utf-8"))
    regras = dados["regras"]
    regiao = regras["regiao_cep"]
    return TabelaDePreco(
        bases={p["id"]: Decimal(str(p["base_mensal"])) for p in dados["planos"]},
        faixas_etarias=tuple(
            (int(f["idade_min"]), int(f["idade_max"]), float(f["multiplicador"]))
            for f in regras["faixa_etaria"]
            if not f.get("recusar")
        ),
        faixas_veiculo=tuple(
            (int(f["anos_min"]), int(f["anos_max"]), float(f["multiplicador"]))
            for f in regras["idade_veiculo"]
            if not f.get("recusar")
        ),
        prefixos_agravados=frozenset(regiao["prefixos_alto_risco"]),
        multiplicador_regiao=float(regiao["multiplicador"]),
    )


def multiplicador_regiao(cep: str | None, tabela: TabelaDePreco | None = None) -> float:
    """1,30 nos prefixos de risco, 1,00 no resto — **inclusive quando o CEP está errado**.

    Reproduz o comportamento da API, não o desejável: `None`, `""` e um CEP de 7 dígitos
    devolvem 1,00 sem nenhum sinal de erro. É de propósito — esta função é o gabarito, e
    um gabarito que "corrige" o CEP esconderia a subcotação que ele causa.
    """
    tabela = tabela or carregar_tabela()
    digitos = _SO_DIGITOS.sub("", cep or "")
    if len(digitos) != 8:
        return 1.0
    return (
        tabela.multiplicador_regiao
        if digitos[:2] in tabela.prefixos_agravados
        else 1.0
    )


def _mult(faixas: tuple[tuple[int, int, float], ...], valor: int) -> float | None:
    for minimo, maximo, m in faixas:
        if minimo <= valor <= maximo:
            return m
    return None


def premio_esperado(
    *,
    plano_id: str,
    idade: int,
    veiculo_ano: int,
    cep: str | None = None,
    ano_corrente: int | None = None,
    tabela: TabelaDePreco | None = None,
) -> Decimal | None:
    """O prêmio correto para este perfil, ou `None` se o perfil é recusado.

    `ano_corrente` é injetável pelo mesmo motivo do silver: a fronteira do veículo é
    derivada do relógio, e um teste que confere uma medição de 2026 precisa fixá-lo.
    Em produção o default é o ano de hoje — que é o relógio do **servidor da cotação**
    (API-COTACAO §4.2), não o nosso; a diferença só aparece na virada do ano.
    """
    tabela = tabela or carregar_tabela()
    base = tabela.bases.get((plano_id or "").lower().strip())
    if base is None:
        return None

    m_idade = _mult(tabela.faixas_etarias, idade)
    idade_veiculo = (ano_corrente or date.today().year) - veiculo_ano
    m_veiculo = _mult(tabela.faixas_veiculo, idade_veiculo)
    if m_idade is None or m_veiculo is None:
        return None

    return _arredondar(base, m_idade, m_veiculo, multiplicador_regiao(cep, tabela))


def _arredondar(base: Decimal, *multiplicadores: float) -> Decimal:
    """`round(base × m1 × m2 × m3, 2)`, um único `round` no fim (API-COTACAO §5).

    A conta é feita em `float` **de propósito**: é o que o serviço faz, e reproduzi-la
    em `Decimal` produziria um centavo de diferença em algum dos 72 valores sem que
    nenhum dos dois estivesse "errado". O `Decimal` entra depois, via `str`, para que a
    comparação com a coluna `Numeric(10, 2)` seja exata.
    """
    valor = float(base)
    for m in multiplicadores:
        valor *= m
    return Decimal(str(round(valor, 2)))


@lru_cache(maxsize=4)
def premios_possiveis(plans: Path | None = None) -> frozenset[Decimal]:
    """Os 72. Produto cartesiano das quatro dimensões, com a mesma conta de cima.

    Que sejam exatamente 72 não é presunção: `tests/dados/test_replay_precos.py`
    confere o tamanho, os extremos e os cinco casos calculados à mão da §5.4.
    """
    tabela = carregar_tabela(plans)
    return frozenset(
        _arredondar(base, m_idade, m_veiculo, m_regiao)
        for base in tabela.bases.values()
        for _, _, m_idade in tabela.faixas_etarias
        for _, _, m_veiculo in tabela.faixas_veiculo
        for m_regiao in (1.0, tabela.multiplicador_regiao)
    )


def e_alcancavel(premio: Decimal | float | str | None) -> bool:
    """O prêmio pertence ao conjunto fechado?

    Falso para todos os 8 preços do dataset — é essa a prova de que ele não pode ser
    few-shot de cotação (CLAUDE.md 5).
    """
    if premio is None:
        return False
    return Decimal(str(premio)) in premios_possiveis()


@dataclass(frozen=True)
class ConferenciaDePreco:
    """O veredito sobre uma cotação, com as duas conferências separadas.

    Guardar as duas em vez de um booleano só é o que distingue "o agente alucinou um
    preço" (fora do conjunto) de "o agente cotou com o CEP errado" (dentro do conjunto,
    e mesmo assim 30% abaixo). São defeitos diferentes, com correções diferentes.
    """

    premio: Decimal | None
    esperado: Decimal | None
    alcancavel: bool
    exato: bool

    @property
    def ok(self) -> bool:
        return self.alcancavel and self.exato


def conferir(
    *,
    premio: Decimal | float | str | None,
    plano_id: str,
    idade: int,
    veiculo_ano: int,
    cep: str | None = None,
    ano_corrente: int | None = None,
) -> ConferenciaDePreco:
    valor = None if premio is None else Decimal(str(premio))
    esperado = premio_esperado(
        plano_id=plano_id, idade=idade, veiculo_ano=veiculo_ano,
        cep=cep, ano_corrente=ano_corrente,
    )
    return ConferenciaDePreco(
        premio=valor,
        esperado=esperado,
        alcancavel=e_alcancavel(valor),
        exato=valor is not None and valor == esperado,
    )
