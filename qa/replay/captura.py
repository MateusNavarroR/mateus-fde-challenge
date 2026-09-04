"""A costura que devolve o `RunOutput` de cada turno ao replay.

**O problema.** `ReliabilityEval` assere sobre `agent_response.messages[].tool_calls` —
ele precisa do `RunOutput`. Mas `app.agent.turno.responder` roda o agente por dentro e
não devolve nada: ele persiste, entrega pelo canal, aplica a regra de descarte e volta
`None`. Rodar o agente por fora, montando o `ContextoDoTurno` no replay, resolveria o
acesso e **duplicaria** a regra de descarte, a avaliação dos sete gatilhos e a gravação
de `turn_usage` — três comportamentos que o replay existe para verificar, não para
reimplementar. Um replay que reimplementa o que mede não mede mais nada.

**A costura.** Trocar `app.agent.turno.construir_agente` por um embrulho que devolve o
mesmo agente com `run` instrumentado. O caminho de produção continua sendo o exercitado,
byte a byte; o que muda é que o `RunOutput` fica visível — e que a exceção do provedor
fica visível também, o que importa porque `responder` captura `Exception` de forma ampla
e um 402 chegaria ao relatório como "conversa normal que respondeu estranho".

**A alternativa que não foi escolhida**, e por quê: fazer `responder` devolver o
`RunOutput`. É mais limpo e é uma mudança em `app/` — fora do escopo desta frente. Se
esta costura se mostrar frágil, é essa a correção, e ela cabe em uma linha.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator

from qa.replay.falhas import Falha, de_excecao


@dataclass
class Coletor:
    """O que aconteceu em cada turno, na ordem.

    `runs` e `falhas` são listas paralelas ao número de chamadas, não ao número de
    turnos: um turno que retenta duas vezes aparece duas vezes. É o que permite ao
    relatório distinguir "10 turnos" de "10 turnos e 4 retentativas".
    """

    runs: list[Any] = field(default_factory=list)
    falhas: list[Falha] = field(default_factory=list)
    conversation_id: str | None = None
    message_index: int | None = None

    @property
    def ultimo_run(self) -> Any | None:
        return self.runs[-1] if self.runs else None

    def chamadas_de_tool(self, desde: int = 0) -> list[str]:
        """Os nomes das tools chamadas, na ordem, a partir do `desde`-ésimo run.

        Achatar aqui — em vez de deixar cada asserção reabrir o `RunOutput` — é o que
        mantém a forma do objeto do Agno em **um** lugar. Quando ela mudar de versão,
        muda aqui.
        """
        nomes: list[str] = []
        for run in self.runs[desde:]:
            for mensagem in getattr(run, "messages", None) or []:
                for chamada in getattr(mensagem, "tool_calls", None) or []:
                    nome = _nome_da_chamada(chamada)
                    if nome:
                        nomes.append(nome)
        return nomes

    def argumentos_de(self, tool: str, desde: int = 0) -> list[dict[str, Any]]:
        """Os argumentos de cada chamada a `tool`, já decodificados.

        O Agno entrega os argumentos como **string JSON** dentro de
        `function.arguments`. Decodificar em cada asserção seria repetir o mesmo
        `json.loads` com o mesmo `try` em cinco lugares.
        """
        import json

        saida: list[dict[str, Any]] = []
        for run in self.runs[desde:]:
            for mensagem in getattr(run, "messages", None) or []:
                for chamada in getattr(mensagem, "tool_calls", None) or []:
                    if _nome_da_chamada(chamada) != tool:
                        continue
                    brutos = _argumentos_da_chamada(chamada)
                    if isinstance(brutos, str):
                        try:
                            brutos = json.loads(brutos)
                        except (ValueError, TypeError):
                            brutos = {}
                    saida.append(brutos if isinstance(brutos, dict) else {})
        return saida


def _nome_da_chamada(chamada: Any) -> str | None:
    if isinstance(chamada, dict):
        return (chamada.get("function") or {}).get("name") or chamada.get("name")
    funcao = getattr(chamada, "function", None)
    return getattr(funcao, "name", None) or getattr(chamada, "name", None)


def _argumentos_da_chamada(chamada: Any) -> Any:
    if isinstance(chamada, dict):
        return (chamada.get("function") or {}).get("arguments") or chamada.get("arguments")
    funcao = getattr(chamada, "function", None)
    return getattr(funcao, "arguments", None) or getattr(chamada, "arguments", None)


class _AgenteEspiao:
    """Delegação total, com `run` instrumentado.

    Existe como plano B: em quase todo caso basta atribuir `agente.run = embrulho`, mas
    uma classe com `__slots__` ou um `run` só de leitura recusaria a atribuição. Falhar
    aí produziria um `AttributeError` a dez frames de distância da causa; este proxy
    troca isso por um caminho que sempre funciona.
    """

    def __init__(self, alvo: Any, embrulho) -> None:
        object.__setattr__(self, "_alvo", alvo)
        object.__setattr__(self, "_embrulho", embrulho)

    def run(self, *args, **kwargs):
        return object.__getattribute__(self, "_embrulho")(*args, **kwargs)

    def __getattr__(self, nome: str):
        return getattr(object.__getattribute__(self, "_alvo"), nome)

    def __setattr__(self, nome: str, valor) -> None:
        setattr(object.__getattribute__(self, "_alvo"), nome, valor)


def instrumentar(agente: Any, coletor: Coletor) -> Any:
    """Devolve o agente com `run` gravando no coletor. Reexporta a exceção."""
    original = agente.run

    def embrulho(*args, **kwargs):
        try:
            saida = original(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — classificada e relançada, nunca engolida
            coletor.falhas.append(
                de_excecao(
                    e,
                    conversation_id=coletor.conversation_id,
                    message_index=coletor.message_index,
                )
            )
            raise
        coletor.runs.append(saida)
        return saida

    try:
        agente.run = embrulho  # type: ignore[method-assign]
        return agente
    except (AttributeError, TypeError):  # pragma: no cover - depende da versão do Agno
        return _AgenteEspiao(agente, embrulho)


@contextmanager
def capturando(coletor: Coletor) -> Iterator[Coletor]:
    """Enquanto o bloco durar, todo agente construído por `turno` grava no coletor.

    Restaura o original no `finally`, inclusive quando o corpo levanta: deixar a costura
    instalada depois de uma falha faria o próximo teste da mesma sessão medir o coletor
    errado, e esse é o tipo de defeito que só aparece na ordem de execução.
    """
    from app.agent import turno as modulo_turno

    original = modulo_turno.construir_agente

    def construir(ctx):
        return instrumentar(original(ctx), coletor)

    modulo_turno.construir_agente = construir  # type: ignore[assignment]
    try:
        yield coletor
    finally:
        modulo_turno.construir_agente = original  # type: ignore[assignment]
