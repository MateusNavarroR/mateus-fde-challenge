"""A tabela de asserções — incluindo a linha que estava invertida.

A spec original dizia *"lead incotável chamou `escalate_to_human` e não chamou
`quote_plan`"*. As duas metades estão erradas, e cada uma tem um teste aqui:

- **recusa não cria handoff** (DECISOES-FECHADAS §2), então `escalate_to_human` num lead
  incotável é o defeito;
- **o agente não tem como saber que o lead é incotável** — o catálogo no system prompt
  tem nomes e coberturas e nenhuma regra —, então `quote_plan` é obrigatório: quem
  decide elegibilidade é a `/quote`, do mesmo jeito que quem decide preço.
"""

from __future__ import annotations

import json

import pytest

from app.contracts.conversa import HandoffTrigger
from app.contracts.quote import MotivoRecusa
from qa.dataset.elegibilidade import Elegibilidade
from qa.replay import assercoes
from qa.replay.assercoes import Desfecho, ESCALATE, QUALIFY, QUOTE
from qa.replay.casos import CasoReplay, Fala, Gabarito
from tests.fixtures.pii import cep_de


def _caso(*, cotavel=True, motivo=None, textos=("oi, quero cotar",), midia=False):
    return CasoReplay(
        conversation_id="c1",
        outcome="ganho",
        falas=tuple(
            Fala(i, "audio" if (midia and i == 0) else "text", t)
            for i, t in enumerate(textos)
        ),
        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep=cep_de("01", com_hifen=False)),
        elegibilidade=Elegibilidade(
            cotavel=cotavel,
            por_idade=motivo is MotivoRecusa.IDADE_ACIMA,
            por_veiculo=motivo is MotivoRecusa.VEICULO_ANTIGO,
            motivo=motivo, ano_veiculo=2018, idade_veiculo=8,
        ),
        _midias=1 if midia else 0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# A tabela
# ─────────────────────────────────────────────────────────────────────────────


def test_lead_incotavel_deve_chamar_quote_plan():
    """A metade invertida nº 1. **`quote_plan` é obrigatório** no lead incotável.

    Não perguntamos ao modelo se o lead é elegível, do mesmo jeito que não perguntamos o
    preço: o catálogo no system prompt não tem regra nenhuma, e quem decide é a `/quote`.
    """
    e = assercoes.esperado_para(_caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA))
    assert e.tools_obrigatorias == (QUOTE,)
    assert e.desfecho is Desfecho.REFUSED
    assert e.motivo_recusa == "idade_acima_do_limite"


def test_lead_incotavel_nao_deve_chamar_escalate():
    """A metade invertida nº 2. Recusa **não** cria handoff (§2)."""
    e = assercoes.esperado_para(_caso(cotavel=False, motivo=MotivoRecusa.VEICULO_ANTIGO))
    assert e.tools_proibidas == (ESCALATE,)


def test_lead_cotavel_deve_cotar_com_idade_e_ano_corretos():
    e = assercoes.esperado_para(_caso())
    assert e.desfecho is Desfecho.OK
    assert e.tools_obrigatorias == (QUOTE,)
    assert e.tools_proibidas == (ESCALATE,)
    assert e.argumentos_de_quote == {
        "idade": 35, "veiculo_ano": 2018, "cep": cep_de("01", com_hifen=False)
    }


def test_o_cep_fica_fora_do_casamento_exato_de_argumentos():
    """O casamento do Agno é igualdade exata, e o argumento é o que o **modelo
    escreveu** — na forma `01XXX-XXX`, com hífen, como o lead falou —, enquanto o
    gabarito é normalizado
    para 8 dígitos corridos. Exigir igualdade ali reprovaria uma extração correta por
    causa de um hífen.

    O CEP continua conferido nos dois lugares onde já está normalizado: `conversations.cep`
    na extração e `quotes.req_cep` na conferência de preço.
    """
    caso = _caso()
    eval_ = assercoes.montar_reliability(caso, assercoes.esperado_para(caso), [_Run()])
    assert set(eval_.expected_tool_call_arguments[QUOTE]) == {"idade", "veiculo_ano"}


def test_argumento_sem_gabarito_nao_e_exigido():
    """Exigir um argumento que o dataset não tem reprovaria o agente pelo corpus."""
    caso = _caso()
    caso = CasoReplay(
        conversation_id=caso.conversation_id, outcome=caso.outcome, falas=caso.falas,
        gabarito=Gabarito(idade=None, veiculo_ano=2018, cep=None),
        elegibilidade=caso.elegibilidade,
    )
    assert assercoes.esperado_para(caso).argumentos_de_quote == {"veiculo_ano": 2018}


