"""Amostra estratificada em dois eixos, e o custo de relógio que a obriga a existir.

**Por que estratificar.** Uma amostra aleatória de 30 conversas em 2.500 tem ~9 leads
incotáveis por acaso, e a chance de ela conter uma das **60 conversas recusadas pelos
dois motivos** é de 51%. Ou seja: metade das execuções não exercitaria o estrato mais
interessante do corpus — o que fixa, por medição, qual recusa a API reporta primeiro
(a etária, por precedência do serviço; ver `qa/dataset/elegibilidade.avaliar`).

**Os dois eixos.**

1. Os quatro `conversation_outcome` do dataset — `em_negociacao` 757, `ganho` 712,
   `perdido` 538, `sem_resposta` 493 (API-COTACAO §8.3). Não são alvo (o desfecho do
   dataset veio de um vendedor cujas cotações são 100% impossíveis); são variedade de
   tom e de objeção, que é o que muda o texto que o agente recebe.
2. Os motivos de recusa — 280 por idade, 531 por veículo, **60 por ambos**, 1.749
   cotáveis (API-COTACAO §8.1). Este eixo é alvo: ele decide o desfecho esperado.

Mais um estrato transversal: conversas com **mídia sem transcrição**, 1.789 mensagens em
6,8% do corpus. Ele não é um quinto motivo de recusa — é uma condição que pode aparecer
em qualquer célula — e por isso entra como **cota mínima** sobre a amostra já formada,
não como uma linha a mais na tabela.

**As contagens medidas se sobrepõem de propósito.** 280 e 531 incluem as 60; 280 + 531
− 60 = 751 = 30,0%. A partição usada para sortear é disjunta (`só idade` 220, `só
veículo` 471, `ambos` 60, `cotável` 1.749) porque uma conversa não pode ser sorteada
duas vezes; `contar_medido()` devolve a forma medida, que é a que a suíte confere.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from qa.replay.casos import CasoReplay

#: Os quatro estratos disjuntos do eixo de elegibilidade, na ordem em que a cota é
#: garantida. `ambos` vem primeiro porque é o menor e o mais informativo: numa amostra
#: de 30, ele é o único que a proporcionalidade pura zeraria.
ESTRATOS_ELEGIBILIDADE = ("ambos", "so_idade", "so_veiculo", "cotavel")

#: Medido em `docs/API-COTACAO.md` §8.1, com o ano corrente 2026. É a forma com
#: sobreposição — `idade` e `veiculo` incluem `ambos`.
MEDIDO = {"idade": 280, "veiculo": 531, "ambos": 60, "cotaveis": 1749, "conversas": 2500}

#: Conversas com pelo menos uma mensagem de mídia sem transcrição, e a fração mínima da
#: amostra reservada a elas. 6,8% das mensagens são mídia (§8.3); pedir ~10% da amostra
#: garante ao menos uma conversa com mídia mesmo em `n=30`, sem distorcer os outros
#: eixos além de uma conversa por célula.
FRACAO_MIDIA = 0.10


def estrato_de(caso: CasoReplay) -> str:
    """A célula disjunta do eixo de elegibilidade."""
    por_idade, por_veiculo = caso.elegibilidade.por_idade, caso.elegibilidade.por_veiculo
    if por_idade and por_veiculo:
        return "ambos"
    if por_idade:
        return "so_idade"
    if por_veiculo:
        return "so_veiculo"
    return "cotavel"


def contar_medido(casos: Iterable[CasoReplay]) -> dict[str, int]:
    """As contagens na forma da medição — com sobreposição, para conferir contra §8.1.

    Deliberadamente **não** é a partição disjunta: é a tabela publicada que a suíte
    reproduz, e reproduzir uma tabela diferente da publicada seria conferir outra coisa.
    """
    casos = list(casos)
    return {
        "conversas": len(casos),
        "idade": sum(1 for c in casos if c.elegibilidade.por_idade),
        "veiculo": sum(1 for c in casos if c.elegibilidade.por_veiculo),
        "ambos": sum(
            1
            for c in casos
            if c.elegibilidade.por_idade and c.elegibilidade.por_veiculo
        ),
        "cotaveis": sum(1 for c in casos if c.cotavel),
    }


@dataclass(frozen=True)
class Estratificacao:
    """A amostra e a prova de como ela ficou.

    Guardar a distribuição ao lado dos casos é o que permite ao relatório dizer "30
    conversas, 4 incotáveis, 1 pelos dois motivos, 3 com mídia" em vez de "30
    conversas" — que é uma afirmação sem informação.
    """

    casos: tuple[CasoReplay, ...]
    por_elegibilidade: dict[str, int]
    por_outcome: dict[str, int]
    com_midia: int
    #: Uma inferência por fala do lead. O relatório imprime a estimativa de parede.
    inferencias: int

    def __len__(self) -> int:
        return len(self.casos)


def _celulas(casos: Sequence[CasoReplay]) -> dict[tuple[str, str], list[CasoReplay]]:
    tabela: dict[tuple[str, str], list[CasoReplay]] = {}
    for caso in casos:
        tabela.setdefault((estrato_de(caso), caso.outcome), []).append(caso)
    return tabela


def _ordem_das_celulas(tabela: dict[tuple[str, str], list[CasoReplay]]) -> list[tuple[str, str]]:
    """Célula menor primeiro, `ambos` antes de tudo.

    A ordem decide quem recebe a vaga quando `n` é pequeno, e é por isso que ela é
    explícita e não o que o dicionário devolver: com `n=30` e 16 células, quatro
    células ficariam sem representante, e a escolha de quais não pode ser acidente de
    ordem de iteração.
    """
    return sorted(
        tabela,
        key=lambda chave: (
            ESTRATOS_ELEGIBILIDADE.index(chave[0]),
            len(tabela[chave]),
            chave[1],
        ),
    )


def amostrar(
    casos: Sequence[CasoReplay],
    *,
    n: int = 30,
    seed: int = 20260904,
    fracao_midia: float = FRACAO_MIDIA,
) -> Estratificacao:
    """`n` conversas, cobrindo as duas dimensões e a cota de mídia.

    O sorteio é **semeado e explícito**. Uma amostra que muda a cada execução torna
    impossível dizer se a taxa de extração caiu porque o agente piorou ou porque
    saíram outras conversas — e é exatamente essa a pergunta que o replay existe para
    responder.

    O algoritmo, em três passos:

    1. **uma vaga por célula não vazia**, na ordem de `_ordem_das_celulas` — é o que
       garante as 60 conversas recusadas pelos dois motivos em qualquer `n ≥ 16`;
    2. **o resto por proporção**, maior resto primeiro, para que a amostra grande
       convirja para a forma do corpus;
    3. **cota de mídia**, trocando dentro da mesma célula. Trocar dentro da célula é o
       que faz a cota transversal não desfazer a estratificação: sai uma conversa sem
       mídia e entra uma com mídia do mesmo estrato e do mesmo `outcome`.
    """
    if n <= 0:
        return Estratificacao((), {}, {}, 0, 0)
    casos = list(casos)
    if n >= len(casos):
        return _fechar(casos)

    rng = random.Random(seed)
    tabela = _celulas(casos)
    for grupo in tabela.values():
        # Ordenar por id antes de embaralhar tira a dependência da ordem física do
        # parquet: dois arquivos com as mesmas conversas em ordem diferente produzem
        # a mesma amostra para a mesma seed.
        grupo.sort(key=lambda c: c.conversation_id)
        rng.shuffle(grupo)

    ordem = _ordem_das_celulas(tabela)
    cotas = {chave: 0 for chave in ordem}

    for chave in ordem:
        if sum(cotas.values()) >= n:
            break
        cotas[chave] = 1

    restante = n - sum(cotas.values())
    if restante > 0:
        total_disponivel = sum(len(tabela[c]) - cotas[c] for c in ordem)
        exatos = {
            chave: restante * (len(tabela[chave]) - cotas[chave]) / total_disponivel
            for chave in ordem
        }
        for chave in ordem:
            cotas[chave] += int(exatos[chave])
        sobra = n - sum(cotas.values())
        # Maior resto primeiro; empate desfeito pela mesma ordem canônica de cima.
        for chave in sorted(
            ordem, key=lambda c: (-(exatos[c] % 1), ordem.index(c))
        )[:sobra]:
            if cotas[chave] < len(tabela[chave]):
                cotas[chave] += 1

    escolhidos = [c for chave in ordem for c in tabela[chave][: cotas[chave]]]
    escolhidos = _garantir_midia(escolhidos, tabela, cotas, n, fracao_midia)
    return _fechar(escolhidos)


def _garantir_midia(
    escolhidos: list[CasoReplay],
    tabela: dict[tuple[str, str], list[CasoReplay]],
    cotas: dict[tuple[str, str], int],
    n: int,
    fracao: float,
) -> list[CasoReplay]:
    """Troca dentro da célula até bater a cota mínima de conversas com mídia.

    Quando nenhuma célula tem uma conversa com mídia sobrando, a cota fica abaixo do
    alvo e isso **não** é erro: o relatório imprime `com_midia`, e um número abaixo do
    pedido é informação sobre o corpus, não uma falha da amostragem. Estourar aqui
    trocaria um número honesto por uma exceção.
    """
    alvo = max(1, round(n * fracao)) if fracao > 0 else 0
    presentes = [c for c in escolhidos if c.tem_midia_sem_transcricao]
    if len(presentes) >= alvo:
        return escolhidos

    dentro = {c.conversation_id for c in escolhidos}
    faltam = alvo - len(presentes)
    for chave in _ordem_das_celulas(tabela):
        if faltam <= 0:
            break
        grupo = tabela[chave]
        candidatos = [
            c for c in grupo[cotas[chave]:] if c.tem_midia_sem_transcricao
        ]
        substituiveis = [
            c
            for c in grupo[: cotas[chave]]
            if not c.tem_midia_sem_transcricao and c.conversation_id in dentro
        ]
        for entra, sai in zip(candidatos, substituiveis):
            if faltam <= 0:
                break
            escolhidos[escolhidos.index(sai)] = entra
            dentro.discard(sai.conversation_id)
            dentro.add(entra.conversation_id)
            faltam -= 1
    return escolhidos


def _fechar(escolhidos: Sequence[CasoReplay]) -> Estratificacao:
    escolhidos = list(escolhidos)
    return Estratificacao(
        casos=tuple(escolhidos),
        por_elegibilidade=dict(Counter(estrato_de(c) for c in escolhidos)),
        por_outcome=dict(Counter(c.outcome for c in escolhidos)),
        com_midia=sum(1 for c in escolhidos if c.tem_midia_sem_transcricao),
        inferencias=sum(c.inferencias for c in escolhidos),
    )
