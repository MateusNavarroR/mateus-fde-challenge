"""Um caso de replay por conversa: as falas cruas do lead e o gabarito.

**Por que o bronze e não o silver.** O silver mascara `message_body`: injetar
`"meu cep é [CEP]"` no agente mediria o mascaramento, não a extração. O replay é o único
consumidor de `qa/` que precisa do texto cru, e ele o mantém **em memória**. Nada daqui
é escrito: o relatório mascara antes de serializar (`relatorio.py`).

**Três campos medidos: idade, `veiculo_ano` e CEP.** Marca e modelo ficam de fora, e o
motivo é uma observação sobre o dataset (DECISOES-FECHADAS §9): `veiculo_texto` contém
informação que o lead nunca disse — a coluna diz "Renault Sandero 2022" e a fala diz "e
um Sandero 2022". Penalizar o agente por não extrair uma marca que ninguém pronunciou é
medir o ruído do gabarito, não o agente.

O CEP entra com os outros dois porque aparece em 100% das conversas, está na fala do
lead, e errar nele **subcota em 30%** nos prefixos de risco (API-COTACAO §5.3). Depois
da idade e do ano do veículo, é o erro de extração de maior consequência que existe.

**`data_inicio` e `plano_id` não têm gabarito e não são medidos aqui**: o lead do
dataset nunca os informa. Quem os cobre é o respondedor roteirizado.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Iterable

from app.privacy.mascarar import _REGRAS
from qa.dataset.elegibilidade import Elegibilidade, avaliar, carregar_regras

#: O mesmo padrão de CEP que o mascaramento usa, reaproveitado como extrator do
#: gabarito. Uma segunda definição de "o que é um CEP" divergiria da primeira — e a
#: primeira é a que decide o que vaza. `test_replay_casos` prova que é a mesma.
_CEP = next(padrao for nome, padrao, _ in _REGRAS if nome == "cep")

_SO_DIGITOS = re.compile(r"\D")

#: `message_type` que carrega mídia. O corpo existe (`"[audio] mensagem de voz (18s)"`)
#: mas é um rótulo do gerador, não transcrição: não há conteúdo para extrair.
TIPOS_DE_MIDIA = ("audio", "image", "document")


@dataclass(frozen=True)
class Fala:
    """Uma mensagem do lead, crua, com a posição canônica."""

    message_index: int
    tipo: str
    texto: str

    @property
    def e_midia_sem_transcricao(self) -> bool:
        return self.tipo in TIPOS_DE_MIDIA


@dataclass(frozen=True)
class Gabarito:
    """O que o agente deveria ter extraído. Três campos, e só três.

    `cep` é PII e vive só em memória. Ele existe para a comparação com
    `conversations.cep`, que também é mascarado na gravação — a comparação é feita
    sobre os **dígitos normalizados**, do nosso lado, e nenhum dos dois chega ao
    relatório.
    """

    idade: int | None
    veiculo_ano: int | None
    cep: str | None

    #: Quais dos três o dataset de fato oferece. Um gabarito ausente não é um erro do
    #: agente, e contá-lo como erro rebaixaria a taxa de extração por culpa do dataset.
    @property
    def campos_com_gabarito(self) -> tuple[str, ...]:
        return tuple(
            c for c in ("idade", "veiculo_ano", "cep") if getattr(self, c) is not None
        )


@dataclass(frozen=True)
class CasoReplay:
    """Uma conversa do dataset, pronta para ser injetada.

    `outcome` é o `conversation_outcome` do dataset (`ganho`, `perdido`,
    `em_negociacao`, `sem_resposta`) — **não** é o desfecho esperado do nosso agente.
    Ele é um dos dois eixos da estratificação (`amostra.py`), nada mais: o desfecho que
    o dataset registrou veio de um vendedor cujas cotações são 100% impossíveis, e
    tratá-lo como alvo seria ensinar o alvo errado.
    """

    conversation_id: str
    outcome: str
    falas: tuple[Fala, ...]
    gabarito: Gabarito
    elegibilidade: Elegibilidade
    #: Cru, para o relatório citar a origem depois de mascarar.
    veiculo_texto: str | None = None
    _midias: int = field(default=0, repr=False)

    @property
    def cotavel(self) -> bool:
        return self.elegibilidade.cotavel

    @property
    def motivo_recusa(self) -> str | None:
        m = self.elegibilidade.motivo
        return None if m is None else str(m)

    @property
    def tem_midia_sem_transcricao(self) -> bool:
        return self._midias > 0

    @property
    def midias(self) -> int:
        return self._midias

    @property
    def inferencias(self) -> int:
        """Uma por fala do lead. É a unidade do custo de relógio (§9): 16.470 no
        volume completo, ~3 s cada, ~14 h de parede."""
        return len(self.falas)


def extrair_cep(falas: Iterable[Fala]) -> str | None:
    """O primeiro CEP que o lead pronuncia, normalizado para 8 dígitos.

    Normalizar aqui é o que torna a comparação justa: `conversations.cep` é
    `String(8)`, gravado pelo validador da `QuoteRequest`. Comparar `"01310-100"` com
    `"01310100"` reprovaria uma extração correta.
    """
    for fala in falas:
        achado = _CEP.search(fala.texto or "")
        if achado:
            digitos = _SO_DIGITOS.sub("", achado.group(0))
            if len(digitos) == 8:
                return digitos
    return None


def montar(
    linhas: Iterable[dict[str, Any]], *, ano_corrente: int | None = None
) -> list[CasoReplay]:
    """Bronze → casos de replay, em memória.

    Ordena por `(conversation_id, message_index)` e **nunca** por `timestamp`: 2.495 das
    2.500 conversas têm relógio não monotônico (API-COTACAO §8.3), e o replay literal
    depende da ordem certa das falas. É a mesma regra do silver, pelo mesmo motivo.

    A ordem dos casos devolvidos é a de primeira aparição da conversa no arquivo, que é
    estável para um mesmo parquet — a amostragem semeada depende disso.
    """
    regras = carregar_regras()
    ano_corrente = ano_corrente or date.today().year

    por_conversa: dict[str, list[dict[str, Any]]] = {}
    for linha in linhas:
        por_conversa.setdefault(str(linha["conversation_id"]), []).append(linha)

    casos: list[CasoReplay] = []
    for conv_id, mensagens in por_conversa.items():
        mensagens.sort(key=lambda m: int(m["message_index"]))
        cabeca = mensagens[0]

        falas = tuple(
            Fala(
                message_index=int(m["message_index"]),
                tipo=str(m["message_type"]),
                texto=m["message_body"] or "",
            )
            for m in mensagens
            if m["sender_role"] == "lead"
        )
        if not falas:
            # Conversa sem fala do lead não tem o que reproduzir. Não existe no
            # dataset medido; a guarda existe para que um parquet diferente falhe
            # ruidosamente na contagem em vez de produzir um caso vazio.
            continue

        veredito = avaliar(
            idade=cabeca["lead_idade_informada"],
            veiculo_texto=cabeca["veiculo_texto"],
            ano_corrente=ano_corrente,
            regras=regras,
        )
        casos.append(
            CasoReplay(
                conversation_id=conv_id,
                outcome=str(cabeca["conversation_outcome"]),
                falas=falas,
                gabarito=Gabarito(
                    idade=(
                        None
                        if cabeca["lead_idade_informada"] is None
                        else int(cabeca["lead_idade_informada"])
                    ),
                    # O ano já foi extraído pelo veredito. Copiar em vez de extrair de
                    # novo mantém uma única definição de "o ano do veículo é o último
                    # número de `veiculo_texto`".
                    veiculo_ano=veredito.ano_veiculo,
                    cep=extrair_cep(falas),
                ),
                elegibilidade=veredito,
                veiculo_texto=cabeca["veiculo_texto"],
                _midias=sum(1 for f in falas if f.e_midia_sem_transcricao),
            )
        )
    return casos


def carregar(*, ano_corrente: int | None = None) -> list[CasoReplay]:
    """Os casos do parquet do desafio. Levanta `BronzeIndisponivel` se ele não está lá."""
    from qa.dataset import bronze

    return montar(bronze.ler(), ano_corrente=ano_corrente)
