"""Espelho SQLAlchemy das migrações.

**O SQL é a fonte.** Este módulo não redefine o esquema, não cria tabela e não declara
`CHECK` — os invariantes que importam (prêmio só existe quando o job é `ok`, timeout
não tem status HTTP, handoff resolvido tem data) são impostos pelo banco, em
`db/migrations/0001_inicial.sql`. Duplicá-los aqui criaria dois lugares para divergir.

Os tipos `ENUM` são referenciados com `create_type=False` pelo mesmo motivo.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _enum(nome: str, *valores: str) -> Enum:
    return Enum(*valores, name=nome, create_type=False, native_enum=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    channel: Mapped[str] = mapped_column(Text)
    external_ref: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(
        _enum("conversation_state", "novo", "qualificando", "cotando", "cotado",
              "fechado", "encaminhado"),
        default="novo",
    )

    # Perfil de qualificação, desnormalizado: cinco campos sempre lidos juntos.
    idade: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    veiculo_ano: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    data_inicio: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    plano_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())
    atualizado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                       server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(back_populates="conversation")


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))

    #: Ordem canônica. É por ela que se ordena e se pagina, NUNCA por timestamp.
    index: Mapped[int] = mapped_column("index", Integer)

    autor: Mapped[str] = mapped_column(
        _enum("message_autor", "lead", "agente", "sistema", "operador")
    )
    tipo: Mapped[str] = mapped_column(
        _enum("message_tipo", "text", "image", "audio", "document"), default="text"
    )
    #: SEMPRE mascarado. É a coluna exibida na UI e no transcript entregue.
    conteudo: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        _enum("message_status", "received", "pending", "sent", "failed", "discarded")
    )
    external_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Não-nulo quando a mensagem apresenta uma cotação. O guardrail materializado.
    quote_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    status: Mapped[str] = mapped_column(
        _enum("quote_job_status", "pending", "ok", "refused", "failed"),
        default="pending",
    )

    req_plano_id: Mapped[str] = mapped_column(Text)
    req_idade: Mapped[int] = mapped_column(SmallInteger)
    req_veiculo_ano: Mapped[int] = mapped_column(SmallInteger)
    req_cep: Mapped[str | None] = mapped_column(String(8), nullable=True)
    req_data_inicio: Mapped[dt.date | None] = mapped_column(Date, nullable=True)

    premio_mensal: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    franquia: Mapped[int | None] = mapped_column(Integer, nullable=True)
    carencia_dias: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    pro_rata_valor: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    pro_rata_dias: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    motivo_recusa: Mapped[str | None] = mapped_column(Text, nullable=True)
    erro_outcome: Mapped[str | None] = mapped_column(
        _enum("quote_outcome", "transient", "timeout", "ok", "refused", "bad_request"),
        nullable=True,
    )
    circuito_aberto: Mapped[bool] = mapped_column(Boolean, default=False)

    total_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())
    finalizado_em: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True),
                                                              nullable=True)

    attempts: Mapped[list["QuoteAttempt"]] = relationship(
        back_populates="quote", order_by="QuoteAttempt.attempt"
    )


class QuoteAttempt(Base):
    """Uma linha por tentativa HTTP. É a evidência de C2 — o que permite responder,
    sem log: "tentamos 3 vezes, a 1ª deu 503 em 40 ms, a 2ª estourou o timeout aos
    12 s, a 3ª voltou 200 aos 8,01 s"."""

    __tablename__ = "quote_attempts"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    quote_id: Mapped[str] = mapped_column(ForeignKey("quotes.id"))
    attempt: Mapped[int] = mapped_column(SmallInteger)
    #: NULL quando não houve resposta: timeout de leitura ou erro de conexão.
    http_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(
        _enum("quote_outcome", "transient", "timeout", "ok", "refused", "bad_request")
    )
    #: Texto cru da API, para diagnóstico. NUNCA exibido ao lead, e passa pelo
    #: mascaramento antes de gravar: o corpo do 422 do Pydantic ecoa o payload.
    detalhe: Mapped[str | None] = mapped_column(Text, nullable=True)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())

    quote: Mapped[Quote] = relationship(back_populates="attempts")


class Handoff(Base):
    __tablename__ = "handoffs"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    #: Qual REGRA disparou. A fila mostra o gatilho, não uma frase gerada.
    trigger: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: 'regra' | 'modelo' — um gatilho determinístico e uma decisão do modelo produzem
    #: o mesmo sinal, e a fila distingue os dois.
    disparado_por: Mapped[str] = mapped_column(Text, default="regra")
    quote_id: Mapped[str | None] = mapped_column(ForeignKey("quotes.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        _enum("handoff_status", "pendente", "assumido", "resolvido"), default="pendente"
    )
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())
    assumido_em: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True),
                                                            nullable=True)


class TurnUsage(Base):
    """Custo e uso por turno. Substitui o Langfuse: a informação fica na própria base,
    disponível para quem rodar `docker compose up`."""

    __tablename__ = "turn_usage"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    message_id: Mapped[str] = mapped_column(ForeignKey("messages.id"))
    conversation_id: Mapped[str] = mapped_column(ForeignKey("conversations.id"))
    model: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    #: NULL, e não 0, quando o provider não reporta caching — o Ollama não reporta.
    #: Um zero diria "o cache não acertou" onde a verdade é "não existe cache aqui".
    cache_read: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    #: Sem isto, um custo histórico deixa de ser auditável assim que o preço muda.
    pricing_vigencia: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    criado_em: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True),
                                                   server_default=func.now())


# `gatilhos_secundarios` chega na migração 0003, com a fatia 5.
_ = ARRAY  # mantém o import explícito para quando a coluna for mapeada
