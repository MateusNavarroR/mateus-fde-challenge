"""`python -m qa.dataset` — materializa o silver e imprime a conferência.

Não há passo escondido: o comando lê o bronze do caminho configurado, escreve o silver
no diretório ignorado pelo Git e mostra as contagens de elegibilidade ao lado das
medidas em `docs/API-COTACAO.md` §8.1.
"""

from __future__ import annotations

import sys

from . import bronze, caminhos
from .silver import construir, materializar, resumo_elegibilidade

ESPERADO = {"conversas": 2500, "idade": 280, "veiculo": 531, "ambos": 60, "incotaveis": 751}


def main() -> int:
    try:
        linhas = bronze.ler()
    except bronze.BronzeIndisponivel as e:
        print(f"bronze indisponível: {e}", file=sys.stderr)
        return 2

    print(f"bronze .......... {bronze.caminho()}  ({len(linhas)} mensagens)")
    dados = construir(linhas)
    alvo = materializar()
    print(f"silver .......... {alvo}  ({len(dados)} mensagens)")

    medido = resumo_elegibilidade(dados)
    print(f"\n{'':<14}{'medido':>8}{'esperado':>10}")
    for chave, esperado in ESPERADO.items():
        marca = "ok" if medido[chave] == esperado else "DIVERGE"
        print(f"{chave:<14}{medido[chave]:>8}{esperado:>10}  {marca}")
    pct = 100 * medido["incotaveis"] / medido["conversas"]
    print(f"\nincotáveis ...... {pct:.1f}% (esperado 30,0%)")
    print(f"saída ignorada pelo Git: {caminhos.dir_saida()}")
    return 0 if all(medido[k] == v for k, v in ESPERADO.items()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
