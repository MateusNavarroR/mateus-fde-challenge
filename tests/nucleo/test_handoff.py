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


# ─── o gatilho tem que ser alcançável PELO CAMINHO DE PRODUÇÃO ───────────────
#
# Este bloco existe por causa de um bug real: `MIDIA_SEM_TEXTO` passava em
# `test_um_teste_por_gatilho` e era **inalcançável em produção**. O teste chamava
# `casa()` com um `Contexto` montado à mão; `_encaminhar` montava o dele sem
# `tipo_da_mensagem` nem `midias_apos_pedido`, e o gatilho nunca podia disparar.
#
# A unidade estava provada. A fiação, não. É a mesma cegueira que deixou passar o
# `external_ref` fixo e o stub no lugar do agente — nenhum apareceu em teste, todos
# apareceram usando.


def test_todo_campo_que_um_gatilho_le_e_preenchido_por_encaminhar():
    """O teste estrutural que fecha a CLASSE do bug, não só o caso.

    Ele lê o código: os campos de `Contexto` que `casa()` consulta têm que ser os
    mesmos que `_encaminhar` atribui. Acrescentar um campo novo a um gatilho e
    esquecer de ligá-lo no turno reprova aqui, mesmo com o teste de unidade verde.
    """
    import ast
    import inspect

    from app.agent import turno

    lidos = {
        n.attr
        for n in ast.walk(ast.parse(inspect.getsource(gatilhos.casa)))
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "c"
    }

    chamada = next(
        n
        for n in ast.walk(ast.parse(inspect.getsource(turno._encaminhar)))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "Contexto"
    )
    preenchidos = {kw.arg for kw in chamada.keywords}

    assert lidos <= preenchidos, (
        f"gatilho(s) inalcançáveis em produção: `casa()` lê {sorted(lidos - preenchidos)}, "
        "e `_encaminhar` não preenche. O teste de unidade continua verde e o gatilho "
        "nunca dispara."
    )


async def test_a_segunda_midia_encaminha_de_verdade(sessao, conversa, monkeypatch):
    """O caso concreto, ponta a ponta: duas mídias entram pelo canal e sai um handoff.

    A primeira mídia **não** encaminha — o agente pede texto uma vez. É a segunda,
    a insistência, que custa mais responder errado do que passar adiante.
    """
    from app.agent import runner, turno

    class AgenteMudo:
        def run(self, _texto):
            return type("R", (), {"content": "Consegue me mandar por texto?"})()

    monkeypatch.setattr(turno, "construir_agente", lambda _ctx: AgenteMudo())

    class Canal:
        name = "web"

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

    def pendentes() -> list[str]:
        return [
            h.trigger
            for h in sessao.query(Handoff).filter_by(conversation_id=conversa.id).all()
        ]

    await runner.processar_turno_web(conversa.id, "audio-1.ogg", Canal(), tipo="audio")
    sessao.commit()
    assert pendentes() == [], "a primeira mídia não encaminha: o agente pede texto"

    await runner.processar_turno_web(conversa.id, "audio-2.ogg", Canal(), tipo="audio")
    sessao.commit()
    assert HandoffTrigger.MIDIA_SEM_TEXTO.value in pendentes()


async def test_texto_depois_de_uma_midia_nao_encaminha(sessao, conversa, monkeypatch):
    """O negativo que dá sentido ao positivo.

    Sem ele, um `casa()` que ignorasse `tipo_da_mensagem` passaria no teste acima —
    e todo lead que mandasse um áudio e depois escrevesse cairia na fila.
    """
    from app.agent import runner, turno

    class AgenteMudo:
        def run(self, _texto):
            return type("R", (), {"content": "Perfeito, obrigado."})()

    monkeypatch.setattr(turno, "construir_agente", lambda _ctx: AgenteMudo())

    class Canal:
        name = "web"

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

    await runner.processar_turno_web(conversa.id, "foto.jpg", Canal(), tipo="image")
    await runner.processar_turno_web(conversa.id, "tenho 30 anos", Canal())
    sessao.commit()

    assert sessao.query(Handoff).filter_by(conversation_id=conversa.id).count() == 0


