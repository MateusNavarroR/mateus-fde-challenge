"""O que se espera de cada conversa — e a asserção que estava invertida.

A formulação original — *"lead incotável chamou `escalate_to_human` e não chamou
`quote_plan`"* — é incorreta por dois motivos, ambos consequência de decisões fechadas
(`docs/DECISOES-FECHADAS.md` §2 e §9):

1. **Recusa não cria handoff.** Chamar `escalate_to_human` num lead incotável é o
   defeito, não o acerto.
2. **O agente não tem como saber que o lead é incotável.** O catálogo no system prompt
   tem nomes e coberturas e **nenhuma regra** — nem limite de idade, nem de ano do
   veículo. Quem decide elegibilidade é a `/quote`, exatamente como quem decide preço.

| Lead | Deve chamar | Desfecho | Não deve |
|---|---|---|---|
| incotável | **`quote_plan`** — obrigatório, é a API que decide | `refused` com o motivo certo | `escalate_to_human` |
| cotável | `quote_plan` com idade e ano corretos | `ok` | `escalate_to_human` |

**A terceira linha, que a tabela não tem e o corpus exige.** Parte das conversas do
dataset traz, na fala do lead, um gatilho de handoff legítimo — o lead pede um atendente,
ou fala de um sinistro. Nessas, encaminhar é o acerto, e cobrar `quote_plan` mediria o
agente contra o oposto do que a política manda. Quem classifica não é uma regex nova
daqui: é `app.handoff.gatilhos`, o mesmo módulo que decide em produção. Um segundo
classificador divergiria do primeiro, e o replay passaria a reprovar o agente por
concordar com a própria política.

**O que o `ReliabilityEval` cobre e o que ele não cobre.** Ele expressa "deve chamar"
(`expected_tool_calls`) e "com estes argumentos" (`expected_tool_call_arguments`, casamento
parcial). Ele **não** expressa "pode chamar, mas não precisa": desligar
`allow_additional_tool_calls` para pegar `escalate_to_human` reprovaria junto todo turno
que chamou `qualify_lead`, que é legítimo e não obrigatório. Então o "não deve" é
conferido aqui, em três linhas de cálculo — que é onde o `CLAUDE.md` 27 manda o harness
próprio ficar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Sequence

from app.contracts.conversa import HandoffTrigger
from qa.replay.casos import CasoReplay

QUALIFY = "qualify_lead"
QUOTE = "quote_plan"
ESCALATE = "escalate_to_human"


class Desfecho(str, Enum):
    """O estado terminal observável de uma conversa do replay."""

    OK = "ok"
    REFUSED = "refused"
    ENCAMINHADO = "encaminhado"
    #: A conversa acabou sem cotação e sem handoff — o agente ficou perguntando.
    INCOMPLETO = "incompleto"
    #: A execução parou por falha do provedor. Não é veredito sobre o agente.
    FALHOU = "falhou"

    def __str__(self) -> str:
        return self.value


#: Os gatilhos que a **fala do lead** pode acionar sozinha, antes de qualquer cotação.
#: Os outros quatro (guardrail, cotação indisponível, extração falhou, objeção repetida)
#: dependem do que acontece durante o turno e não podem ser previstos do corpus.
GATILHOS_DO_TEXTO = (HandoffTrigger.ASSUNTO_SENSIVEL, HandoffTrigger.LEAD_PEDIU)


def gatilho_no_corpus(caso: CasoReplay) -> HandoffTrigger | None:
    """O primeiro gatilho que as falas do lead acionam, pela precedência de produção.

    Reusa `gatilhos.casa` em vez de reimplementar as regexes: elas são o contrato, e
    duas cópias do contrato são um contrato só até alguém editar uma.
    """
    from app.handoff import gatilhos

    for fala in caso.falas:
        contexto = gatilhos.Contexto(texto_do_lead=fala.texto)
        for trigger in GATILHOS_DO_TEXTO:
            if gatilhos.casa(trigger, contexto):
                return trigger
    return None


@dataclass(frozen=True)
class Expectativa:
    """O contrato de uma conversa, pronto para virar asserção.

    `motivo_recusa` só é exigido quando o desfecho é `refused`: é o que separa "recusou"
    de "recusou pelo motivo certo", e a diferença importa nas **60 conversas recusadas
    pelos dois motivos**, onde a API reporta a idade por precedência do serviço. Um
    replay que só conferisse "recusou" passaria com o motivo errado.
    """

    desfecho: Desfecho
    tools_obrigatorias: tuple[str, ...] = ()
    tools_proibidas: tuple[str, ...] = ()
    motivo_recusa: str | None = None
    argumentos_de_quote: dict[str, Any] = field(default_factory=dict)
    #: A conversa tem mídia sem transcrição ⇒ o agente precisa pedir por texto ou
    #: encaminhar, e nunca inventar o conteúdo.
    exige_pedido_de_texto: bool = False
    gatilho_esperado: HandoffTrigger | None = None


def esperado_para(caso: CasoReplay) -> Expectativa:
    """A expectativa desta conversa. Três linhas de tabela, nesta precedência."""
    gatilho = gatilho_no_corpus(caso)
    if gatilho is not None:
        # Handoff legítimo vindo da fala do lead. Cobrar cotação aqui mediria o agente
        # contra o oposto da política.
        return Expectativa(
            desfecho=Desfecho.ENCAMINHADO,
            tools_proibidas=(),
            gatilho_esperado=gatilho,
            exige_pedido_de_texto=caso.tem_midia_sem_transcricao,
        )

    # O CEP entra na comparação junto com idade e ano do veículo, e **não fica de
    # fora por ser opcional no contrato da API**.
    #
    # É o erro mais caro possível neste domínio: se o agente mandar `cep=None`
    # quando o lead disse um CEP de prefixo de risco, a `/quote` devolve um prêmio
    # **30% menor** e ninguém percebe — a API não tem como saber que o CEP existia.
    # O número sai plausível, verificável contra as regras, e errado.
    argumentos = {
        chave: valor
        for chave, valor in (
            ("idade", caso.gabarito.idade),
            ("veiculo_ano", caso.gabarito.veiculo_ano),
            ("cep", caso.gabarito.cep),
        )
        if valor is not None
    }
    return Expectativa(
        desfecho=Desfecho.REFUSED if not caso.cotavel else Desfecho.OK,
        tools_obrigatorias=(QUOTE,),
        tools_proibidas=(ESCALATE,),
        motivo_recusa=caso.motivo_recusa,
        argumentos_de_quote=argumentos,
        exige_pedido_de_texto=caso.tem_midia_sem_transcricao,
    )


# ─── a ponte com o `ReliabilityEval` do Agno ─────────────────────────────────


@dataclass
class RunAgregado:
    """Um `RunOutput` de mentira que agrega os turnos de uma conversa.

    `ReliabilityEval` avalia **um** `RunOutput`, e a nossa unidade é a conversa: o
    `quote_plan` acontece no turno 9 de 11, e avaliar turno a turno reprovaria os
    outros dez por não terem cotado. Agregar é concatenar os dois atributos que o
    módulo lê:

    - **`tools`** — a lista de `ToolExecution`. Desde a 2.8.0 é daqui que sai a
      evidência: uma expectativa só é satisfeita por uma execução **limpa**, e não mais
      por um pedido no `messages` que a tool recusou ou que estourou. É a leitura certa
      para o nosso caso — "chamou `quote_plan`" tem que significar que a `/quote` foi
      consultada, não que o modelo escreveu o nome da tool;
    - **`messages`** — mantido porque o módulo ainda o usa para anotar a falha de uma
      chamada que nunca virou execução.

    Os três campos de telemetria existem porque `_get_telemetry_data` os lê;
    `telemetry=False` já os dispensaria, e eles ficam para o caso de alguém religar.
    """

    tools: list[Any] = field(default_factory=list)
    messages: list[Any] = field(default_factory=list)
    agent_id: str | None = None
    model: str | None = None
    model_provider: str | None = None


def agregar(runs: Iterable[Any]) -> RunAgregado:
    execucoes: list[Any] = []
    mensagens: list[Any] = []
    for run in runs:
        execucoes.extend(getattr(run, "tools", None) or [])
        mensagens.extend(getattr(run, "messages", None) or [])
    return RunAgregado(tools=execucoes, messages=mensagens)


def montar_reliability(
    caso: CasoReplay,
    expectativa: Expectativa,
    runs: Sequence[Any],
    *,
    db: Any = None,
    print_results: bool = False,
):
    """`ReliabilityEval` para a metade "deve chamar" do contrato.

    `allow_additional_tool_calls=True` é deliberado e está explicado no docstring do
    módulo: sem ele, `qualify_lead` — legítimo e não obrigatório — reprovaria toda
    conversa. A metade "não deve" é `tools_proibidas`, conferida por `conferir_tools`.

    Devolve `None` quando não há tool obrigatória (o caso do handoff legítimo): montar
    um eval sem expectativa produziria um `PASSED` que não significa nada.

    **O CEP fica fora do `expected_tool_call_arguments`, e não por descuido.** O
    casamento de argumentos do Agno é igualdade exata, e o argumento que chega à tool é
    o que o **modelo escreveu** — na forma `01XXX-XXX`, com hífen, como o lead
    falou —, enquanto o gabarito
    é normalizado para 8 dígitos (é assim que `conversations.cep` guarda). Exigir
    igualdade ali reprovaria uma extração correta por causa de um hífen. O CEP continua
    conferido duas vezes, nos dois lugares onde já está normalizado: contra
    `conversations.cep` na medição de extração, e contra `quotes.req_cep` na conferência
    de preço — que é onde a subcotação de 30% de fato aparece.
    """
    if not expectativa.tools_obrigatorias:
        return None
    from agno.eval.reliability import ReliabilityEval

    argumentos = {
        chave: valor
        for chave, valor in expectativa.argumentos_de_quote.items()
        if chave != "cep"
    }
    return ReliabilityEval(
        name=f"replay:{caso.conversation_id}",
        agent_response=agregar(runs),  # type: ignore[arg-type]
        expected_tool_calls=list(expectativa.tools_obrigatorias),
        allow_additional_tool_calls=True,
        expected_tool_call_arguments={QUOTE: argumentos} if argumentos else None,
        db=db,
        telemetry=False,
        print_results=print_results,
    )


def conferir_tools(
    expectativa: Expectativa, chamadas: Sequence[str]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """`(faltando, proibidas_chamadas)`. Cálculo, não julgamento."""
    vistas = set(chamadas)
    return (
        tuple(t for t in expectativa.tools_obrigatorias if t not in vistas),
        tuple(t for t in expectativa.tools_proibidas if t in vistas),
    )


# ─── mídia sem transcrição ───────────────────────────────────────────────────

#: O agente pediu o conteúdo por escrito. Frases nossas, não do modelo — mas o modelo
#: escreve com as próprias palavras neste caso (não há template para isso), então o
#: casamento é por intenção e o padrão é largo de propósito: um falso positivo aqui
#: significa "aceitei uma forma de pedir texto que eu não previa", o que é preferível a
#: reprovar o agente por sinônimo.
_PEDIU_TEXTO = re.compile(
    r"\b(por (?:escrito|texto)|escrev\w+|digit\w+|manda\w* (?:por|em) texto|"
    r"n[ãa]o consigo (?:ouvir|abrir|ver|acessar)|n[ãa]o abro|"
    r"me (?:conta|diz)\w* por aqui)\b",
    re.IGNORECASE,
)


def tratou_midia(mensagens_do_agente: Iterable[str], encaminhou: bool) -> bool:
    """A política de mídia foi cumprida: pediu por texto **ou** encaminhou.

    A terceira saída — inventar o conteúdo do áudio — não tem como ser detectada aqui e
    também não precisa: ela aparece como cotação com dados que o lead nunca disse, e a
    conferência de preço e a de extração já reprovam isso.

    ⚠️ **Achado, e não é desta frente corrigir.** O gatilho `midia_sem_texto` existe em
    `app.handoff.gatilhos` mas é inalcançável pelo caminho de produção:
    `app.agent.turno._encaminhar` monta o `Contexto` sem `tipo_da_mensagem` nem
    `midias_apos_pedido`, que são justamente os dois campos que `casa()` lê para esse
    gatilho. Ou seja: hoje a política de mídia depende inteiramente do modelo pedir
    texto. Por isso a asserção aqui é a disjunção, e não `encaminhou`.
    """
    if encaminhou:
        return True
    return any(_PEDIU_TEXTO.search(m or "") for m in mensagens_do_agente)


# ─── tom e clareza da recusa: o único lugar de juiz de modelo ────────────────

CRITERIO_RECUSA = (
    "A mensagem explica ao lead, com clareza e sem jargão, que a cotação não pode ser "
    "feita, e diz o motivo real. Ela NÃO promete exceção, análise, retorno de um "
    "atendente ou revisão do caso. Ela NÃO sugere trocar o condutor principal por outra "
    "pessoa. Ela não usa tom de culpa nem de deboche. Se o motivo for a idade do "
    "veículo, oferecer cotar outro veículo da casa é correto e desejável."
)


def montar_juiz_da_recusa(*, model: Any = None, db: Any = None, threshold: int = 8):
    """`AgentAsJudgeEval` para tom e clareza — **nunca** para preço nem elegibilidade.

    Preço é cálculo e tem gabarito fechado (`precos.py`); elegibilidade tem gabarito em
    `plans.json`. Perguntar qualquer um dos dois a um juiz de modelo trocaria uma conta
    exata por uma opinião cara. O que sobra para o juiz é o que não tem conta: se o
    texto da recusa soa como uma porta fechada com respeito ou como uma promessa vaga.

    O texto da recusa vem de um mapa fixo (`app.textos.POR_MOTIVO`), então este juiz
    avalia **a nossa redação**, não a do modelo — e é por isso que ele roda uma vez por
    motivo, não uma vez por conversa. Ver `docs/EVALS.md` para a ressalva de qual modelo
    produziu qual número.
    """
    from agno.eval.agent_as_judge import AgentAsJudgeEval

    return AgentAsJudgeEval(
        name="replay:tom-da-recusa",
        criteria=CRITERIO_RECUSA,
        scoring_strategy="numeric",
        threshold=threshold,
        model=model,
        db=db,
        telemetry=False,
    )
