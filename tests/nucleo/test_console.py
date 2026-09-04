"""O adaptador de console e o transcript.

O transcript é o entregável nº 4. O que ele precisa provar não é que o agente falou —
é **quando** falou, porque é o tempo que demonstra a política de espera funcionando.
"""

import io

import pytest

from app.channels.console import ConsoleAdapter
from app.contracts.channel import ChannelAdapter


class RelogioFalso:
    """Sem isto a suíte dormiria 37 s no cenário degradado — e suíte que ninguém roda
    não protege nada."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, s: float) -> None:
        self.t += s


@pytest.fixture
def relogio():
    return RelogioFalso()


@pytest.fixture
def adaptador(relogio):
    a = ConsoleAdapter(transcript=True, relogio=relogio)
    a.saida = io.StringIO()
    a.marcar_inicio()
    return a


def test_satisfaz_a_porta():
    assert isinstance(ConsoleAdapter(), ChannelAdapter)


async def test_typing_e_no_op_e_nao_escreve_nada(adaptador):
    """`[digitando...]` num log documentaria a coisa errada."""
    await adaptador.typing("c1", ativo=True)
    await adaptador.typing("c1", ativo=False)
    assert adaptador.saida.getvalue() == ""
    assert adaptador.linhas == []


async def test_send_devolve_external_id(adaptador):
    ext = await adaptador.send("c1", "oi", message_id="msg_1")
    assert ext == "console:msg_1"


async def test_transcript_marca_tempo_relativo(adaptador, relogio):
    relogio.avancar(6.2)
    await adaptador.send("c1", "aviso", message_id="m1", autor="sistema")
    assert "[+6.2s]" in adaptador.linhas[-1].render()


async def test_a_sequencia_degradada_fica_legivel(adaptador, relogio):
    """A sequência que o avaliador vai olhar: aviso, reforço, encaminhamento —
    e os tempos que provam que houve tentativa de verdade."""
    await adaptador.send("c1", "pode cotar então", message_id="m0", autor="lead")
    relogio.avancar(6.0)
    await adaptador.send("c1", "tô buscando o valor", message_id="m1", autor="sistema")
    relogio.avancar(14.4)
    await adaptador.send("c1", "ainda tô aqui, viu?", message_id="m2", autor="sistema")
    relogio.avancar(17.1)
    await adaptador.send("c1", "não consegui confirmar", message_id="m3", autor="sistema")

    texto = adaptador.transcript_texto()
    assert "[+0.0s]" in texto
    assert "[+6.0s]" in texto
    assert "[+20.4s]" in texto
    assert "[+37.5s]" in texto
    # e nenhuma decoração
    assert "digitando" not in texto


async def test_sem_transcript_imprime_forma_simples(relogio):
    a = ConsoleAdapter(transcript=False, relogio=relogio)
    a.saida = io.StringIO()
    await a.send("c1", "oi", message_id="m1")
    assert a.saida.getvalue().strip() == "agente: oi"


async def test_quote_id_acompanha_a_mensagem(adaptador):
    """O guardrail auditável: mensagem com valor monetário carrega o vínculo."""
    await adaptador.send("c1", "R$ 392,25/mês", message_id="m1",
                         quote_id="q_1", autor="sistema")
    assert adaptador.enviadas[-1]["quote_id"] == "q_1"


async def test_relogio_nao_precisa_de_marcacao_explicita(relogio):
    """Se ninguém chamou `marcar_inicio`, a primeira mensagem zera o relógio em vez
    de explodir."""
    a = ConsoleAdapter(transcript=True, relogio=relogio)
    a.saida = io.StringIO()
    await a.send("c1", "primeira", message_id="m1")
    assert a.linhas[0].segundos == pytest.approx(0.0)
