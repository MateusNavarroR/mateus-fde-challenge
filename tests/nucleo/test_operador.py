"""O operador responde na conversa que assumiu — a outra ponta do handoff.

Sem isto, a fila era uma lista que ninguém atendia: o agente encerrava a participação,
o caso entrava na fila, e ali parava. "Assumir" mudava um status e não abria porta
nenhuma.

Os testes daqui travam as três decisões que a rota carrega: **só depois do handoff**,
**autor `operador`** (distinguível de `sistema` e de `agente` no histórico), e **PII
mascarada na escrita**, como em todo o resto do sistema.
"""

from __future__ import annotations

import pytest

from tests.fixtures.pii import cep_de

pytestmark = pytest.mark.db


@pytest.fixture
def cliente(sessao):
    """`TestClient` com a sessão da suíte, e sem login exigido.

    A dependência de sessão é sobrescrita para a do teste — senão a rota abriria uma
    conexão própria e não veria o `commit` feito aqui.
    """
    from fastapi.testclient import TestClient

    from app.auth import exigir_admin
    from app.main import app, sessao as dep_sessao

    app.dependency_overrides[dep_sessao] = lambda: sessao
    app.dependency_overrides[exigir_admin] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_so_responde_DEPOIS_do_handoff(cliente, sessao, conversa):
    """Enquanto o agente conduz, ele é o único que fala pela empresa.

    Duas vozes no mesmo turno deixam o lead sem saber com quem está falando — e o
    agente não tem como saber que um humano escreveu no meio do seu raciocínio.
    """
    r = cliente.post(
        f"/api/conversations/{conversa.id}/mensagens", json={"text": "oi, aqui é a equipe"}
    )
    assert r.status_code == 409
    assert r.json()["error"] == "conversa_nao_encaminhada"


def test_depois_do_handoff_grava_com_autor_OPERADOR(cliente, sessao, conversa):
    """`operador`, e não `sistema`: a distinção é auditoria.

    Para o lead os dois saem iguais, de propósito — é a mesma empresa falando. No
    admin, a pergunta que a tela existe para responder é justamente "isto foi um
    template determinístico ou uma pessoa escrevendo?".
    """
    from app.persistence import repo

    repo.atualizar_estado(sessao, conversa.id, "encaminhado")
    sessao.commit()

    r = cliente.post(
        f"/api/conversations/{conversa.id}/mensagens",
        json={"text": "Oi! Aqui é a Ana, assumi seu atendimento."},
    )
    assert r.status_code == 201
    corpo = r.json()
    assert corpo["autor"] == "operador"
    assert corpo["conteudo"] == "Oi! Aqui é a Ana, assumi seu atendimento."
    assert corpo["status"] == "sent"


def test_a_PII_do_operador_e_mascarada_como_a_de_todo_mundo(cliente, sessao, conversa):
    """Um atendente com pressa colando o CPF do lead não é hipótese, é rotina.

    A rota não tem tratamento próprio de PII — ela usa `repo.gravar_mensagem`, que
    mascara na escrita. Este teste é o que garante que ninguém adicione um caminho
    paralelo de gravação que pule essa etapa.
    """
    from app.persistence import repo

    repo.atualizar_estado(sessao, conversa.id, "encaminhado")
    sessao.commit()
    cep = cep_de("07")

    r = cliente.post(
        f"/api/conversations/{conversa.id}/mensagens",
        json={"text": f"confirmando o endereço do CEP {cep}, tudo certo"},
    )
    assert r.status_code == 201
    assert cep not in r.json()["conteudo"]
    assert "[CEP]" in r.json()["conteudo"]


def test_texto_vazio_nao_vira_mensagem(cliente, sessao, conversa):
    from app.persistence import repo

    repo.atualizar_estado(sessao, conversa.id, "encaminhado")
    sessao.commit()

    assert cliente.post(
        f"/api/conversations/{conversa.id}/mensagens", json={"text": "   "}
    ).status_code == 422


def test_conversa_inexistente_e_404_e_nao_409(cliente):
    """A ordem das checagens importa: 409 numa conversa que não existe mentiria sobre
    o motivo, mandando o operador procurar um handoff que nunca houve."""
    r = cliente.post("/api/conversations/conv_fantasma/mensagens", json={"text": "oi"})
    assert r.status_code == 404


def test_a_mensagem_do_operador_APARECE_no_historico_da_conversa(
    cliente, sessao, conversa
):
    """Ponta a ponta: o que o operador escreveu entra na mesma lista que o resto.

    É o que faz o histórico continuar sendo a resposta ao critério de rastreabilidade
    depois que uma pessoa entra na conversa.
    """
    from app.persistence import repo

    repo.atualizar_estado(sessao, conversa.id, "encaminhado")
    sessao.commit()
    cliente.post(f"/api/conversations/{conversa.id}/mensagens", json={"text": "assumido"})

    detalhe = cliente.get(f"/api/conversations/{conversa.id}").json()
    autores = [m["autor"] for m in detalhe["messages"]]
    assert "operador" in autores
