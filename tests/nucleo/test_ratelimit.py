"""O limite de taxa da superfície pública.

Três rotas não exigem autenticação, por desenho: `GET /api/health`,
`POST /api/conversations` e o WebSocket do chat. As duas últimas custam dinheiro — cada
mensagem do chat é uma inferência — e sem limite alguém com acesso à porta esgota a
chave da Anthropic sem precisar de nenhum bug.

O relógio é injetado em todos os testes: uma suíte que espera 60 s para provar
reposição é uma suíte que ninguém roda, e uma que ninguém roda não protege nada.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import ratelimit


class Relogio:
    """Relógio manual. `avancar` é a única forma de o tempo passar."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def avancar(self, s: float) -> None:
        self.t += s


# ─── o balde ─────────────────────────────────────────────────────────────────


def test_a_rajada_permitida_e_exatamente_a_capacidade():
    r = Relogio()
    b = ratelimit.por_minuto(10, relogio=r)

    assert all(b.permite("a") for _ in range(10))
    assert not b.permite("a"), "a 11ª no mesmo instante tem de ser recusada"


def test_repoe_continuamente_e_nao_por_janela():
    """Janela fixa deixa passar o DOBRO do limite na virada: 10 no último segundo de
    um minuto e 10 no primeiro do seguinte. O balde repõe continuamente, então a
    rajada é a capacidade, sempre — inclusive em cima da virada."""
    r = Relogio()
    b = ratelimit.por_minuto(10, relogio=r)

    for _ in range(10):
        b.permite("a")
    assert not b.permite("a")

    r.avancar(6.0)  # 10/min ⇒ 1 token a cada 6 s
    assert b.permite("a")
    assert not b.permite("a"), "repôs um token, não a janela inteira"


def test_o_limite_e_POR_ORIGEM():
    """Um contador global transformaria um visitante ruidoso em negação de serviço
    para todos os outros — o limite viraria a vulnerabilidade."""
    r = Relogio()
    b = ratelimit.por_minuto(3, relogio=r)

    assert all(b.permite("1.2.3.4") for _ in range(3))
    assert not b.permite("1.2.3.4")
    assert b.permite("5.6.7.8"), "outra origem não pode herdar o limite da primeira"


def test_o_balde_nao_acumula_acima_da_capacidade():
    """Ficar uma hora quieto não compra uma hora de rajada."""
    r = Relogio()
    b = ratelimit.por_minuto(5, relogio=r)

    r.avancar(3600)
    assert all(b.permite("a") for _ in range(5))
    assert not b.permite("a")


def test_a_origem_NAO_vem_de_cabecalho_do_cliente():
    """`X-Forwarded-For` é escrito pelo cliente. Usá-lo como chave daria limite
    infinito a quem variasse o cabeçalho a cada requisição — o controle existiria no
    código e não existiria na prática."""
    class Falso:
        client = type("C", (), {"host": "10.0.0.1"})()
        headers = {"x-forwarded-for": "9.9.9.9", "x-real-ip": "8.8.8.8"}

    assert ratelimit.origem(Falso()) == "10.0.0.1"


def test_sem_cliente_a_chave_e_estavel():
    """Sem `client` — acontece em teste e em transporte não-TCP — a chave não pode ser
    None nem aleatória: aleatória daria limite infinito."""
    class Sem:
        client = None

    assert ratelimit.origem(Sem()) == "desconhecido"
    assert ratelimit.origem(Sem()) == ratelimit.origem(Sem())


# ─── as rotas ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def baldes_limpos():
    ratelimit.CRIAR_CONVERSA.limpar()
    ratelimit.MENSAGEM_DO_CHAT.limpar()
    yield
    ratelimit.CRIAR_CONVERSA.limpar()
    ratelimit.MENSAGEM_DO_CHAT.limpar()


def test_criar_conversa_devolve_429_depois_do_limite(monkeypatch):
    """A rota é pública e é o portão de entrada de tudo."""
    from app.main import app

    monkeypatch.setattr(
        "app.persistence.repo.criar_ou_retomar_conversa",
        lambda s, **kw: (type("C", (), {
            "id": "conv_x", "channel": "web", "state": "novo",
            "criado_em": __import__("datetime").datetime.now(__import__("datetime").UTC),
        })(), True),
    )
    monkeypatch.setattr("app.main.sessao", lambda: None, raising=False)

    cliente = TestClient(app)
    vistos = set()
    for _ in range(int(ratelimit.CRIAR_CONVERSA.capacidade) + 5):
        vistos.add(cliente.post("/api/conversations", json={"external_ref": "x"}).status_code)

    assert 429 in vistos, (
        "sem 429 a rota pública abre conversas sem teto, e cada conversa é o começo "
        "de uma cadeia que gasta inferência"
    )


def test_o_limite_do_chat_e_mais_generoso_que_o_de_abrir_conversa():
    """Digitar rápido é normal; abrir conversas em rajada não é. Se o limite do chat
    fosse o mais apertado, uma conversa legítima seria interrompida antes de um laço
    de abertura ser barrado."""
    assert (ratelimit.MENSAGEM_DO_CHAT.capacidade
            > ratelimit.CRIAR_CONVERSA.capacidade)
