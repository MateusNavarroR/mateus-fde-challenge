"""Um turno por vez, e o relógio de demora do modelo."""

import asyncio
import uuid

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


@pytest.mark.db
def test_duas_aberturas_SIMULTANEAS_devolvem_a_MESMA_conversa(engine_teste, monkeypatch):
    """A corrida que o `SELECT` sozinho não fecha, e que virava HTTP 500 para o lead.

    Entre ler e inserir há uma janela. Duas requisições com o mesmo `external_ref`
    passam pelas duas: ambas não encontram nada, ambas inserem, e a segunda bate na
    `UNIQUE (channel, external_ref)`. Não é hipotético — o React em desenvolvimento
    monta cada componente duas vezes, e foi assim que o defeito apareceu no `vite dev`;
    em produção basta um duplo clique, duas abas ou um F5 durante a abertura.

    **O teste força a janela em vez de torcer por ela.** Chamar a função duas vezes em
    sequência não reproduz nada: a segunda chamada encontra a linha já commitada e sai
    pelo caminho feliz — foi a primeira versão deste teste, e ela passava com o bug
    presente. Aqui um "outro processo" vence a corrida DENTRO da janela, entre o
    `SELECT` e o `INSERT`, que é exatamente onde ela existe.
    """
    from sqlalchemy.orm import Session

    from app.persistence import repo

    ref = f"corrida-{uuid.uuid4().hex}"
    original = repo.criar_conversa

    def intruso(sessao, *, channel, external_ref):
        # O concorrente insere e commita agora — a partir daqui o INSERT abaixo
        # colide, que é o estado que o código precisa saber tratar.
        monkeypatch.setattr(repo, "criar_conversa", original)
        with Session(engine_teste) as outra:
            original(outra, channel=channel, external_ref=external_ref)
            outra.commit()
        return original(sessao, channel=channel, external_ref=external_ref)

    monkeypatch.setattr(repo, "criar_conversa", intruso)

    with Session(engine_teste) as s:
        conversa, criada = repo.criar_ou_retomar_conversa(
            s, channel="web", external_ref=ref
        )
        s.commit()
        id_perdedor = conversa.id

    # Quem perdeu a corrida NÃO recebe erro: recebe a conversa do vencedor.
    assert criada is False, "perder a corrida devolveu `criada=True`"
    with Session(engine_teste) as s:
        do_banco = repo.criar_ou_retomar_conversa(s, channel="web", external_ref=ref)[0]
        assert do_banco.id == id_perdedor, (
            "a conversa devolvida não é a que ficou no banco — o lead acabaria com "
            "duas conversas para a mesma sessão"
        )
