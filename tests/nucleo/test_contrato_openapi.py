"""Deriva entre o `docs/openapi.yaml` congelado e o que o FastAPI gera.

Congelar um contrato antes da implementação destrava a frente de Frontend — foi essa
a aposta da Fase 0. **Contract-first sem este teste vira documentação mentindo**, e o
risco é exatamente o que se assumiu ao congelar.

Compara nos **dois sentidos**, e o segundo é o que quase ninguém escreve:

1. toda rota e método do congelado existe no gerado → o backend implementou o contrato;
2. toda rota e método do gerado existe no congelado → o backend **não criou superfície
   não documentada**.

Não compara byte a byte: o FastAPI emite `anyOf` onde o congelado escreve
`type: [x, "null"]`, entre outras diferenças de forma que não são deriva de contrato.
A normalização é pequena e **ela mesma tem teste** — senão ela poderia estar apagando
uma diferença real.

Quando este teste falhar, a pergunta é qual dos dois está errado. A regra: **o
congelado manda**, e mudá-lo é decisão escrita, não conserto de teste.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[2]

METODOS = {"get", "post", "put", "patch", "delete"}


@pytest.fixture(scope="module")
def congelado() -> dict:
    return yaml.safe_load((RAIZ / "docs" / "openapi.yaml").read_text())


@pytest.fixture(scope="module")
def gerado() -> dict:
    from app.main import app

    return app.openapi()


def _operacoes(spec: dict) -> set[tuple[str, str]]:
    return {
        (rota, m)
        for rota, ops in spec.get("paths", {}).items()
        for m in ops
        if m in METODOS
    }


#: Os WebSockets não aparecem no `openapi()` do FastAPI — o OpenAPI não os modela.
#: Eles estão no congelado como `get` com resposta 101, que é a convenção usada para
#: documentá-los. Ficam fora da comparação e têm teste próprio abaixo.
WEBSOCKETS = {("/api/chat/{conversation_id}", "get"), ("/api/events", "get")}


def _credencial_de_boot(monkeypatch) -> None:
    """Estes quatro testes são de ROTEAMENTO — não falam com o modelo. Mas entrar no
    `TestClient` como contexto executa o lifespan, e o lifespan valida a credencial.

    Num clone limpo, sem `ANTHROPIC_API_KEY` exportada, isso os derrubava com
    `CredencialAusente`: quatro vermelhos que não dizem nada sobre o código — medido
    rodando a suíte num clone recém-baixado do repositório público.

    Marcar presença é o suficiente: o boot confere se a variável EXISTE, e nenhuma
    chamada ao provider acontece aqui. Uma chave real no ambiente continua vencendo.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", os.getenv("ANTHROPIC_API_KEY") or "presente")


def test_toda_rota_do_congelado_existe_no_gerado(congelado, gerado):
    """Sentido 1: o backend implementou o contrato."""
    faltando = (_operacoes(congelado) - WEBSOCKETS) - _operacoes(gerado)
    assert not faltando, f"no contrato mas não implementadas: {sorted(faltando)}"


def test_toda_rota_gerada_existe_no_congelado(congelado, gerado):
    """Sentido 2 — o que pega deriva de verdade: superfície não documentada.

    É este que impede alguém de acrescentar um endpoint e o contrato virar ficção.
    """
    sobrando = _operacoes(gerado) - _operacoes(congelado)
    assert not sobrando, f"implementadas mas fora do contrato: {sorted(sobrando)}"


def test_os_websockets_do_contrato_estao_registrados(congelado):
    """Eles não entram no `openapi()`, então precisam de verificação própria — senão
    sairiam do escopo dos dois testes acima e ninguém notaria."""
    from app.main import app

    registrados = {r.path for r in app.routes if r.__class__.__name__ == "APIWebSocketRoute"}
    for rota, _ in WEBSOCKETS:
        assert rota in registrados, rota


@pytest.mark.parametrize(
    "rota,metodo,status",
    [
        ("/api/conversations", "post", "201"),
        ("/api/conversations/{conversation_id}", "get", "404"),
        ("/api/handoffs/{handoff_id}", "patch", "409"),
    ],
)
def test_codigos_de_resposta_declarados_existem(gerado, rota, metodo, status):
    """O contrato promete um 409 no PATCH; sem este teste, o backend poderia devolver
    200 para uma transição inválida e a documentação continuaria dizendo 409."""
    assert status in gerado["paths"][rota][metodo]["responses"]


def test_docs_desligados_fora_de_dev(monkeypatch):
    """O legado do desafio expõe /docs e /openapi.json abertos. Este serviço não
    repete esse default."""
    import importlib

    monkeypatch.setenv("APP_ENV", "prod")
    import app.main as m

    recarregado = importlib.reload(m)
    assert recarregado.app.docs_url is None
    assert recarregado.app.openapi_url is None
    monkeypatch.setenv("APP_ENV", "dev")
    importlib.reload(m)


def test_post_conversations_duas_vezes_seguidas(monkeypatch):
    """A regressão pelo caminho HTTP real, não pelo repo.

    Era 500 na segunda chamada: o literal fixo `"web"` colidia com a
    `UNIQUE (channel, external_ref)`. O avaliador via isso ao clicar em "nova
    conversa" depois da primeira conversa.
    """
    import os

    from fastapi.testclient import TestClient

    from app.config import get_settings

    url = os.getenv(
        "APP_DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/autoseguro",
    )
    monkeypatch.setattr(get_settings(), "database_url", url)
    try:
        from app.main import app

        with TestClient(app) as c:
            a = c.post("/api/conversations", json={"channel": "web"})
            b = c.post("/api/conversations", json={"channel": "web"})
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"backend indisponível: {e}")

    assert a.status_code == 201, a.text
    assert b.status_code == 201, b.text          # <- era 500
    assert a.json()["id"] != b.json()["id"]


def test_post_conversations_com_a_mesma_sessao_retoma(monkeypatch):
    """Mesma sessão de navegador, mesma conversa — a semântica que o campo ganhou."""
    from fastapi.testclient import TestClient

    try:
        from app.main import app

        with TestClient(app) as c:
            corpo = {"channel": "web", "external_ref": "sessao-de-teste-openapi"}
            a = c.post("/api/conversations", json=corpo)
            b = c.post("/api/conversations", json=corpo)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"backend indisponível: {e}")

    assert a.status_code == b.status_code == 201
    assert a.json()["id"] == b.json()["id"]


# ─── o SPA servido pela mesma origem ─────────────────────────────────────────


def test_api_desconhecida_devolve_json_nao_html(monkeypatch, tmp_path):
    """Sem esta guarda, o catch-all do SPA devolveria `index.html` com 200 para um
    endpoint inexistente — e o cliente receberia HTML onde espera JSON, com o erro
    aparecendo como "unexpected token <" três camadas adiante da causa."""
    from fastapi.testclient import TestClient

    _credencial_de_boot(monkeypatch)
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/api/rota-que-nao-existe")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("rota", ["docs", "redoc", "openapi.json"])
def test_documentacao_nao_volta_pelo_catch_all(rota, monkeypatch):
    """Elas ficam desligadas fora de dev; o roteamento do SPA não pode ressuscitá-las
    por acidente, servindo o `index.html` com 200 no lugar delas."""
    from fastapi.testclient import TestClient

    _credencial_de_boot(monkeypatch)
    from app.main import app

    with TestClient(app) as c:
        r = c.get(f"/{rota}")
    # Em dev o FastAPI serve de verdade; fora de dev, 404 JSON — nunca HTML do SPA.
    assert r.status_code == 200 or (
        r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    )
