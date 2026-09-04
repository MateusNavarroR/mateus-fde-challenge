"""Engine e sessão.

As migrações em `db/migrations/` são a fonte do esquema. Este módulo não cria tabela
— `Base.metadata.create_all` não é chamado em lugar nenhum de propósito, para que não
exista um segundo lugar onde o esquema é definido e possa divergir do SQL.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine = None
_Sessao: sessionmaker[Session] | None = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def sessao_factory() -> sessionmaker[Session]:
    global _Sessao
    if _Sessao is None:
        _Sessao = sessionmaker(bind=engine(), expire_on_commit=False)
    return _Sessao


@contextmanager
def sessao() -> Iterator[Session]:
    s = sessao_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
