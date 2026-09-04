"""Um turno por vez, e o relógio de demora do modelo."""

import asyncio

import pytest

from app import textos
from app.conversa import Conversa


class AgenteLento:
    def __init__(self, duracao: float = 0.0, resposta: str = "ok") -> None:
        self.duracao, self.resposta = duracao, resposta
        self.comecou = asyncio.Event()
        self.chamadas: list[str] = []

    async def __call__(self, texto: str) -> str:
        self.chamadas.append(texto)
        self.comecou.set()
        await asyncio.sleep(self.duracao)
        return f"{self.resposta} {len(self.chamadas)}"


@pytest.fixture
def saidas():
    return []


def _conversa(agente, saidas):
    async def entregar(texto, autor):
        saidas.append((autor, texto))

    return Conversa(conversation_id="c1", agente=agente, entregar=entregar)


async def test_segunda_mensagem_espera_a_primeira(saidas):
    agente = AgenteLento(duracao=0.05)
    c = _conversa(agente, saidas)
    await asyncio.gather(c.receber("primeira"), c.receber("segunda"))
    # A asserção que importa: sem ela o teste passaria mesmo com dois turnos
    # concorrentes que por acaso não se atrapalharam.
    assert c.turnos_simultaneos_maximo == 1
    assert agente.chamadas == ["primeira", "segunda"]
    assert [t for _, t in saidas] == ["ok 1", "ok 2"]


async def test_ordem_das_saidas_segue_a_ordem_das_entradas(saidas):
    c = _conversa(AgenteLento(duracao=0.02), saidas)
    await asyncio.gather(*(c.receber(f"m{i}") for i in range(5)))
    assert [t for _, t in saidas] == [f"ok {i}" for i in range(1, 6)]


async def test_aviso_de_demora_do_modelo(saidas, monkeypatch):
    """①b: fora do caminho da cotação, 10 s. Aqui encurtado para a suíte não dormir."""
    import app.config as cfg

    monkeypatch.setattr(cfg.get_settings(), "aviso_sem_cotacao_s", 0.05)
    c = _conversa(AgenteLento(duracao=0.20), saidas)
    await c.receber("oi")
    assert ("sistema", textos.AVISO_SEM_COTACAO) in saidas
    # e o aviso vem ANTES da resposta
    assert saidas[0][0] == "sistema"


async def test_modelo_rapido_nao_dispara_aviso(saidas, monkeypatch):
    """O teste que justifica o limiar de 10 s existir. Sem ele, alguém 'uniformiza'
    para 6 s e o agente passa a se desculpar por nada."""
    import app.config as cfg

    monkeypatch.setattr(cfg.get_settings(), "aviso_sem_cotacao_s", 0.20)
    c = _conversa(AgenteLento(duracao=0.02), saidas)
    await c.receber("oi")
    assert all(t != textos.AVISO_SEM_COTACAO for _, t in saidas)


async def test_relogio_desligado_apos_encaminhado(saidas, monkeypatch):
    """Senão o lead que escreve depois do handoff recebe 'só um instante' a cada
    10 s, para sempre."""
    import app.config as cfg

    monkeypatch.setattr(cfg.get_settings(), "aviso_sem_cotacao_s", 0.05)
    c = _conversa(AgenteLento(duracao=0.20), saidas)
    c.encaminhar()
    await c.receber("oi? tem alguém?")
    assert all(t != textos.AVISO_SEM_COTACAO for _, t in saidas)


async def test_turno_sem_fala_nao_entrega_nada(saidas):
    """Depois de uma cotação o bloco já foi enviado pela tool, e o texto do modelo
    é descartado — o turno não produz fala."""

    async def mudo(_texto):
        return None

    c = _conversa(mudo, saidas)
    await c.receber("oi")
    assert saidas == []
