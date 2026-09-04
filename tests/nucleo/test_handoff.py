"""Os sete gatilhos de handoff.

O critério declarado é *"explícito e defensável"*. O que reprova não é ser generoso
ou econômico com a fila — é o gatilho implícito, que ninguém consegue enumerar nem
testar. Por isso: **um teste por gatilho**, e um bloco igualmente importante para o
que **não** é gatilho.
"""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy import text

from app import textos
from app.contracts.conversa import HandoffTrigger
from app.handoff import gatilhos
from app.handoff.gatilhos import Contexto
from app.persistence import repo
from app.persistence.models import Handoff

pytestmark = pytest.mark.db


# ─── um teste por gatilho ────────────────────────────────────────────────────

CASOS = [
    (HandoffTrigger.ASSUNTO_SENSIVEL,
     Contexto(texto_do_lead="bati o carro ontem e queria abrir sinistro"), "alto"),
    (HandoffTrigger.GUARDRAIL,
     Contexto(violacoes_guardrail=2), "alto"),
    (HandoffTrigger.LEAD_PEDIU,
     Contexto(texto_do_lead="prefiro falar com uma pessoa"), "—"),
    (HandoffTrigger.COTACAO_INDISPONIVEL,
     Contexto(cotacao_falhou=True), "alto"),
    (HandoffTrigger.EXTRACAO_FALHOU,
     Contexto(tentativas_extracao={"cep": 2}), "médio"),
    (HandoffTrigger.OBJECAO_FORA_DA_ALCADA,
     Contexto(texto_do_lead="continua caro demais", objecoes_de_preco=2), "baixo"),
    (HandoffTrigger.MIDIA_SEM_TEXTO,
     Contexto(tipo_da_mensagem="audio", midias_apos_pedido=2), "baixo"),
]


@pytest.mark.parametrize("trigger,contexto,custo", CASOS, ids=[c[0].value for c in CASOS])
def test_um_teste_por_gatilho(trigger, contexto, custo):
    assert gatilhos.casa(trigger, contexto), f"{trigger} (custo do erro: {custo})"
    assert gatilhos.avaliar(contexto)[0] is trigger


def test_os_sete_gatilhos_tem_regra():
    """Se alguém acrescentar um membro ao enum e esquecer a regra, o gatilho existiria
    no contrato e nunca dispararia."""
    assert {t for t, _ in gatilhos.REGRAS} == set(HandoffTrigger)
    assert len(gatilhos.REGRAS) == 7


# ─── o que NÃO é gatilho — vale tanto quanto ─────────────────────────────────


@pytest.mark.parametrize(
    "contexto,porque",
    [
        (Contexto(texto_do_lead="achei caro", objecoes_de_preco=1),
         "primeira objeção: o agente responde e insiste"),
        (Contexto(tipo_da_mensagem="audio", midias_apos_pedido=1),
         "primeira mídia: o agente pede por texto"),
        (Contexto(tentativas_extracao={"cep": 1, "idade": 1}),
         "falhar uma vez em DOIS campos não é falhar duas vezes no mesmo"),
        (Contexto(violacoes_guardrail=1),
         "a primeira violação descarta a mensagem e conta; a segunda encaminha"),
        (Contexto(texto_do_lead="quero cotar um seguro pro meu Onix"),
         "conversa normal"),
        (Contexto(texto_do_lead="o sistema deu erro na cotação, tenta de novo"),
         "5xx que o retry resolveu — encaminhar aqui encheria a fila com o que se "
         "resolve sozinho em 96% dos casos"),
    ],
)
def test_o_que_nao_e_gatilho(contexto, porque):
    assert gatilhos.avaliar(contexto) is None, porque


def test_recusa_nao_e_gatilho_nem_existe_no_enum():
    """30% do tráfego. Um humano releria a mesma regra fixa em plans.json e daria o
    mesmo "não"; encaminhar isso encheria a fila com casos sem saída."""
    assert not hasattr(HandoffTrigger, "COTACAO_RECUSADA")
    assert "cotacao_recusada" not in {str(t) for t in HandoffTrigger}


# ─── precedência ─────────────────────────────────────────────────────────────


def test_assunto_sensivel_vence_lead_pediu():
    c = Contexto(texto_do_lead="bati o carro, quero falar com alguém")
    trigger, _, secundarios = gatilhos.avaliar(c)
    assert trigger is HandoffTrigger.ASSUNTO_SENSIVEL
    assert HandoffTrigger.LEAD_PEDIU in secundarios      # não se perde


def test_a_ordem_da_declaracao_e_a_precedencia():
    """A precedência é dado, não uma cadeia de `if`. Mudar a ordem da lista muda o
    comportamento — e é isso que a torna auditável."""
    ordem = [t for t, _ in gatilhos.REGRAS]
    assert ordem[0] is HandoffTrigger.ASSUNTO_SENSIVEL
    assert ordem.index(HandoffTrigger.COTACAO_INDISPONIVEL) < ordem.index(
        HandoffTrigger.OBJECAO_FORA_DA_ALCADA
    )


def test_secundarios_saem_na_ordem_de_precedencia():
    c = Contexto(texto_do_lead="bati o carro, quero falar com alguém",
                 cotacao_falhou=True)
    _, _, secundarios = gatilhos.avaliar(c)
    assert secundarios == [HandoffTrigger.LEAD_PEDIU, HandoffTrigger.COTACAO_INDISPONIVEL]