async def test_a_segunda_violacao_de_guardrail_encaminha(sessao, conversa, monkeypatch):
    """O outro gatilho que o teste estrutural revelou inalcançável.

    O modelo escreve um valor monetário — o que só o renderizador pode fazer. A
    primeira vez a mensagem é descartada e o descarte fica gravado; a segunda
    encaminha, porque um modelo que escorrega duas vezes na mesma conversa não é
    ruído, é padrão.
    """
    from app.agent import runner, turno
    from app.persistence.models import Message

    class AgenteQueEscorrega:
        def run(self, _texto):
            return type("R", (), {"content": "Fica R$ 289,90 por mês."})()

    monkeypatch.setattr(turno, "construir_agente", lambda _ctx: AgenteQueEscorrega())

    class Canal:
        name = "web"

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

    await runner.processar_turno_web(conversa.id, "quanto fica?", Canal())
    sessao.commit()
    descartadas = sessao.query(Message).filter_by(
        conversation_id=conversa.id, status="discarded"
    ).all()
    assert len(descartadas) == 1, "o descarte tem que deixar rastro, não virar log"
    # O conteúdo barrado é a evidência: sem ele o operador não sabe o que o modelo
    # tentou dizer, e o descarte vira um número sem história.
    assert "289,90" in descartadas[0].conteudo
    assert sessao.query(Handoff).filter_by(conversation_id=conversa.id).count() == 0

    await runner.processar_turno_web(conversa.id, "e então?", Canal())
    sessao.commit()
    assert [
        h.trigger for h in sessao.query(Handoff).filter_by(conversation_id=conversa.id)
    ] == [HandoffTrigger.GUARDRAIL.value]


# ─── a fronteira entre o que o modelo decide e o que a regra conta ───────────


def test_o_modelo_so_pode_pedir_os_dois_gatilhos_de_julgamento(sessao, conversa):
    """Medido no navegador: com `midia_sem_texto` no menu da tool, o modelo
    encaminhou na PRIMEIRA foto — contra a política de tentar uma vez.

    A causa não é o prompt, é o menu. Um gatilho de contagem oferecido ao modelo é
    escolhido pela impressão do turno isolado, que é exatamente o que a contagem
    existe para não seguir. Por isso a recusa é mecanismo, como o guardrail.
    """
    from app.agent.tools import ContextoDoTurno, make_escalate_to_human

    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
    escalar = make_escalate_to_human(ctx)

    for aceito in ("assunto_sensivel", "lead_pediu_atendente"):
        resposta = escalar(trigger=aceito, reason="motivo")
        assert "encaminhado" in resposta
    assert len(ctx.handoffs) == 2

    for recusado in ("midia_sem_texto", "objecao_fora_da_alcada", "extracao_falhou",
                     "guardrail", "cotacao_indisponivel"):
        resposta = escalar(trigger=recusado, reason="motivo")
        assert "não é seu para decidir" in resposta, recusado
    assert len(ctx.handoffs) == 2, "gatilho de contagem não pode entrar por write-back"


def test_a_fronteira_cobre_todos_os_sete_gatilhos():
    """Se alguém acrescentar um gatilho ao enum, ele cai de um lado ou do outro — não
    fica num limbo em que a tool aceita sem que ninguém tenha decidido."""
    from app.agent.tools import _DO_MODELO

    assert _DO_MODELO < {str(t) for t in HandoffTrigger}
    contados = {str(t) for t in HandoffTrigger} - _DO_MODELO
    assert len(contados) == 5


# ─── `extracao_falhou` conta ao longo da CONVERSA, e conta uma vez ───────────


def test_uma_falha_de_extracao_nao_encaminha(sessao, conversa):
    """Medido gerando o transcript: o gatilho disparava na PRIMEIRA falha.

    Duas causas somadas — o incremento estava duplicado, e o contador nunca era
    persistido. O efeito é o pior possível para o critério nº 3: um lead cujo campo o
    modelo mandou torto ia para a fila humana na hora, sem nunca ser reperguntado.
    Encaminhar por bug nosso é o caso que CLAUDE.md 9 nomeia.
    """
    from app.agent.tools import ContextoDoTurno, make_qualify_lead
    from app.persistence import repo as _repo

    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
    qualificar = make_qualify_lead(ctx)

    qualificar(data_inicio="dia de são nunca")
    sessao.commit()

    assert _repo.tentativas_de_extracao(sessao, conversa.id) == {"data_inicio": 1}
    assert not gatilhos.casa(
        HandoffTrigger.EXTRACAO_FALHOU,
        Contexto(tentativas_extracao=_repo.tentativas_de_extracao(sessao, conversa.id)),
    )


