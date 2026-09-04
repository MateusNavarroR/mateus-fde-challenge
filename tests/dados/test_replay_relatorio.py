"""O relatório: o parser, as contagens derivadas e a garantia de que nada cru sai.

A propriedade que este arquivo protege é a mais simples de enunciar e a mais fácil de
perder numa refatoração: **um numerador sem denominador é a forma mais educada de
mentir.** Um replay que morre na conversa 18 e reporta "17 conversas, 100% de acerto"
passa por bem-sucedido.
"""

from __future__ import annotations

import json

from app.privacy.mascarar import contem_pii
from qa.replay.assercoes import Desfecho
from qa.replay.falhas import ClasseDeFalha, Falha
from qa.replay.relatorio import (
    ExtracaoConferida,
    Relatorio,
    ResultadoConversa,
    de_json,
    estimativa_de_parede,
    falha_para_dict,
    render,
)
from tests.fixtures.pii import frase_do_lead


def _ok(cid="c1", **kwargs):
    base = dict(
        conversation_id=cid, estrato="cotavel", outcome_dataset="ganho",
        desfecho_esperado=str(Desfecho.OK), desfecho_obtido=str(Desfecho.OK),
        preco_alcancavel=True, preco_exato=True, perguntas_do_agente=4,
    )
    base.update(kwargs)
    return ResultadoConversa(**base)


# ─────────────────────────────────────────────────────────────────────────────
# Veredito por conversa
# ─────────────────────────────────────────────────────────────────────────────


def test_conversa_que_bate_o_contrato_passa():
    assert _ok().passou


def test_tool_obrigatoria_faltando_reprova():
    """Lead incotável que não chamou `quote_plan` não foi recusado pela API — foi
    recusado pelo modelo, que é o defeito (DECISOES-FECHADAS §9)."""
    assert not _ok(tools_faltando=["quote_plan"]).passou


def test_escalate_em_conversa_de_recusa_reprova():
    """Recusa **não** cria handoff (§2). Chamar `escalate_to_human` num lead incotável é
    o defeito, não o acerto — é a asserção que estava invertida na spec original."""
    assert not _ok(tools_proibidas_chamadas=["escalate_to_human"]).passou


def test_recusa_pelo_motivo_errado_reprova():
    """Nas 60 conversas recusadas pelos dois motivos, a API reporta a idade por
    precedência do serviço. Um replay que só conferisse "recusou" passaria com o motivo
    errado."""
    linha = _ok(
        desfecho_esperado=str(Desfecho.REFUSED), desfecho_obtido=str(Desfecho.REFUSED),
        motivo_esperado="idade_acima_do_limite",
        motivo_obtido="veiculo_acima_de_20_anos",
    )
    assert not linha.passou


def test_preco_fora_do_conjunto_reprova():
    assert not _ok(preco_exato=False).passou


def test_midia_nao_tratada_reprova():
    assert not _ok(tem_midia=True, midia_tratada=False).passou