# ─── o prefixo de texto do assunto sensível ──────────────────────────────────


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("bati o carro ontem", "sinistro"),
        ("levaram meu carro no fim de semana", "sinistro"),
        ("fiquei ferido no acidente", "sinistro"),
        ("meu advogado vai entrar com processo", "juridico"),
        ("abri reclamação no Procon", "juridico"),
        ("quero cotar um seguro", None),
    ],
)
def test_o_assunto_escolhe_o_prefixo(texto, esperado):
    """Dois textos e não um: "sinto muito" numa notificação extrajudicial soa como
    admissão, e a ausência dele depois de "bati o carro" soa como frieza."""
    assert gatilhos.assunto_do_texto(texto) == esperado


@pytest.mark.parametrize(
    "trigger,assunto,esperado",
    [
        ("cotacao_indisponivel", None, textos.INDISPONIBILIDADE + "\n\n" + textos.DESPEDIDA),
        ("assunto_sensivel", "sinistro", textos.SENSIVEL_SINISTRO + "\n\n" + textos.DESPEDIDA),
        ("assunto_sensivel", "juridico", textos.SENSIVEL_JURIDICO + "\n\n" + textos.DESPEDIDA),
        ("lead_pediu_atendente", None, textos.DESPEDIDA),
        ("objecao_fora_da_alcada", None, textos.DESPEDIDA),
    ],
)
def test_composicao_prefixo_mais_despedida(trigger, assunto, esperado):
    assert textos.compor_handoff(trigger, assunto=assunto) == esperado


# ─── persistência ────────────────────────────────────────────────────────────


def test_registrar_cria_o_handoff_e_encerra_a_conversa(sessao, conversa):
    h = gatilhos.registrar(sessao, conversa.id, HandoffTrigger.LEAD_PEDIU,
                           "o lead pediu uma pessoa")
    assert h.status == "pendente" and h.disparado_por == "regra"
    # `encaminhado` é terminal — é a saída de todos os gatilhos.
    assert repo.obter_conversa(sessao, conversa.id).state == "encaminhado"


def test_secundarios_sao_persistidos(sessao, conversa):
    h = gatilhos.registrar(
        sessao, conversa.id, HandoffTrigger.ASSUNTO_SENSIVEL, "sinistro",
        secundarios=[HandoffTrigger.LEAD_PEDIU],
    )
    sessao.commit()
    assert h.gatilhos_secundarios == ["lead_pediu_atendente"]


def test_gatilho_inventado_e_recusado_pelo_banco(sessao, conversa):
    """A migração 0003 fecha o conjunto. Enum e SQL divergirem é o tipo de coisa que
    só explode em produção."""
    with pytest.raises(IntegrityError):
        sessao.execute(text(
            "INSERT INTO handoffs (id, conversation_id, trigger, reason) "
            "VALUES ('h_x', :c, 'inventado', 'x')"
        ), {"c": conversa.id})
    sessao.rollback()


def test_o_enum_bate_com_o_check_do_banco(sessao):
    """Se alguém acrescentar um gatilho no Python e esquecer o SQL, ou o inverso,
    isto falha aqui — em vez de o INSERT explodir depois."""
    definicao = sessao.execute(text(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
        "WHERE conname = 'handoffs_trigger_conhecido'"
    )).scalar_one()
    for t in HandoffTrigger:
        assert f"'{t.value}'" in definicao, t
    assert "cotacao_recusada" not in definicao


def test_disparado_por_distingue_regra_de_modelo(sessao, conversa):
    """Um gatilho determinístico e uma decisão do modelo produzem o MESMO sinal — e a
    fila distingue os dois. É o ponto do padrão write-back."""
    a = gatilhos.registrar(sessao, conversa.id, HandoffTrigger.COTACAO_INDISPONIVEL,
                           "job failed", disparado_por="regra")
    outra = repo.criar_conversa(sessao, channel="console", external_ref="outra-h")
    b = gatilhos.registrar(sessao, outra.id, HandoffTrigger.LEAD_PEDIU,
                           "pediu", disparado_por="modelo")
    assert type(a) is type(b)
    assert a.disparado_por != b.disparado_por


# ─── `encaminhado` é terminal de verdade ─────────────────────────────────────


async def test_agente_para_de_responder_apos_o_handoff(sessao, conversa):
    """O estado é terminal: o agente avisa que um atendente vai assumir e para.

    A mensagem do lead continua sendo persistida — ela é do operador agora, não
    nossa para responder.
    """
    from app.agent import turno

    gatilhos.registrar(sessao, conversa.id, HandoffTrigger.LEAD_PEDIU, "pediu")
    sessao.commit()

    class CanalMudo:
        def __init__(self):
            self.enviadas = []

        async def send(self, *a, **kw):
            self.enviadas.append(kw)
            return "x"

    canal = CanalMudo()
    await turno.responder(conversa.id, "oi? tem alguém?", canal)
    assert canal.enviadas == []


def test_o_relogio_de_demora_desliga_em_encaminhado():
    """Senão o lead que escreve depois do handoff recebe "só um instante" a cada
    10 s, para sempre."""
    import asyncio

    from app.conversa import Conversa

    async def agente(_t):
        await asyncio.sleep(0.05)
        return "resposta"

    saidas = []

    async def entregar(t, autor):
        saidas.append(t)

    async def rodar():
        c = Conversa(conversation_id="c1", agente=agente, entregar=entregar)
        c.encaminhar()
        await c.receber("oi")

    asyncio.run(rodar())
    assert textos.AVISO_SEM_COTACAO not in saidas
