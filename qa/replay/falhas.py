"""Classificação das falhas do provedor, e o backoff do próprio replay.

**Um replay que morre na conversa 18 e não diz que morreu é pior que um replay que não
roda.** O segundo é obviamente inútil; o primeiro produz um relatório com 17 conversas e
a aparência de estar completo.

Duas falhas concretas motivam o módulo:

- **HTTP 402.** O free tier do Ollama Cloud devolve `402 Payment Required` em três dos
  quatro modelos. Não é transitório e não adianta esperar: ou o modelo tem crédito, ou
  não tem. A execução para, **com relatório**.
- **Rate limit (429).** É transitório por definição, e a resposta certa é esperar. O
  replay é uma execução longa e não interativa; abortar por um 429 desperdiça as horas
  já gastas.

**Por que a classificação é por texto e não por tipo de exceção.** O erro atravessa duas
camadas — o SDK do provedor e o wrapper do Agno — e cada provedor embrulha de um jeito.
Casar por tipo exigiria importar exceções de `anthropic`, `ollama` e `openai` e
manter-se em dia com as três. Casar por `status_code` quando ele existe, e por texto
quando não existe, cobre os três com uma função e degrada para `OUTRA` — que é
registrada, não engolida.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from enum import Enum


class ClasseDeFalha(str, Enum):
    #: 402: sem crédito. Não retenta, e para a execução.
    PAGAMENTO = "pagamento_402"
    #: 429 e afins: espera e retenta.
    RATE_LIMIT = "rate_limit"
    #: 5xx, sobrecarga, conexão. Retenta menos vezes.
    INDISPONIVEL = "indisponivel"
    #: Qualquer outra. Não retenta; a conversa é marcada e a execução continua.
    OUTRA = "outra"

    def __str__(self) -> str:
        return self.value


_PADROES: tuple[tuple[ClasseDeFalha, re.Pattern[str]], ...] = (
    (
        ClasseDeFalha.PAGAMENTO,
        re.compile(
            r"\b402\b|payment required|insufficient (?:credit|funds|balance|quota)|"
            r"billing|upgrade your plan",
            re.IGNORECASE,
        ),
    ),
    (
        ClasseDeFalha.RATE_LIMIT,
        re.compile(
            r"\b429\b|rate.?limit|too many requests|quota exceeded|"
            r"requests per (?:minute|second)",
            re.IGNORECASE,
        ),
    ),
    (
        ClasseDeFalha.INDISPONIVEL,
        re.compile(
            r"\b5\d{2}\b|overloaded|service unavailable|bad gateway|timed? ?out|"
            r"timeout|connection (?:error|reset|refused)|temporarily",
            re.IGNORECASE,
        ),
    ),
)

#: Quantas vezes cada classe vale a pena retentar dentro de um mesmo turno.
#: `PAGAMENTO` é zero por definição: 402 não melhora com espera.
TENTATIVAS = {
    ClasseDeFalha.PAGAMENTO: 0,
    ClasseDeFalha.RATE_LIMIT: 4,
    ClasseDeFalha.INDISPONIVEL: 2,
    ClasseDeFalha.OUTRA: 0,
}


def _status_de(exc: BaseException) -> int | None:
    """`status_code` onde os SDKs o colocam, sem importar nenhum deles."""
    for atributo in ("status_code", "status"):
        valor = getattr(exc, atributo, None)
        if isinstance(valor, int):
            return valor
    resposta = getattr(exc, "response", None)
    valor = getattr(resposta, "status_code", None)
    return valor if isinstance(valor, int) else None


def classificar(exc: BaseException) -> ClasseDeFalha:
    """A classe da falha. Olha o status primeiro, o texto depois.

    O texto inclui a cadeia de `__cause__`: o Agno costuma embrulhar a exceção do SDK, e
    a mensagem original — que é onde está o "402" — fica um nível abaixo.
    """
    status = _status_de(exc)
    if status == 402:
        return ClasseDeFalha.PAGAMENTO
    if status == 429:
        return ClasseDeFalha.RATE_LIMIT
    if status is not None and 500 <= status < 600:
        return ClasseDeFalha.INDISPONIVEL

    partes: list[str] = []
    atual: BaseException | None = exc
    visitados: set[int] = set()
    while atual is not None and id(atual) not in visitados:
        visitados.add(id(atual))
        partes.append(f"{type(atual).__name__}: {atual}")
        atual = atual.__cause__ or atual.__context__

    texto = " | ".join(partes)
    for classe, padrao in _PADROES:
        if padrao.search(texto):
            return classe
    return ClasseDeFalha.OUTRA


@dataclass(frozen=True)
class Falha:
    """O que o relatório grava. Sem traceback e sem corpo de resposta.

    A mensagem é truncada e passa pelo mascaramento antes de sair (`relatorio.py`): um
    corpo de erro do provedor pode ecoar o prompt, e o prompt carrega a fala do lead.
    """

    classe: ClasseDeFalha
    mensagem: str
    conversation_id: str | None = None
    message_index: int | None = None

    @property
    def fatal(self) -> bool:
        """Continuar depois desta falha produziria só mais falhas iguais."""
        return self.classe is ClasseDeFalha.PAGAMENTO


def de_excecao(
    exc: BaseException,
    *,
    conversation_id: str | None = None,
    message_index: int | None = None,
    limite: int = 300,
) -> Falha:
    texto = f"{type(exc).__name__}: {exc}"
    return Falha(
        classe=classificar(exc),
        mensagem=texto[:limite],
        conversation_id=conversation_id,
        message_index=message_index,
    )


def de_run_com_erro(
    run: object,
    *,
    conversation_id: str | None = None,
    message_index: int | None = None,
    limite: int = 300,
) -> Falha | None:
    """A falha que **não vem como exceção**, e por isso passava batida.

    O Agno não levanta quando a chamada ao provider falha: devolve um `RunOutput` com
    `status=ERROR` e o texto do erro em `content`. O `instrumentar` só classificava
    exceção, então esse run entrava na lista como resposta normal do agente — com
    `content` sendo a mensagem de erro do provedor.

    O estrago medido: a conta ficou sem crédito no meio de uma execução e **18 das 30
    conversas viraram "o agente não perguntou nada e não chamou tool nenhuma"**. O
    relatório publicou 36,7% de acerto. Não era o agente: era uma fatura.

    A classificação reusa `classificar`, então `credit balance` cai em `PAGAMENTO`,
    que é `fatal` — a execução aborta na primeira em vez de gastar vinte minutos
    produzindo linhas que não medem nada.
    """
    if not str(getattr(run, "status", "") or "").upper().endswith("ERROR"):
        return None
    texto = str(getattr(run, "content", "") or "")[:limite]
    return Falha(
        classe=classificar(RuntimeError(texto)),
        mensagem=f"RunStatus.ERROR: {texto}",
        conversation_id=conversation_id,
        message_index=message_index,
    )


@dataclass
class Backoff:
    """Exponencial com jitter, semeado.

    Semeado porque o relatório informa quanto tempo o replay passou esperando, e um
    jitter não reprodutível tornaria dois relatórios incomparáveis por um motivo que não
    tem nada a ver com o agente. O `dormir` é injetável para que a suíte não durma de
    verdade — uma suíte que espera 30 s ninguém roda.
    """

    base_s: float = 2.0
    teto_s: float = 60.0
    seed: int = 20260904
    dormir: object = time.sleep

    _rng: random.Random = None  # type: ignore[assignment]
    esperado_s: float = 0.0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)

    def espera(self, tentativa: int) -> float:
        """Segundos para a `tentativa`-ésima retentativa, contando de 1."""
        bruto = min(self.teto_s, self.base_s * (2 ** max(0, tentativa - 1)))
        return bruto * (0.5 + self._rng.random() / 2)

    def esperar(self, tentativa: int) -> float:
        segundos = self.espera(tentativa)
        self.esperado_s += segundos
        self.dormir(segundos)  # type: ignore[operator]
        return segundos
