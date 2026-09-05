"""Fixtures compartilhadas.

O banco é real: as invariantes que mais importam (prêmio só existe com job `ok`,
timeout não tem status HTTP) são `CHECK` do Postgres, e um SQLite em memória não os
executaria — o teste passaria e a garantia não existiria.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.getenv(
    "APP_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@127.0.0.1:55432/autoseguro",
)

# E o alvo volta para o AMBIENTE, que é o detalhe que faltava. Nem todo teste passa
# pela fixture `engine_teste`: os que instanciam a aplicação (`test_auth`,
# `test_handoff`, `test_injecao`) abrem sessão por `app.config`, cujo default é
# `localhost:5432` — a porta onde mora o Postgres do SISTEMA de quem tem um
# instalado. Nessa máquina a suíte falhava com `password authentication failed`, e
# sem o `skip` gracioso da fixture: dezessete vermelhos que não dizem nada sobre o
# código. Escrever aqui faz os dois lados apontarem para o mesmo banco, e um
# `APP_DATABASE_URL` já definido continua vencendo.
os.environ.setdefault("APP_DATABASE_URL", DATABASE_URL)

TABELAS = (
    "turn_usage",
    "handoffs",
    "quote_attempts",
    "quotes",
    "messages",
    "conversations",
)


@pytest.fixture(scope="session")
def engine_teste():
    eng = create_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        with eng.connect() as c:
            c.execute(text("select 1"))
    except Exception as e:  # pragma: no cover - caminho de ambiente
        pytest.skip(f"Postgres indisponível em {DATABASE_URL}: {e}")
    return eng


@pytest.fixture
def sessao(engine_teste) -> Session:
    """Sessão limpa por teste. Trunca em vez de recriar: as migrações são a fonte do
    esquema e recriá-lo aqui abriria um segundo lugar para ele divergir."""
    fabrica = sessionmaker(bind=engine_teste, expire_on_commit=False)
    s = fabrica()
    s.execute(text(f"TRUNCATE {', '.join(TABELAS)} RESTART IDENTITY CASCADE"))
    s.commit()
    try:
        yield s
    finally:
        s.rollback()
        s.close()


@pytest.fixture
def conversa(sessao):
    from app.persistence import repo

    c = repo.criar_conversa(sessao, channel="console", external_ref="sessao-de-teste")
    sessao.commit()
    return c