# ─────────────────────────────────────────────────────────────────────────────
# A terceira linha: handoff legítimo vindo da fala do lead
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "texto,trigger",
    [
        ("quero falar com um atendente", HandoffTrigger.LEAD_PEDIU),
        ("bati o carro ontem, e agora?", HandoffTrigger.ASSUNTO_SENSIVEL),
        ("vou entrar com processo no Procon", HandoffTrigger.ASSUNTO_SENSIVEL),
    ],
)
def test_fala_do_lead_que_pede_handoff_muda_a_expectativa(texto, trigger):
    """Parte do corpus traz gatilho legítimo na fala do lead. Cobrar `quote_plan` ali
    mediria o agente contra o oposto do que a política manda."""
    e = assercoes.esperado_para(_caso(textos=("oi", texto)))
    assert e.desfecho is Desfecho.ENCAMINHADO
    assert e.gatilho_esperado is trigger
    assert e.tools_obrigatorias == ()
    assert e.tools_proibidas == ()


def test_o_classificador_de_gatilho_e_o_de_producao():
    """Um segundo classificador divergiria do primeiro, e o replay passaria a reprovar o
    agente por concordar com a própria política."""
    import inspect

    fonte = inspect.getsource(assercoes.gatilho_no_corpus)
    assert "from app.handoff import gatilhos" in fonte
    assert "gatilhos.casa(" in fonte


def test_handoff_legitimo_vence_a_incotabilidade():
    """Precedência: um lead incotável que pede um atendente é encaminhado, não recusado."""
    caso = _caso(
        cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA,
        textos=("oi", "prefiro falar com uma pessoa"),
    )
    assert assercoes.esperado_para(caso).desfecho is Desfecho.ENCAMINHADO


# ─────────────────────────────────────────────────────────────────────────────
# Conferência de tools
# ─────────────────────────────────────────────────────────────────────────────


def test_conferir_tools_separa_faltando_de_proibida():
    e = assercoes.esperado_para(_caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA))
    assert assercoes.conferir_tools(e, [QUALIFY, QUOTE]) == ((), ())
    assert assercoes.conferir_tools(e, [QUALIFY]) == ((QUOTE,), ())
    assert assercoes.conferir_tools(e, [QUOTE, ESCALATE]) == ((), (ESCALATE,))


def test_qualify_lead_e_permitido_e_nao_obrigatorio():
    """É legítimo e não obrigatório. Reprovar por chamá-lo — que é o que
    `allow_additional_tool_calls=False` faria — mediria a coisa errada."""
    e = assercoes.esperado_para(_caso())
    assert QUALIFY not in e.tools_obrigatorias
    assert QUALIFY not in e.tools_proibidas


def test_os_nomes_das_tools_sao_os_congelados_em_app_agent_tools():
    """As assinaturas são contrato: mudá-las quebraria a avaliação sem quebrar nenhum
    teste do agente. Este é o teste que faz quebrar."""
    import app.agent.tools as tools

    assert callable(tools.make_qualify_lead) and QUALIFY == "qualify_lead"
    assert callable(tools.make_quote_plan) and QUOTE == "quote_plan"
    assert callable(tools.make_escalate_to_human) and ESCALATE == "escalate_to_human"


# ─────────────────────────────────────────────────────────────────────────────
# A ponte com o ReliabilityEval do Agno
# ─────────────────────────────────────────────────────────────────────────────


class _Msg:
    def __init__(self, tool_calls):
        self.tool_calls = tool_calls
        self.from_history = False


class _Run:
    """Um `RunOutput` mínimo com as duas evidências que o `ReliabilityEval` lê.

    `tools` (as execuções) é a que decide desde a 2.8.0; `messages` (os pedidos) fica
    para anotar a chamada que nunca virou execução.
    """

    def __init__(self, *chamadas, com_erro=()):
        from agno.models.response import ToolExecution

        self.tools = [
            ToolExecution(tool_name=n, tool_args=json.loads(a),
                          tool_call_error=(n in com_erro) or None)
            for n, a in chamadas
        ]
        self.messages = [
            _Msg([{"function": {"name": n, "arguments": a}} for n, a in chamadas])
        ]


def test_agregar_junta_os_turnos_da_conversa():
    """`ReliabilityEval` avalia **um** `RunOutput`, e a nossa unidade é a conversa: o
    `quote_plan` acontece no turno 9 de 11, e avaliar turno a turno reprovaria os
    outros dez por não terem cotado."""
    agregado = assercoes.agregar([_Run(("qualify_lead", "{}")), _Run(("quote_plan", "{}"))])
    assert len(agregado.messages) == 2


