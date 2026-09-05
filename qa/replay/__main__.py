"""`python -m qa.replay` — a linha de comando do replay.

**O default é 30 conversas, e isso é uma decisão de relógio, não de rigor.** Medido no
parquet: 16.470 mensagens do lead em 2.500 conversas, uma inferência por mensagem.

| Escopo | Inferências | Parede a 3 s |
|---|---|---|
| 2.500 conversas | 16.470 | ~14 h |
| 150 conversas | 991 | ~50 min |
| 50 conversas | 342 | ~17 min |
| **30 conversas (default)** | **203** | **~10 min** |

O volume completo fica atrás de `--tudo`, para ser uma decisão consciente e de
preferência noturna — não algo que trave a entrega no meio da tarde. E não comprime com
nada: inferência local não paraleliza sem GPU sobrando, e a `/quote` tem teto de 40
chamadas lentas simultâneas (API-COTACAO §3.3).

O comando **não executa nada** sem `--rodar`. Sem a flag ele imprime a amostra, a
estratificação e a estimativa de parede — que é o que alguém quer ver antes de gastar
dez minutos, e o único jeito de conferir a amostra sem pagar por ela.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from qa.dataset import bronze, caminhos
from qa.replay import amostra as amostragem
from qa.replay import casos as construtor
from qa.replay import relatorio as rel_mod
from qa.replay.executor import Executor, Modo

#: Fica em `qa/_saida/`, que carrega o próprio `.gitignore` com `*` — o relatório é
#: derivado do dataset e não é versionado, mesmo mascarado.
def destino_padrao() -> Path:
    return caminhos.dir_saida().parent / "replay"


def montar_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m qa.replay", description="Replay do dataset contra o agente."
    )
    p.add_argument(
        "--modo", choices=[str(Modo.EXTRACAO), str(Modo.DESFECHO)],
        default=str(Modo.DESFECHO),
        help="extracao afere idade, veiculo_ano e CEP; desfecho exercita a cadeia inteira.",
    )
    p.add_argument("--conversas", type=int, default=30, help="tamanho da amostra (default 30).")
    p.add_argument(
        "--tudo", action="store_true",
        help="as 2.500 conversas. ~14 h de parede — leia o docstring antes.",
    )
    p.add_argument("--seed", type=int, default=amostragem.SEED_PADRAO,
                   help="semente da amostragem.")
    p.add_argument("--ano-corrente", type=int, default=None,
                   help="fixa o ano para a fronteira do veículo (as medições são de 2026).")
    p.add_argument("--rodar", action="store_true",
                   help="executa de verdade. Sem isto, só imprime a amostra e o custo.")
    p.add_argument("--saida", type=Path, default=None, help="onde escrever o relatório JSON.")
    p.add_argument(
        "--continuar-no-402", action="store_true",
        help="não para no primeiro 402. O free tier do Ollama Cloud devolve 402 em três "
             "dos quatro modelos, e insistir só produz mais 402 — use com motivo.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = montar_parser().parse_args(argv)

    try:
        casos = construtor.montar(bronze.ler(), ano_corrente=args.ano_corrente)
    except bronze.BronzeIndisponivel as e:
        print(f"bronze indisponível: {e}", file=sys.stderr)
        return 2

    medido = amostragem.contar_medido(casos)
    print(f"corpus .......... {medido['conversas']} conversas, "
          f"{sum(c.inferencias for c in casos)} falas do lead")
    print(f"elegibilidade ... idade {medido['idade']} · veículo {medido['veiculo']} · "
          f"ambos {medido['ambos']} · cotáveis {medido['cotaveis']}")

    n = len(casos) if args.tudo else args.conversas
    estratificacao = amostragem.amostrar(casos, n=n, seed=args.seed)
    print(f"\namostra ......... {len(estratificacao)} conversas, "
          f"{estratificacao.inferencias} inferências "
          f"({rel_mod.estimativa_de_parede(estratificacao.inferencias)} de parede)")
    print(f"  elegibilidade   {estratificacao.por_elegibilidade}")
    print(f"  outcome         {estratificacao.por_outcome}")
    print(f"  com mídia       {estratificacao.com_midia}")

    if not args.rodar:
        print("\nnada foi executado. Repita com --rodar para valer.")
        return 0

    import asyncio

    executor = Executor(
        modo=Modo(args.modo),
        seed=args.seed,
        ano_corrente=args.ano_corrente,
        parar_no_402=not args.continuar_no_402,
    )
    rel = asyncio.run(executor.executar(estratificacao))

    destino = args.saida or (destino_padrao() / f"replay-{args.modo}-{args.seed}.json")
    rel.escrever(destino)
    print()
    print(rel_mod.render(rel))
    print(f"relatório ....... {destino}")
    return 0 if rel.aprovado else 1


if __name__ == "__main__":
    raise SystemExit(main())