def test_a_contagem_de_extracao_atravessa_turnos(sessao, conversa):
    """A regra diz "2ª falha no MESMO campo", sem dizer "no mesmo turno".

    Antes, `tentativas_extracao` vivia no envelope do turno e `_perfil_de()` a
    descartava ao reconstruir o perfil das colunas — então a contagem reiniciava a
    cada mensagem e a segunda falha só podia acontecer dentro de um turno só, que é o
    modelo se atrapalhando, e não o lead sendo ilegível.
    """
    from app.agent.tools import ContextoDoTurno, make_qualify_lead
    from app.persistence import repo as _repo

    for _ in range(2):
        # Um ContextoDoTurno NOVO a cada volta: é o que o turno faz de verdade.
        ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
        make_qualify_lead(ctx)(data_inicio="quando der")
        sessao.commit()

    contagem = _repo.tentativas_de_extracao(sessao, conversa.id)
    assert contagem == {"data_inicio": 2}
    assert gatilhos.casa(HandoffTrigger.EXTRACAO_FALHOU,
                         Contexto(tentativas_extracao=contagem))


def test_falhas_em_campos_diferentes_nao_somam(sessao, conversa):
    """O negativo que dá sentido ao positivo: a contagem é POR CAMPO.

    Errar uma vez a data e uma vez o CEP não é "falhou duas vezes" — são dois campos
    para reperguntar, e reperguntar é barato.
    """
    from app.agent.tools import ContextoDoTurno, make_qualify_lead
    from app.persistence import repo as _repo

    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
    make_qualify_lead(ctx)(data_inicio="sei lá", plano_id="turbo")
    sessao.commit()

    contagem = _repo.tentativas_de_extracao(sessao, conversa.id)
    assert sorted(contagem) == ["data_inicio", "plano_id"]
    assert all(n == 1 for n in contagem.values())
    assert not gatilhos.casa(HandoffTrigger.EXTRACAO_FALHOU,
                             Contexto(tentativas_extracao=contagem))


def test_indisponibilidade_nao_repete_a_despedida(sessao, conversa, monkeypatch):
    """`compor_handoff("cotacao_indisponivel")` já TERMINA com a despedida.

    `_encaminhar` mandava `DESPEDIDA` de novo, e o lead lia a mesma frase, palavra
    por palavra, em duas mensagens seguidas. Visível no transcript do cenário
    degradado — e invisível na suíte, porque nenhum teste comparava as mensagens
    entre si.
    """
    from app.agent import turno
    from app.agent.tools import ContextoDoTurno

    enviadas: list[str] = []

    async def enviar_async(texto, autor="sistema"):
        enviadas.append(texto)

    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
    ctx.handoffs.append({
        "trigger": HandoffTrigger.COTACAO_INDISPONIVEL,
        "reason": "a cotação não respondeu", "quote_id": None,
        "disparado_por": "regra", "assunto": None,
    })

    import asyncio
    asyncio.run(turno._encaminhar(sessao, conversa.id, ctx, "e aí?", enviar_async))

    assert enviadas == [], (
        "a mensagem de indisponibilidade sai de dentro da tool; `_encaminhar` não "
        f"pode mandar nada por cima. Mandou: {enviadas}"
    )
    assert textos.DESPEDIDA in textos.compor_handoff("cotacao_indisponivel")


def test_uma_cotacao_por_turno(sessao, conversa, monkeypatch):
    """O modelo chamou `quote_plan` duas vezes no mesmo turno, gerando o transcript.

    O estrago tem três partes: dois jobs contra a `/quote`, dois avisos de espera
    idênticos em sequência para o lead, e uma linha em `quotes` que ficou `pending`
    para sempre — rastro inconsistente na tabela que responde pelo critério nº 4.
    """
    from app.agent.tools import ContextoDoTurno, make_quote_plan

    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id)
    ctx.quote_do_turno = "q_ja_existe"

    resposta = make_quote_plan(ctx)(
        plano_id="completo", idade=30, veiculo_ano=2020,
    )
    assert "já cotado neste turno" in resposta
    assert "q_ja_existe" in resposta


