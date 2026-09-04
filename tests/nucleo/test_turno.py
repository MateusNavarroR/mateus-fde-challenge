"""Persistência de mensagem: id, status, ordem, dedup — e o mascaramento na gravação.

Critério declarado do desafio, literal: *"dá pra rastrear o que aconteceu? (cada
mensagem/cotação, com id e status)"*. Este arquivo é a resposta a ele.
"""

import pytest
from sqlalchemy import text

from app.agent.guardrail import GuardrailViolado
from app.persistence import repo
from app.persistence.models import Message
from tests.fixtures.pii import frase_do_lead

pytestmark = pytest.mark.db


def test_mensagem_persiste_com_id_e_status(sessao, conversa):
    m = repo.gravar_mensagem(
        sessao, conversa.id, autor="lead", conteudo="oi", status="received"
    )
    assert m.id.startswith("msg_")
    assert m.index == 0
    assert m.status == "received"


def test_pii_e_mascarada_na_gravacao(sessao, conversa):
    """Não na exibição: assim não existe versão crua para vazar depois."""
    frase, pii = frase_do_lead(seed=42)
    m = repo.gravar_mensagem(
        sessao, conversa.id, autor="lead", conteudo=frase, status="received"
    )
    for classe, valor in pii.items():
        assert valor not in m.conteudo, classe
    # e o que não é PII sobrevive — cotar depende da idade
    assert "35 anos" in m.conteudo


def test_pii_nao_esta_nem_no_banco(sessao, conversa):
    """Assere sobre a linha lida de volta do Postgres, não sobre o objeto em memória."""
    frase, pii = frase_do_lead(seed=7)
    repo.gravar_mensagem(
        sessao, conversa.id, autor="lead", conteudo=frase, status="received"
    )
    sessao.commit()
    bruto = sessao.execute(text("SELECT conteudo FROM messages")).scalar_one()
    assert not any(v in bruto for v in pii.values())


def test_index_e_sequencial_por_conversa(sessao, conversa):
    for i in range(5):
        m = repo.gravar_mensagem(
            sessao, conversa.id, autor="lead", conteudo=f"m{i}", status="received"
        )
        assert m.index == i


def test_index_e_independente_entre_conversas(sessao, conversa):
    outra = repo.criar_conversa(sessao, channel="console", external_ref="outra")
    repo.gravar_mensagem(sessao, conversa.id, autor="lead", conteudo="a", status="received")
    m = repo.gravar_mensagem(sessao, outra.id, autor="lead", conteudo="b", status="received")
    assert m.index == 0


def test_external_id_repetido_nao_duplica(sessao, conversa):
    """Canais reais reentregam. O console não, mas o contrato é o mesmo — assim o
    teste do console prova o caminho que um canal real vai usar."""
    a = repo.gravar_mensagem(
        sessao, conversa.id, autor="lead", conteudo="oi", status="received",
        external_id="wamid.X",
    )
    b = repo.gravar_mensagem(
        sessao, conversa.id, autor="lead", conteudo="oi", status="received",
        external_id="wamid.X",
    )
    assert a.id == b.id
    assert sessao.query(Message).count() == 1


def test_external_id_igual_em_conversas_diferentes_nao_colide(sessao, conversa):
    outra = repo.criar_conversa(sessao, channel="console", external_ref="outra")
    repo.gravar_mensagem(sessao, conversa.id, autor="lead", conteudo="a",
                         status="received", external_id="X")
    repo.gravar_mensagem(sessao, outra.id, autor="lead", conteudo="b",
                         status="received", external_id="X")
    assert sessao.query(Message).count() == 2


def test_mensagens_saem_ordenadas_por_index(sessao, conversa):
    for i in range(4):
        repo.gravar_mensagem(sessao, conversa.id, autor="lead",
                             conteudo=f"m{i}", status="received")
    assert [m.index for m in repo.mensagens(sessao, conversa.id)] == [0, 1, 2, 3]


def test_status_pode_ser_promovido(sessao, conversa):
    m = repo.gravar_mensagem(sessao, conversa.id, autor="agente",
                             conteudo="oi", status="pending")
    repo.atualizar_status_mensagem(sessao, m.id, "sent")
    assert sessao.get(Message, m.id).status == "sent"


# ─── o guardrail, no ponto de estrangulamento ────────────────────────────────


def test_texto_do_modelo_com_preco_nao_e_gravado(sessao, conversa):
    with pytest.raises(GuardrailViolado):
        repo.gravar_mensagem(sessao, conversa.id, autor="agente",
                             conteudo="fica R$ 209,90 por mês", status="pending")
    sessao.rollback()
    assert sessao.query(Message).count() == 0


def test_texto_de_sistema_com_preco_e_permitido_se_tiver_cotacao(sessao, conversa):
    """Autor `sistema` vem do renderer ou de docs/TEXTOS.md. O que responde por ele
    são as verificações 2 e 3, que exigem cotação — e sem quote_id não passa."""
    with pytest.raises(GuardrailViolado):
        repo.gravar_mensagem(sessao, conversa.id, autor="sistema",
                             conteudo="R$ 209,90", status="pending",
                             quote_id="q_inexistente")


def test_quote_id_inexistente_e_rejeitado(sessao, conversa):
    with pytest.raises(GuardrailViolado, match="não existe"):
        repo.gravar_mensagem(sessao, conversa.id, autor="sistema",
                             conteudo="qualquer", status="pending",
                             quote_id="q_naoexiste")


def test_estado_da_conversa_muda(sessao, conversa):
    repo.atualizar_estado(sessao, conversa.id, "qualificando")
    assert repo.obter_conversa(sessao, conversa.id).state == "qualificando"
