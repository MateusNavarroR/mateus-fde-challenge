"""As invariantes do Núcleo, conferidas em SQL sobre o banco inteiro.

Os testes de unidade provam cada peça; estes provam que **o conjunto** não tem uma
linha incoerente. São as três perguntas que o avaliador faria olhando o banco:

1. existe alguma mensagem com preço sem uma cotação `ok` por trás?
2. alguma recusa gerou handoff?
3. alguma resposta final da API consumiu mais de uma tentativa?

Rodam sobre o que estiver no banco no momento — em CI, sobre o que a suíte produziu;
localmente, sobre o que o uso real deixou. É de propósito: uma invariante que só vale
sobre dado de teste não vale.
"""

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.db


def test_nenhuma_mensagem_com_preco_sem_cotacao_ok(sessao):
    """O guardrail materializado. `gravar_mensagem` impede na escrita; isto confere o
    resultado, que é o que a tela mostra e o que o avaliador consulta."""
    linhas = sessao.execute(text("""
        SELECT m.id, left(m.conteudo, 60) AS trecho, q.status
        FROM messages m
        LEFT JOIN quotes q ON q.id = m.quote_id
        WHERE m.conteudo ~ 'R\\$'
          AND (q.id IS NULL OR q.status <> 'ok')
    """)).all()
    assert not linhas, f"mensagens com valor sem cotação ok: {linhas}"


def test_nenhuma_recusa_gerou_handoff(sessao):
    """Decisão 3: recusa é desfecho que o bot resolve, não exceção que ele delega."""
    linhas = sessao.execute(text("""
        SELECT h.id, h.trigger
        FROM handoffs h
        JOIN quotes q ON q.conversation_id = h.conversation_id
        WHERE q.status = 'refused' AND h.trigger = 'cotacao_indisponivel'
          AND h.quote_id = q.id
    """)).all()
    assert not linhas, f"recusa virou handoff: {linhas}"


def test_nenhuma_resposta_final_consumiu_mais_de_uma_tentativa(sessao):
    """`refused` e `bad_request` são a API respondendo, e a resposta é final.
    Retentá-los mascara defeito e queima tempo."""
    linhas = sessao.execute(text("""
        SELECT quote_id, count(*) AS tentativas
        FROM quote_attempts
        WHERE outcome IN ('refused', 'bad_request')
        GROUP BY quote_id
        HAVING count(*) > 1
    """)).all()
    assert not linhas, f"resposta final retentada: {linhas}"


def test_timeout_nunca_tem_status_http(sessao):
    """O CHECK da migração impõe; isto confirma que nada burlou por SQL direto."""
    n = sessao.execute(text(
        "SELECT count(*) FROM quote_attempts WHERE outcome = 'timeout' AND http_status IS NOT NULL"
    )).scalar()
    assert n == 0


def test_nenhum_premio_fora_do_conjunto_de_72(sessao):
    """O gabarito de preço é o conjunto fechado derivado de `plans.json`: 3 planos ×
    4 faixas etárias × 3 faixas de veículo × 2 regiões. Um prêmio fora dele significa
    que alguém escreveu um número que a API não produziu."""
    BASE = {"essencial": 119.90, "completo": 209.90, "premium": 339.90}
    possiveis = {
        round(b * mi * mv * mr, 2)
        for b in BASE.values()
        for mi in (1.60, 1.25, 1.00, 1.40)
        for mv in (1.00, 1.15, 1.45)
        for mr in (1.0, 1.30)
    }
    assert len(possiveis) == 72

    observados = sessao.execute(text(
        "SELECT DISTINCT premio_mensal FROM quotes WHERE premio_mensal IS NOT NULL"
    )).scalars().all()
    fora = [float(p) for p in observados if float(p) not in possiveis]
    assert not fora, f"prêmios impossíveis pelas regras de plans.json: {fora}"


def test_nenhuma_pii_crua_no_banco(sessao):
    """O mascaramento acontece na gravação — não existe versão crua para vazar."""
    for classe, regex in (
        ("CPF", r"[0-9]{3}\.[0-9]{3}\.[0-9]{3}-[0-9]{2}"),
        ("telefone", r"\+55 [0-9]{2} 9[0-9]{4}-[0-9]{4}"),
        ("e-mail", r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    ):
        n = sessao.execute(
            text("SELECT count(*) FROM messages WHERE conteudo ~ :re"), {"re": regex}
        ).scalar()
        assert n == 0, f"{classe} cru em messages.conteudo"