# ─── o custo do turno sobrevive ao fim do turno ──────────────────────────────


async def test_turno_em_que_a_tool_responde_grava_o_custo(sessao, conversa, monkeypatch):
    """Achado na vistoria: uma conversa de 2 turnos tinha 1 linha em `turn_usage`, e
    a que faltava era a do turno da COTAÇÃO.

    `gravar_turn_usage` faz `flush`, não `commit`. O caminho `ja_enviou → return`
    saía da sessão sem commitar e o rollback levava a linha junto. O turno sem tool
    sobrevivia só porque `enviar_async` commitava depois, por acidente.

    Um teste de `gravar_turn_usage` isolado passaria com o bug presente: ele grava
    certo. Quem perdia era o TURNO. Por isso a asserção é depois de `responder`, com
    sessão nova — que é o que prova que a linha atravessou o commit.
    """
    from app.agent import runner, turno
    from app.persistence.db import sessao_factory
    from app.persistence.models import TurnUsage

    class Metrics:
        input_tokens, output_tokens = 1234, 567
        cache_read_tokens, cache_write_tokens = 890, 0
        duration = 1.5

    class AgenteComTool:
        """Imita o turno de cotação: a tool fala com o lead e o texto do modelo é
        descartado — que é o caminho em que a linha sumia."""

        def run(self, _texto):
            ctx.ja_enviou = True
            return type("R", (), {"content": "texto que será descartado",
                                  "metrics": Metrics()})()

    ctx = None
    original = turno.ContextoDoTurno if hasattr(turno, "ContextoDoTurno") else None

    def construir(c):
        nonlocal ctx
        ctx = c
        return AgenteComTool()

    monkeypatch.setattr(turno, "construir_agente", construir)

    class Canal:
        name = "web"

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

    await runner.processar_turno_web(conversa.id, "quanto fica?", Canal())

    # Sessão NOVA: é ela que distingue "flushado" de "commitado".
    with sessao_factory()() as outra:
        linhas = outra.query(TurnUsage).filter_by(conversation_id=conversa.id).all()

    assert len(linhas) == 1, (
        "o turno em que a tool respondeu não gravou custo — é o turno com tool "
        "call, o mais caro, e o painel o perdia"
    )
    assert linhas[0].tokens_in == 1234
    assert linhas[0].cache_read == 890


async def test_turno_sem_mensagem_ainda_grava_o_custo(sessao, conversa, monkeypatch):
    """Nem todo turno produz mensagem, e ele custa tokens igual.

    Depois de a cotação sair pela tool, o texto do modelo é descartado; se o lead
    escrever de novo, o turno roda, consome contexto e não escreve em `messages`.
    `gravar_turn_usage` ancorava na ÚLTIMA mensagem — a do turno anterior — e batia no
    UNIQUE de `turn_usage.message_id`, derrubando a transação inteira.

    Isso vinha acontecendo em silêncio: sem o commit, o `flush` voltava atrás no
    rollback e o custo sumia. O replay do dataset foi onde apareceu, quebrando aos
    15/30. A âncora agora é nula nesse turno, em vez de mentir ou de sumir.
    """
    from app.agent import turno
    from app.persistence.db import sessao_factory
    from app.persistence.models import TurnUsage

    class Metrics:
        input_tokens, output_tokens = 100, 20
        cache_read_tokens, cache_write_tokens = 50, 0
        duration = 1.0

    # O PRIMEIRO turno fala (e cria a âncora); o segundo roda e não escreve. Se os
    # dois fossem mudos, a conversa não teria mensagem nenhuma, a âncora seria nula
    # nos dois casos e o teste passaria com o defeito presente — foi assim que ele
    # nasceu, e a mutação o pegou.
    falas = iter(["Boa, me passa o ano do carro?", ""])

    class AgenteQueEmudece:
        def run(self, _texto):
            return type("R", (), {"content": next(falas), "metrics": Metrics()})()

    monkeypatch.setattr(turno, "construir_agente", lambda _c: AgenteQueEmudece())

    class Canal:
        name = "web"

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

    # `responder` DIRETO, sem `processar_turno_web`. É o caminho do replay, e é o que
    # expõe o defeito: `processar_turno_web` persiste a fala do lead a cada turno,
    # então a âncora muda sozinha e o conflito nunca aparece. O replay injeta a fala
    # sem gravá-la — a última mensagem continua sendo a mesma entre os turnos.
    await turno.responder(conversa.id, "oi", Canal())
    await turno.responder(conversa.id, "e aí?", Canal())

    with sessao_factory()() as outra:
        linhas = outra.query(TurnUsage).filter_by(conversation_id=conversa.id).all()

    assert len(linhas) == 2, (
        "os dois turnos custaram e os dois têm de aparecer — antes, o segundo "
        "derrubava a transação no UNIQUE e o replay morria aos 15/30"
    )
    ancoras = [l.message_id for l in linhas]
    assert None in ancoras, (
        "o turno que não produziu mensagem tem de gravar com âncora NULA — apontar "
        "para a mensagem de outro turno é mentira, e omitir subestima a conta"
    )


