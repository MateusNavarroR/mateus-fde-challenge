"""O script que cobre os dois buracos — e o contador que torna a fragilidade visível.

O lead do dataset **nunca informa `data_inicio` nem `plano_id`**, e são justamente os
dois que a nossa qualificação exige (`app.contracts.conversa.CAMPOS_QUALIFICACAO`). Sem
alguém para respondê-los, toda conversa do replay morre em `qualificando` e o caminho
até `cotado` nunca é exercitado.

**Script cobrindo dois buracos conhecidos, não a conversa inteira.** Roteirizar tudo
trocaria a linguagem bagunçada de verdade — que é o que o dataset oferece e que nenhum
roteiro nosso imitaria bem — por uma imitação limpa. Menos superfície frágil e mais
fidelidade: só os dois campos que o corpus não tem.

**O contador de "não entendi a pergunta".** O respondedor casa a fala do agente por
intenção. Quando o agente pergunta algo que ele não sabe classificar, o contador sobe e
o relatório reprova a suíte acima de um limiar. É o mesmo princípio do teste negativo do
cache: um casador de intenção que erra em silêncio produz uma suíte que passa medindo
nada, e a diferença entre "o agente não perguntou" e "eu não entendi que ele perguntou"
é a diferença entre uma métrica e um número.

**Cinco intenções reconhecidas, duas respondidas.** Idade, ano do veículo e CEP são
reconhecidos e **não** respondidos: quem os responde são as falas do dataset. Reconhecê-
los sem responder é o que impede o contador de subir por perguntas que o corpus já cobre
— senão ele mediria o dataset, não o script.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

#: Os três planos do catálogo. Vêm de `plans.json` via `precos.carregar_tabela`, não
#: escritos aqui — o mesmo motivo de sempre: uma segunda lista divergiria.
from qa.replay.precos import carregar_tabela


class Intencao(str, Enum):
    """O que o agente está pedindo neste turno."""

    DATA_INICIO = "data_inicio"
    PLANO_ID = "plano_id"
    #: Reconhecidas, respondidas pelas falas do dataset.
    IDADE = "idade"
    VEICULO_ANO = "veiculo_ano"
    CEP = "cep"
    #: O agente falou, mas não perguntou nada. Não conta contra ninguém.
    NENHUMA = "nenhuma"
    #: Perguntou algo que o script não sabe classificar. **Esta é a que conta.**
    DESCONHECIDA = "desconhecida"

    def __str__(self) -> str:
        return self.value


#: Só os dois primeiros produzem resposta. A ordem é a precedência: uma pergunta que
#: mencione plano e data ao mesmo tempo é respondida como plano, e a data volta a ser
#: perguntada no turno seguinte — que é o comportamento honesto, porque um lead real
#: também responderia uma coisa de cada vez.
_PADROES: tuple[tuple[Intencao, re.Pattern[str]], ...] = (
    (
        Intencao.PLANO_ID,
        re.compile(
            r"\b(plano|essencial|completo|premium|cobertura|franquia|"
            r"qual dos tr[êe]s|op[çc][ãa]o)\w*",
            re.IGNORECASE,
        ),
    ),
    (
        Intencao.DATA_INICIO,
        re.compile(
            r"\b(quando|a partir de quando|data de in[íi]cio|in[íi]cio da vig[êe]ncia|"
            r"vig[êe]ncia|come[çc]ar a valer|entrar em vigor|come[çc]a)\w*",
            re.IGNORECASE,
        ),
    ),
    (
        Intencao.IDADE,
        re.compile(r"\b(idade|quantos anos|anos voc[êe]|nasceu|nascimento)\w*", re.IGNORECASE),
    ),
    (
        Intencao.VEICULO_ANO,
        re.compile(
            r"\b(ano do (?:carro|ve[íi]culo)|ano de fabrica[çc][ãa]o|"
            r"que ano [ée] o|modelo é de que ano)\w*",
            re.IGNORECASE,
        ),
    ),
    (
        Intencao.CEP,
        re.compile(r"\b(cep|onde o carro dorme|onde (?:ele|o carro) fica|garagem)\w*", re.IGNORECASE),
    ),
)

#: Uma pergunta é uma frase com `?`, ou uma ordem explícita ("me diga", "informe").
#: Sem esta guarda, o bloco de cotação — que cita plano, franquia e carência — casaria
#: `PLANO_ID` e o respondedor responderia a uma pergunta que ninguém fez.
_E_PERGUNTA = re.compile(
    r"\?|\b(me (?:diga|informe|passa|fala)|informe|qual|quando|preciso saber|"
    r"pode (?:me )?(?:dizer|informar|confirmar))\b",
    re.IGNORECASE,
)


def classificar(texto: str | None) -> Intencao:
    """A intenção da fala do agente. Determinístico, sem modelo.

    Um casador por regex é frágil por construção, e é por isso que ele vem com contador:
    a alternativa — perguntar a um modelo o que o outro modelo quis dizer — trocaria
    fragilidade visível por fragilidade cara e igualmente invisível.
    """
    if not texto or not texto.strip():
        return Intencao.NENHUMA
    if not _E_PERGUNTA.search(texto):
        return Intencao.NENHUMA
    for intencao, padrao in _PADROES:
        if padrao.search(texto):
            return intencao
    return Intencao.DESCONHECIDA


@dataclass
class RespondedorRoteirizado:
    """Um por conversa. Guarda o contador e o que já foi respondido.

    O estado por conversa (e não global) é o que permite ao relatório dizer em **quais**
    conversas o script não deu conta, que é a informação acionável — um contador global
    diria "23" e não diria onde.
    """

    conversation_id: str
    #: Semeado pelo `conversation_id`: a mesma conversa recebe sempre o mesmo plano e a
    #: mesma data, e conversas diferentes recebem planos diferentes. Fixar um único
    #: plano exercitaria um terço da tabela de preço.
    seed: int = 0

    nao_entendi: int = 0
    #: `Intencao -> quantas vezes o agente pediu`. Repetição é sinal: o agente pediu
    #: `plano_id` cinco vezes significa que a nossa resposta não está sendo lida.
    pedidos: dict[str, int] = field(default_factory=dict)
    #: As falas que o agente emitiu e o script não classificou, para o relatório citar
    #: (mascaradas na serialização).
    nao_entendidas: list[str] = field(default_factory=list)
    respondeu: dict[str, str] = field(default_factory=dict)

    @property
    def plano_escolhido(self) -> str:
        planos = sorted(carregar_tabela().bases)
        chave = self.seed or _semente(self.conversation_id)
        return planos[chave % len(planos)]

    @property
    def data_escolhida(self) -> str:
        """"dia 15 do mês que vem" — texto livre, não ISO.

        Duas razões para não mandar `2026-10-15`: o campo vem de conversa e é o mais
        arriscado dos cinco (a `/quote` devolve 400 para data mal formatada, e 400 nunca
        retenta), então mandar ISO testaria o caminho fácil; e **dia ≠ 1** é o que faz o
        `primeiro_pagamento_pro_rata` existir na resposta (API-COTACAO §6.2) — com dia 1
        o bloco some e o replay deixaria de exercitar o pro-rata inteiro.
        """
        chave = self.seed or _semente(self.conversation_id)
        return f"dia {5 + (chave % 20)} do mês que vem"

    def responder(self, fala_do_agente: str | None) -> str | None:
        """A resposta do lead roteirizado, ou `None` quando não há o que responder.

        `None` significa três coisas diferentes, e todas as três estão certas aqui: o
        agente não perguntou nada; perguntou algo que as falas do dataset respondem; ou
        perguntou algo que o script não entendeu — e nesse caso o contador subiu.
        """
        intencao = classificar(fala_do_agente)
        self.pedidos[str(intencao)] = self.pedidos.get(str(intencao), 0) + 1

        if intencao is Intencao.DESCONHECIDA:
            self.nao_entendi += 1
            self.nao_entendidas.append(fala_do_agente or "")
            return None

        if intencao is Intencao.PLANO_ID:
            resposta = f"acho que o {self.plano_escolhido} tá bom pra mim"
        elif intencao is Intencao.DATA_INICIO:
            resposta = f"pode ser {self.data_escolhida}"
        else:
            return None

        self.respondeu[str(intencao)] = resposta
        return resposta

    @property
    def perguntas(self) -> int:
        """Quantas perguntas o agente fez — o denominador da taxa de incompreensão."""
        return sum(n for k, n in self.pedidos.items() if k != str(Intencao.NENHUMA))


def _semente(conversation_id: str) -> int:
    """Hash estável entre processos.

    `hash()` de `str` é aleatorizado por `PYTHONHASHSEED` a cada processo — usá-lo faria
    a mesma conversa receber planos diferentes em execuções diferentes, e a comparação
    entre duas execuções do replay deixaria de valer.
    """
    from hashlib import blake2b

    return int.from_bytes(blake2b(conversation_id.encode(), digest_size=4).digest(), "big")
