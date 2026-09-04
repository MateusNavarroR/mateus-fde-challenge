"""Elegibilidade por conversa, lida das regras de `plans.json`.

**Isto não é o agente decidindo se o lead é elegível.** O agente nunca decide isso —
quem decide é a `/quote`, exatamente como quem decide o preço (DECISOES-FECHADAS §9).
O que este módulo faz é rotular o dataset *offline*, para que a suíte de replay saiba
qual desfecho esperar de cada conversa. É gabarito, não caminho de produção.

Os limites não são constantes escritas aqui: saem de `plans.json`, o mesmo arquivo que
o serviço de cotação lê. E a fronteira do veículo é **derivada do ano corrente**
(`ano_corrente - 20`), nunca fixada em 2005 — em 2027 o mesmo código recusa 2006 sem
ninguém precisar lembrar de editar um número.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

from app.contracts.quote import MotivoRecusa

from . import caminhos

#: O ano do veículo dentro de `veiculo_texto` ("Toyota Corolla 2008"). Só 19xx/20xx,
#: para não capturar cilindrada nem versão.
_ANO = re.compile(r"\b(?:19|20)\d{2}\b")


@dataclass(frozen=True)
class Regras:
    """O recorte de `plans.json` que decide recusa. Os multiplicadores de preço não
    entram: preço é assunto da `/quote`, e reimplementá-lo aqui criaria um segundo
    cálculo para divergir do dela (CLAUDE.md 1)."""

    idade_minima: int
    idade_maxima: int
    idade_veiculo_maxima: int

    def ano_veiculo_minimo(self, ano_corrente: int) -> int:
        """A fronteira, derivada — nunca 2005 escrito à mão."""
        return ano_corrente - self.idade_veiculo_maxima


def _faixa_que_recusa(faixas: list[dict]) -> dict:
    recusas = [f for f in faixas if f.get("recusar")]
    if len(recusas) != 1:
        raise ValueError(
            f"esperava exatamente uma faixa com `recusar`, achei {len(recusas)}"
        )
    return recusas[0]


@lru_cache(maxsize=4)
def carregar_regras(plans: Path | None = None) -> Regras:
    dados = json.loads((plans or caminhos.plans_json()).read_text(encoding="utf-8"))
    regras = dados["regras"]

    etaria = regras["faixa_etaria"]
    recusa_idade = _faixa_que_recusa(etaria)
    aceitas = [f for f in etaria if not f.get("recusar")]

    veiculo = regras["idade_veiculo"]
    recusa_veiculo = _faixa_que_recusa(veiculo)

    return Regras(
        idade_minima=min(f["idade_min"] for f in aceitas),
        # A faixa que recusa começa em 76 ⇒ o último ano aceito é 75.
        idade_maxima=int(recusa_idade["idade_min"]) - 1,
        # A faixa que recusa começa em 21 anos de uso ⇒ 20 é o máximo aceito.
        idade_veiculo_maxima=int(recusa_veiculo["anos_min"]) - 1,
    )


def extrair_ano_veiculo(veiculo_texto: str | None) -> int | None:
    """O ano é o último de `veiculo_texto`; `None` quando não há nenhum.

    `veiculo_texto` é coluna do dataset, não fala do lead: ela contém marca e modelo
    que o lead nunca pronunciou (DECISOES-FECHADAS §9). Aqui ela serve só como
    gabarito do ano — e o ano, esse sim, o lead diz.
    """
    achados = _ANO.findall(veiculo_texto or "")
    return int(achados[-1]) if achados else None


@dataclass(frozen=True)
class Elegibilidade:
    """O veredito de uma conversa, com os dois eixos separados.

    Guardar `por_idade` e `por_veiculo` além do motivo único é o que permite conferir
    a medição da `docs/API-COTACAO.md` §8.1 (280 · 531 · 60 · 751) sem recontar nada:
    o motivo único sozinho esconderia as 60 conversas recusadas pelos dois.
    """

    cotavel: bool
    por_idade: bool
    por_veiculo: bool
    motivo: MotivoRecusa | None
    ano_veiculo: int | None
    idade_veiculo: int | None


def avaliar(
    *,
    idade: int | None,
    veiculo_texto: str | None,
    ano_corrente: int | None = None,
    regras: Regras | None = None,
) -> Elegibilidade:
    """Aplica as regras de recusa a um perfil.

    A precedência é a do serviço: a faixa etária é avaliada antes da idade do veículo,
    então uma conversa recusada pelos dois recebe `IDADE_ACIMA` como motivo único —
    é o motivo que a `/quote` devolveria. `por_veiculo` continua marcado.
    """
    regras = regras or carregar_regras()
    ano_corrente = ano_corrente or date.today().year

    ano = extrair_ano_veiculo(veiculo_texto)
    idade_veiculo = None if ano is None else ano_corrente - ano

    idade_abaixo = idade is not None and idade < regras.idade_minima
    idade_acima = idade is not None and idade > regras.idade_maxima
    por_veiculo = idade_veiculo is not None and idade_veiculo > regras.idade_veiculo_maxima

    motivo: MotivoRecusa | None = None
    if idade_acima:
        motivo = MotivoRecusa.IDADE_ACIMA
    elif idade_abaixo:
        motivo = MotivoRecusa.IDADE_ABAIXO
    elif por_veiculo:
        motivo = MotivoRecusa.VEICULO_ANTIGO

    return Elegibilidade(
        cotavel=motivo is None,
        por_idade=idade_acima or idade_abaixo,
        por_veiculo=por_veiculo,
        motivo=motivo,
        ano_veiculo=ano,
        idade_veiculo=idade_veiculo,
    )