async def test_a_ancora_do_custo_e_a_mensagem_QUE_O_TURNO_PRODUZIU(
    sessao, conversa, monkeypatch
):
    """A coluna promete "a mensagem que este turno produziu". Ela entregava outra.

    `_gravar_uso` rodava ANTES do envio, então a âncora era a mensagem do turno
    ANTERIOR — a deste ainda não existia. No primeiro turno de uma conversa isso dava
    âncora nula; do segundo em diante, apontava para a mensagem errada. E dois turnos
    seguidos sem mensagem nova apontavam para a MESMA, colidindo no índice único.
    """
    from app.agent import turno
    from app.persistence import repo as _repo
    from app.persistence.db import sessao_factory
    from app.persistence.models import TurnUsage

    class Metrics:
        input_tokens, output_tokens = 10, 5
        cache_read_tokens, cache_write_tokens = 0, 0
        duration = 0.1

    falas = iter(["primeira resposta", "segunda resposta"])

    class Falante:
        def run(self, _texto):
            return type("R", (), {"content": next(falas), "metrics": Metrics()})()

    monkeypatch.setattr(turno, "construir_agente", lambda _c: Falante())

    class Canal:
        name = "web"

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

    await turno.responder(conversa.id, "oi", Canal())
    await turno.responder(conversa.id, "de novo", Canal())

    with sessao_factory()() as outra:
        linhas = (outra.query(TurnUsage)
                  .filter_by(conversation_id=conversa.id)
                  .order_by(TurnUsage.criado_em).all())
        msgs = _repo.mensagens(outra, conversa.id)

        assert len(linhas) == 2 and len(msgs) == 2
        # Cada turno ancorado na SUA mensagem, na ordem — nenhuma âncora nula e
        # nenhuma repetida.
        assert [l.message_id for l in linhas] == [m.id for m in msgs], (
            "o custo do turno tem de apontar para a mensagem que ELE produziu"
        )


# ─── o turno que "deu certo" e não deu ──────────────────────────────────────


async def test_erro_do_provider_NAO_chega_ao_lead(sessao, conversa, monkeypatch):
    """O Agno **não levanta** quando a chamada ao provider falha: devolve um
    `RunOutput` com `status=ERROR` e o texto do erro em `content`.

    O `except` em volta de `agente.run` nunca dispara, e a mensagem seguia o caminho
    normal — persistida como fala do `agente` e entregue ao lead. O guardrail não pega:
    não há valor monetário no texto.

    Medido no replay: a conta ficou sem crédito no meio da execução, e 14 conversas
    gravaram «Error code: 400 … Your credit balance is too low …» como resposta do
    agente. Um lead lendo a mensagem de cobrança da nossa conta é o pior desfecho
    possível de uma falha de infraestrutura — pior que silêncio, porque expõe a
    operação.
    """
    from app import textos
    from app.agent import turno

    ERRO = ("Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': 'Your credit balance is too low to "
            "access the Anthropic API.'}}")

    class RunComErro:
        content = ERRO
        status = "ERROR"
        metrics = None

    monkeypatch.setattr(
        turno, "construir_agente",
        lambda _c: type("A", (), {"run": lambda self, t: RunComErro()})(),
    )

    saiu: list[str] = []

    class Canal:
        name = "web"

        async def send(self, conversation_id, text, *, message_id, **kw):
            saiu.append(text)
            return "x"

        async def typing(self, *a, **kw):
            return None

    await turno.responder(conversa.id, "oi", Canal())

    assert saiu == [textos.FALHA_TECNICA], f"o que saiu: {saiu}"
    assert not any("Error code" in t for t in saiu)
    assert not any("credit balance" in t for t in saiu)


