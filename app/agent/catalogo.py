"""O catálogo de planos, buscado no boot.

`fetch_plans` **não é tool.** `GET /planos` é estável — não passa pelo sorteio de falha
(30/30 respondem 200 mesmo com `FAILURE_RATE=1.0`) e não muda durante a execução.
Buscar no boot elimina um round trip por conversa e põe o catálogo no prefixo cacheável
do system prompt.

**O catálogo entra sem nenhum valor monetário**, e é este o motivo mais forte. Se
`base_mensal` estivesse no prompt, o modelo poderia dizer "o Essencial começa em
R$ 119,90" — verdadeiro, e ainda assim um preço escrito pelo modelo. O guardrail
precisaria então de uma lista de exceções, e é ali que guardrail morre.

Sem número no contexto, a regra é uma linha sem ressalva: zero token monetário em texto
de autor `agente`.

O custo é uma pergunta que o agente não responde de cabeça — "qual a franquia do
Completo?" vira "isso eu te falo junto com o valor". Que é, por acaso, melhor prática de
vendas do que soltar a franquia antes do preço.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.config import get_settings


class CatalogoIndisponivel(RuntimeError):
    """Falhar alto é melhor que subir com catálogo vazio: um agente que não sabe os
    nomes dos planos conversa errado sem nenhum sinal."""


@dataclass(frozen=True)
class Plano:
    id: str
    nome: str
    coberturas: tuple[str, ...]
    #: Só a POSIÇÃO relativa da franquia, nunca o valor. Permite responder "qual tem
    #: franquia menor?" sem colocar um número no contexto do modelo.
    posicao_franquia: int


def buscar_planos(url: str | None = None, tentativas: int = 10) -> list[Plano]:
    """Busca `GET /planos` com retry limitado.

    O retry existe porque o `docker compose` sobe os serviços juntos e a ordem não é
    garantida — não é resiliência a instabilidade, que aqui não existe.
    """
    base = url or get_settings().quote_api_url
    erro: Exception | None = None
    for i in range(tentativas):
        try:
            r = httpx.get(f"{base}/planos", timeout=5.0)
            r.raise_for_status()
            dados = r.json()
            break
        except Exception as e:  # noqa: BLE001 - qualquer falha aqui é boot quebrado
            erro = e
            time.sleep(min(0.2 * (i + 1), 2.0))
    else:
        raise CatalogoIndisponivel(
            f"GET {base}/planos não respondeu em {tentativas} tentativas: {erro}"
        )

    brutos = dados["planos"]
    # Ordena por franquia para derivar a posição relativa — e descarta o valor.
    por_franquia = sorted(brutos, key=lambda p: p["franquia"])
    posicao = {p["id"]: i for i, p in enumerate(por_franquia)}
    return [
        Plano(
            id=p["id"],
            nome=p["nome"],
            coberturas=tuple(p["coberturas"]),
            posicao_franquia=posicao[p["id"]],
        )
        for p in brutos
    ]


def render_catalogo(planos: list[Plano]) -> str:
    """Texto que vai para o system prompt. **Nenhum valor monetário.**"""
    linhas = ["PLANOS DISPONÍVEIS (nomes e coberturas — os valores só vêm da cotação):"]
    for p in planos:
        linhas.append(f"- {p.nome} (`{p.id}`): cobre {', '.join(p.coberturas)}.")
    menor = min(planos, key=lambda p: p.posicao_franquia)
    maior = max(planos, key=lambda p: p.posicao_franquia)
    linhas.append(
        f"O {menor.nome} tem a menor franquia e o {maior.nome} a maior. "
        "Você NÃO sabe os valores de franquia nem de mensalidade: eles só existem "
        "depois da cotação, e você nunca os escreve."
    )
    return "\n".join(linhas)


def carregar_catalogo(url: str | None = None) -> str:
    return render_catalogo(buscar_planos(url))