def test_reliability_passa_quando_a_cotacao_aconteceu_com_os_argumentos_certos():
    caso = _caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA)
    e = assercoes.esperado_para(caso)
    runs = [
        _Run(("qualify_lead", '{"idade": 35}')),
        _Run(("quote_plan", '{"plano_id": "completo", "idade": 35, "veiculo_ano": 2018}')),
    ]
    resultado = assercoes.montar_reliability(caso, e, runs).run(print_results=False)
    assert resultado.eval_status == "PASSED"


def test_reliability_reprova_quando_o_ano_do_veiculo_diverge_do_gabarito():
    caso = _caso()
    e = assercoes.esperado_para(caso)
    runs = [_Run(("quote_plan", '{"plano_id": "completo", "idade": 35, "veiculo_ano": 2008}'))]
    resultado = assercoes.montar_reliability(caso, e, runs).run(print_results=False)
    assert resultado.eval_status == "FAILED"
    assert "quote_plan" in resultado.failed_argument_checks


def test_reliability_reprova_quando_nao_cotou():
    caso = _caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA)
    e = assercoes.esperado_para(caso)
    resultado = assercoes.montar_reliability(caso, e, [_Run(("qualify_lead", "{}"))]).run(
        print_results=False
    )
    assert resultado.eval_status == "FAILED"
    assert "quote_plan" in resultado.missing_tool_calls


def test_reliability_nao_e_montado_sem_tool_obrigatoria():
    """Um eval sem expectativa produz um `PASSED` que não significa nada."""
    caso = _caso(textos=("quero falar com um atendente",))
    e = assercoes.esperado_para(caso)
    assert assercoes.montar_reliability(caso, e, [_Run()]) is None


# ─────────────────────────────────────────────────────────────────────────────
# Mídia sem transcrição
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fala",
    [
        "não consigo ouvir áudio por aqui, me conta por escrito?",
        "pode digitar o que tem no documento?",
        "não abro imagem aqui, manda por texto",
    ],
)
def test_pedir_por_texto_cumpre_a_politica_de_midia(fala):
    assert assercoes.tratou_midia([fala], encaminhou=False)


def test_encaminhar_tambem_cumpre():
    assert assercoes.tratou_midia(["qualquer coisa"], encaminhou=True)


def test_inventar_o_conteudo_nao_cumpre():
    assert not assercoes.tratou_midia(
        ["Entendi, seu Corolla 2018 está registrado."], encaminhou=False
    )


def test_conversa_com_midia_exige_pedido_de_texto():
    assert assercoes.esperado_para(_caso(midia=True)).exige_pedido_de_texto


# ─────────────────────────────────────────────────────────────────────────────
# O juiz de modelo, e o seu limite
# ─────────────────────────────────────────────────────────────────────────────


def test_o_juiz_so_avalia_tom_e_clareza_da_recusa():
    """Preço é cálculo e tem gabarito fechado; elegibilidade tem gabarito em
    `plans.json`. Perguntar qualquer um dos dois a um juiz trocaria uma conta exata por
    uma opinião cara (CLAUDE.md 27)."""
    criterio = assercoes.CRITERIO_RECUSA.lower()
    assert "preço" not in criterio and "valor" not in criterio
    assert "não promete exceção" in criterio
    assert "trocar o condutor principal" in criterio


def test_o_juiz_e_a_classe_certa_do_agno():
    """A classe é `AgentAsJudgeEval`, não `AgentAsJudge` — o erro está avisado no
    `docs/DECISOES-FECHADAS.md` §6."""
    from agno.eval.agent_as_judge import AgentAsJudgeEval

    juiz = assercoes.montar_juiz_da_recusa()
    assert isinstance(juiz, AgentAsJudgeEval)
    assert juiz.scoring_strategy == "numeric" and juiz.threshold == 8


def test_execucao_que_errou_nao_satisfaz_a_expectativa():
    """`quote_plan` que estourou dentro da tool não cotou.

    Contá-la faria a asserção "o lead incotável foi recusado pela API" passar sem a API
    ter sido consultada — que é exatamente o buraco que a 2.8.0 do Agno fechou ao trocar
    a evidência do pedido pela execução.
    """
    caso = _caso(cotavel=False, motivo=MotivoRecusa.IDADE_ACIMA)
    e = assercoes.esperado_para(caso)
    runs = [_Run(("quote_plan", "{}"), com_erro=("quote_plan",))]
    resultado = assercoes.montar_reliability(caso, e, runs).run(print_results=False)
    assert resultado.eval_status == "FAILED"