async def test_run_bem_sucedido_continua_entregando_o_texto(sessao, conversa, monkeypatch):
    """O negativo: barrar por `status` errado calaria o agente em todo turno."""
    from app.agent import turno

    class RunOk:
        content = "Boa! Me passa o ano do carro?"
        status = "COMPLETED"
        metrics = None

    monkeypatch.setattr(
        turno, "construir_agente",
        lambda _c: type("A", (), {"run": lambda self, t: RunOk()})(),
    )

    saiu: list[str] = []

    class Canal:
        name = "web"

        async def send(self, conversation_id, text, *, message_id, **kw):
            saiu.append(text)
            return "x"

        async def typing(self, *a, **kw):
            return None

    await turno.responder(conversa.id, "oi", Canal())
    assert saiu == ["Boa! Me passa o ano do carro?"]


@pytest.mark.anyio
async def test_o_handoff_AVISA_A_TELA_que_a_conversa_fechou(sessao, conversa, monkeypatch):
    """A cadeia existia inteira e não estava ligada — este teste é o que a liga.

    `gatilhos.registrar` marca `state = "encaminhado"`, que é terminal: o agente para
    de responder. O cliente sabia tratar isso (o reducer tem `entradaBloqueada`, a tela
    tem a faixa de conversa encerrada, o adaptador tem o método `estado()`) e **nada
    nunca chamava `estado()`**. Na prática, o lead ficava com o campo liberado numa
    conversa que já não responde, digitando no vazio.

    O teste assere sobre o CANAL, e não sobre o banco: o banco já estava certo antes,
    e é justamente por isso que o defeito passou despercebido.
    """
    from app.agent import runner, turno

    class AgenteMudo:
        def run(self, _texto):
            return type("R", (), {"content": "ok"})()

    monkeypatch.setattr(turno, "construir_agente", lambda _ctx: AgenteMudo())

    class CanalQueAnota:
        name = "web"

        def __init__(self) -> None:
            self.estados: list[str] = []

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

        async def estado(self, state: str) -> None:
            self.estados.append(state)

    canal = CanalQueAnota()
    await runner.processar_turno_web(
        conversa.id, "quero falar com um atendente", canal,
    )
    sessao.commit()

    assert canal.estados == ["encaminhado"], (
        "o handoff foi gravado e a tela não foi avisada — é o defeito que deixava o "
        "compositor liberado numa conversa encerrada"
    )


@pytest.mark.anyio
async def test_um_turno_COMUM_nao_anuncia_estado_nenhum(sessao, conversa, monkeypatch):
    """O negativo: sem ele, bastaria emitir `"encaminhado"` em todo turno para passar."""
    from app.agent import runner, turno

    class AgenteMudo:
        def run(self, _texto):
            return type("R", (), {"content": "qual a sua idade?"})()

    monkeypatch.setattr(turno, "construir_agente", lambda _ctx: AgenteMudo())

    class CanalQueAnota:
        name = "web"

        def __init__(self) -> None:
            self.estados: list[str] = []

        async def send(self, *a, **kw):
            return "x"

        async def typing(self, *a, **kw):
            return None

        async def estado(self, state: str) -> None:
            self.estados.append(state)

    canal = CanalQueAnota()
    await runner.processar_turno_web(conversa.id, "oi, tudo bem?", canal)
    sessao.commit()

    assert canal.estados == []
