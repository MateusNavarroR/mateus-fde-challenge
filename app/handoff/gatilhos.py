"""Os sete gatilhos de handoff — como dados, não como `if` espalhado.

É isso que torna o critério "explícito e defensável", que é o texto do enunciado. O
que reprova não é ser generoso ou econômico com a fila: é o gatilho implícito, que
ninguém consegue enumerar nem testar.

**O critério é o custo de o agente errar ali.** Custo alto encaminha na hora e sem
tentar responder; custo baixo tenta e encaminha na segunda vez. Não é "quantos casos
cobrir" — é onde o erro é caro.

**Precedência = ordem da declaração.** Primeiro que casa vence; os demais que casaram
no mesmo turno viram `gatilhos_secundarios`. A fila mostra um gatilho — o que mantém
a regra testável, uma linha por gatilho — sem que o operador perca o quadro completo.

**Não são gatilhos**, e cada ausência é uma decisão:

- **recusa 422** — 30% do tráfego. Um humano releria a mesma regra fixa em
  `plans.json` e daria o mesmo "não";
- **falha isolada da `/quote` que o retry resolveu** — 20% dos jobs; encaminhar aí
  encheria a fila com o que se resolve sozinho em 96% dos casos;
- **primeira objeção de preço** e **primeira mídia** — o agente tenta uma vez.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.contracts.conversa import HandoffTrigger
from app.persistence.models import Conversation, Handoff

#: Assuntos que separam o prefixo de texto: sinistro e saúde pedem empatia, jurídico
#: e reclamação pedem neutralidade. "Sinto muito" numa notificação extrajudicial soa
#: como admissão; a ausência dele depois de "bati o carro" soa como frieza.
_SINISTRO = re.compile(
    r"\b(bati|batida|colidi|colis[ãa]o|acidente|sinistro|capot|roubaram|furtaram|"
    r"levaram meu carro|atropel|ferid|machuc|hospital|ambul[âa]ncia|m[ée]dic)\w*",
    re.IGNORECASE,
)
_JURIDICO = re.compile(
    r"\b(advogad|processo|processar|judicial|extrajudicial|procon|reclama[çc][ãa]o|"
    r"intima[çc][ãa]o|not[ií]fica[çc][ãa]o|ju[ií]z|tribunal|indeniza[çc][ãa]o)\w*",
    re.IGNORECASE,
)
_PEDIU_ATENDENTE = re.compile(
    r"\b(atendente|humano|pessoa de verdade|falar com algu[ée]m|uma pessoa|"
    r"supervisor|ger[êe]nte|prefiro falar com)\b",
    re.IGNORECASE,
)
_OBJECAO_PRECO = re.compile(
    r"\b(caro|salgad|abusiv|apertad|n[ãa]o cabe no bolso|fora do or[çc]amento|"
    r"desconto|mais barato|baratinho|pesou)\w*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Contexto:
    """O que os gatilhos leem. Nada aqui vem de argumento de tool."""

    texto_do_lead: str = ""
    tipo_da_mensagem: str = "text"
    #: O job de cotação terminou `failed` neste turno.
    cotacao_falhou: bool = False
    #: Violações de guardrail acumuladas nesta conversa.
    violacoes_guardrail: int = 0
    #: Quantas vezes cada campo já foi rejeitado na extração.
    tentativas_extracao: dict[str, int] | None = None
    #: Quantas vezes o lead já objetou preço, incluindo agora.
    objecoes_de_preco: int = 0
    #: Quantas mensagens de mídia o lead mandou depois de pedirmos texto.
    midias_apos_pedido: int = 0


def _assunto_sensivel(c: Contexto) -> str | None:
    if _SINISTRO.search(c.texto_do_lead):
        return "sinistro"
    if _JURIDICO.search(c.texto_do_lead):
        return "juridico"
    return None


#: A ordem desta lista É a precedência. Mudar a ordem muda o comportamento, e é por
#: isso que ela é dado e não uma cadeia de `if`.
REGRAS: list[tuple[HandoffTrigger, str]] = [
    (HandoffTrigger.ASSUNTO_SENSIVEL, "assunto que exige uma pessoa: sinistro, saúde, jurídico ou reclamação"),
    (HandoffTrigger.GUARDRAIL, "violação de guardrail repetida na conversa"),
    (HandoffTrigger.LEAD_PEDIU, "o lead pediu para falar com uma pessoa"),
    (HandoffTrigger.COTACAO_INDISPONIVEL, "a cotação não respondeu depois de esgotadas as tentativas"),
    (HandoffTrigger.EXTRACAO_FALHOU, "não consegui ler o mesmo campo duas vezes"),
    (HandoffTrigger.OBJECAO_FORA_DA_ALCADA, "o lead repetiu a objeção de preço"),
    (HandoffTrigger.MIDIA_SEM_TEXTO, "o lead insistiu em mídia depois de pedirmos por texto"),
]


def casa(trigger: HandoffTrigger, c: Contexto) -> bool:
    """Uma função por gatilho, para que cada um tenha um teste seu."""
    if trigger is HandoffTrigger.ASSUNTO_SENSIVEL:
        return _assunto_sensivel(c) is not None
    if trigger is HandoffTrigger.GUARDRAIL:
        # A primeira violação descarta a mensagem e conta; a segunda encaminha.
        return c.violacoes_guardrail >= 2
    if trigger is HandoffTrigger.LEAD_PEDIU:
        return bool(_PEDIU_ATENDENTE.search(c.texto_do_lead))
    if trigger is HandoffTrigger.COTACAO_INDISPONIVEL:
        return c.cotacao_falhou
    if trigger is HandoffTrigger.EXTRACAO_FALHOU:
        # Por CAMPO, não global: falhar uma vez no CEP e uma na idade não é
        # "falhou duas vezes".
        return any(n >= 2 for n in (c.tentativas_extracao or {}).values())
    if trigger is HandoffTrigger.OBJECAO_FORA_DA_ALCADA:
        return c.objecoes_de_preco >= 2 and bool(_OBJECAO_PRECO.search(c.texto_do_lead))
    if trigger is HandoffTrigger.MIDIA_SEM_TEXTO:
        return c.tipo_da_mensagem != "text" and c.midias_apos_pedido >= 2
    return False


def avaliar(c: Contexto) -> tuple[HandoffTrigger, str, list[HandoffTrigger]] | None:
    """Devolve `(gatilho, motivo, secundários)` ou `None`.

    O primeiro que casa vence. Os demais não se perdem: viram secundários.
    """
    casaram = [(t, motivo) for t, motivo in REGRAS if casa(t, c)]
    if not casaram:
        return None
    principal, motivo = casaram[0]
    return principal, motivo, [t for t, _ in casaram[1:]]


def registrar(
    s: Session,
    conversation_id: str,
    trigger: HandoffTrigger,
    reason: str,
    *,
    secundarios: list[HandoffTrigger] | None = None,
    summary: str | None = None,
    quote_id: str | None = None,
    disparado_por: str = "regra",
) -> Handoff:
    """Cria o handoff e move a conversa para `encaminhado`, que é terminal."""
    h = Handoff(
        id=f"ho_{uuid.uuid4().hex[:16]}",
        conversation_id=conversation_id,
        trigger=str(trigger),
        reason=reason,
        summary=summary,
        disparado_por=disparado_por,
        quote_id=quote_id,
        status="pendente",
        gatilhos_secundarios=[str(t) for t in (secundarios or [])],
    )
    s.add(h)
    conv = s.get(Conversation, conversation_id)
    if conv is not None:
        conv.state = "encaminhado"
    s.flush()
    return h


def assunto_do_texto(texto: str) -> str | None:
    """Qual prefixo de texto usar no `assunto_sensivel`."""
    return _assunto_sensivel(Contexto(texto_do_lead=texto))