def test_falha_de_provedor_nao_conta_como_conversa_completa():
    """402 é uma conta sem crédito, não um agente ruim. Somá-los produziria uma taxa de
    acerto que cai quando o cartão vence."""
    linha = _ok(falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402")))
    assert not linha.completou and not linha.passou


# ─────────────────────────────────────────────────────────────────────────────
# Contagens do relatório
# ─────────────────────────────────────────────────────────────────────────────


def _relatorio(**kwargs) -> Relatorio:
    base = dict(modo="desfecho", modelo="ollama:qwen2.5:7b", seed=1, conversas_pedidas=30)
    base.update(kwargs)
    return Relatorio(**base)


def test_conversas_nao_alcancadas_sao_contadas_separadas_das_falhadas():
    """São coisas diferentes: uma falhou porque foi tentada, a outra nunca foi tentada.
    Somá-las esconderia onde a execução parou."""
    rel = _relatorio(
        resultados=[_ok("c1"), _ok("c2", falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402")))],
        interrompido_por="HTTP 402",
    )
    assert rel.completadas == 1
    assert rel.falhadas == 1
    assert rel.nao_alcancadas == 28
    assert not rel.aprovado


def test_taxa_de_acerto_e_sobre_as_completadas():
    rel = _relatorio(
        conversas_pedidas=3,
        resultados=[
            _ok("c1"),
            _ok("c2", tools_faltando=["quote_plan"]),
            _ok("c3", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429"))),
        ],
    )
    assert rel.completadas == 2
    assert rel.aprovados == 1
    assert rel.taxa_de_acerto == 0.5


def test_taxa_e_none_quando_nada_completou():
    """Zero acertos em zero conversas é indefinido. Imprimir "0%" convidaria a ler uma
    execução que não rodou como uma execução que falhou tudo."""
    rel = _relatorio(conversas_pedidas=1, resultados=[
        _ok("c1", falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402")))
    ])
    assert rel.taxa_de_acerto is None
    assert "n/a" in render(rel)


def test_falhas_sao_agrupadas_por_classe():
    rel = _relatorio(resultados=[
        _ok("c1", falha=falha_para_dict(Falha(ClasseDeFalha.PAGAMENTO, "402"))),
        _ok("c2", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429"))),
        _ok("c3", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429 de novo"))),
    ])
    assert rel.falhas_por_classe == {"pagamento_402": 1, "rate_limit": 2}


def test_extracao_por_campo_ignora_campo_sem_gabarito():
    """Campo sem gabarito não conta como erro do agente — contar rebaixaria a taxa por
    culpa do corpus."""
    rel = _relatorio(conversas_pedidas=2, resultados=[
        _ok("c1", extracao=ExtracaoConferida(
            esperado_idade=35, obtido_idade=35,
            esperado_veiculo_ano=2018, obtido_veiculo_ano=2018, cep_correto=True)),
        _ok("c2", extracao=ExtracaoConferida(
            esperado_idade=None, obtido_idade=None,
            esperado_veiculo_ano=2010, obtido_veiculo_ano=2001, cep_correto=None)),
    ])
    por_campo = rel.extracao_por_campo
    assert por_campo["idade"] == {"comparaveis": 1, "acertos": 1}
    assert por_campo["veiculo_ano"] == {"comparaveis": 2, "acertos": 1}
    assert por_campo["cep"] == {"comparaveis": 1, "acertos": 1}


def test_o_relatorio_mede_exatamente_tres_campos():
    """Idade, `veiculo_ano` e CEP. Marca e modelo ficam fora por decisão registrada."""
    rel = _relatorio(resultados=[_ok("c1")])
    assert set(rel.extracao_por_campo) == {"idade", "veiculo_ano", "cep"}


# ─────────────────────────────────────────────────────────────────────────────
# O contador do respondedor reprovando a suíte
# ─────────────────────────────────────────────────────────────────────────────


def test_incompreensao_acima_do_limiar_reprova_a_suite():
    """E a mensagem tem que dizer que o motivo é o harness, não o agente."""
    rel = _relatorio(conversas_pedidas=2, resultados=[
        _ok("c1", perguntas_do_agente=10, nao_entendi=4),
        _ok("c2", perguntas_do_agente=10, nao_entendi=0),
    ])
    assert rel.taxa_nao_entendi == 0.2 + 0.0  # 4 em 20
    assert rel.respondedor_reprovou is False  # exatamente no limiar ainda passa

    rel.resultados[1] = _ok("c2", perguntas_do_agente=10, nao_entendi=1)
    assert rel.respondedor_reprovou is True
    assert not rel.aprovado
    assert "REPROVA: o harness" in render(rel)


def test_sem_perguntas_a_taxa_e_zero_e_nao_divide_por_zero():
    rel = _relatorio(resultados=[_ok("c1", perguntas_do_agente=0)])
    assert rel.taxa_nao_entendi == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Serialização, parser e PII
# ─────────────────────────────────────────────────────────────────────────────


def test_round_trip_preserva_as_linhas():
    """A comparação entre duas execuções — antes e depois de uma mudança de prompt — é o
    uso principal do artefato, e ela precisa que ele seja lido de volta."""
    rel = _relatorio(conversas_pedidas=2, resultados=[
        _ok("c1", extracao=ExtracaoConferida(esperado_idade=35, obtido_idade=35)),
        _ok("c2", falha=falha_para_dict(Falha(ClasseDeFalha.RATE_LIMIT, "429"))),
    ])
    lido = de_json(json.dumps(rel.para_dict(), ensure_ascii=False))
    assert [r.conversation_id for r in lido.resultados] == ["c1", "c2"]
    assert lido.resultados[0].extracao.esperado_idade == 35
    assert lido.resultados[1].falha["classe"] == "rate_limit"
    assert lido.completadas == rel.completadas
    assert lido.taxa_de_acerto == rel.taxa_de_acerto


def test_o_resumo_e_derivado_e_nao_e_lido_de_volta():
    """Reconstruí-lo das linhas impede um relatório editado à mão de afirmar 100% com
    12 linhas vermelhas embaixo."""
    rel = _relatorio(conversas_pedidas=1, resultados=[_ok("c1", tools_faltando=["quote_plan"])])
    dados = rel.para_dict()
    dados["resumo"]["taxa_de_acerto"] = 1.0
    dados["resumo"]["aprovado"] = True
    lido = de_json(json.dumps(dados))
    assert lido.taxa_de_acerto == 0.0
    assert not lido.aprovado


def test_mensagem_de_erro_do_provedor_e_mascarada():
    """O corpo de erro pode ecoar o prompt, e o prompt carrega a fala do lead.

    A defesa não depende de o diretório de saída ser ignorado pelo Git: depende do
    mascaramento.
    """
    fala, _ = frase_do_lead(seed=5)
    assert contem_pii(fala)
    linha = falha_para_dict(
        Falha(ClasseDeFalha.OUTRA, f"400 Bad Request: prompt was {fala}")
    )
    assert not contem_pii(linha["mensagem"])


def test_o_cep_nunca_aparece_no_relatorio_nem_certo_nem_errado():
    """O CEP entra como **acerto ou erro**, nunca como valor: o relatório é um artefato
    que alguém vai colar num README."""
    campos = set(ExtracaoConferida.__dataclass_fields__)
    assert "cep_correto" in campos
    assert not any(c.endswith("_cep") or c == "cep" for c in campos)


def test_relatorio_serializado_nao_contem_pii():
    rel = _relatorio(resultados=[_ok("c1")])
    assert not contem_pii(json.dumps(rel.para_dict(), ensure_ascii=False))


# ─────────────────────────────────────────────────────────────────────────────
# A estimativa de parede
# ─────────────────────────────────────────────────────────────────────────────


def test_estimativa_reproduz_a_tabela_de_custo_de_relogio():
    """DECISOES-FECHADAS §9: 203 inferências ≈ 10 min, 16.470 ≈ 14 h."""
    assert estimativa_de_parede(203) == "~10 min"
    assert estimativa_de_parede(991) == "~50 min"
    assert estimativa_de_parede(16470) == "~13.7 h"


def test_render_sempre_diz_o_denominador():
    rel = _relatorio(conversas_pedidas=30, resultados=[_ok("c1")])
    texto = render(rel)
    assert "1/30 completadas" in texto
    assert "não alcançadas" in texto
