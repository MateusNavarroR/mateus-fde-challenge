"""Os evals do Agno gravam mesmo em `ai.eval_runs`, e o painel lê o que eles gravam.

**Por que este arquivo existe.** Havia trinta testes verdes sobre `assercoes.py`, e
nenhum deles provava o que o repositório afirmava. Eles construíam os objetos e, num
punhado de casos, chamavam `.run()` sobre um `RunOutput` sintético — sempre com
`db=None`. Isso prova a mecânica de casamento de tool calls do Agno, que é código
deles. Não provava que o replay chamava aquilo, nem que algo chegava ao banco: a tabela
`ai.eval_runs` não existia, `_evals()` caía no `except` e o painel exibia um traço,
enquanto três documentos descreviam uma integração fim a fim.

Os testes daqui fecham as duas pontas que ninguém cobria: **a escrita** (a tabela
aparece, com o nome que o painel consulta) e **a leitura** (o número que o painel
mostra vem do que foi gravado). Marcados `db` porque exigem Postgres de verdade — é
justamente isso que estava faltando.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from qa.replay import evals

pytestmark = pytest.mark.db


@pytest.fixture
def db_evals(engine_teste):
    """`PostgresDb` no mesmo banco da suíte, com a tabela limpa entre testes.

    A tabela é criada pelo próprio Agno na primeira escrita, fora das nossas migrações
    — então o `DROP` aqui é seguro e devolve o banco ao estado de quem nunca avaliou,
    que é o estado em que o defeito vivia.
    """
    with engine_teste.begin() as c:
        c.execute(text("drop table if exists ai.eval_runs"))
    yield evals.db_de_evals(str(engine_teste.url.render_as_string(hide_password=False)))
    with engine_teste.begin() as c:
        c.execute(text("drop table if exists ai.eval_runs"))


class _Run:
    """O mínimo que o `ReliabilityEval` lê de um `RunOutput`: as tools executadas."""

    def __init__(self, *tools: str) -> None:
        # `agno.models.response`, e não `agno.tools.function`: é de lá que o
        # `ReliabilityEval` da 3.0.6 lê as execuções. O teste irmão em
        # `test_replay_assercoes.py` usa o mesmo import, e é o que vale.
        from agno.models.response import ToolExecution

        self.tools = [ToolExecution(tool_name=t, tool_args={}) for t in tools]
        self.messages = [
            _Msg([{"function": {"name": t, "arguments": "{}"}} for t in tools])
        ]


class _Msg:
    def __init__(self, tool_calls) -> None:  # noqa: ANN001
        self.role = "assistant"
        self.tool_calls = tool_calls
        self.from_history = False


def test_o_reliability_cria_a_tabela_com_o_NOME_que_o_painel_consulta(db_evals, engine_teste):
    """O nome da tabela não é o default do Agno — e o default falharia em silêncio.

    Sem `eval_table="eval_runs"` tudo parece funcionar: o eval roda, imprime um
    resultado correto e grava numa tabela de outro nome. O painel, que consulta
    `ai.eval_runs` literalmente, continuaria mostrando um traço para sempre. É o tipo
    de defeito que nenhum teste de unidade encontra, porque as duas metades estão
    certas separadamente.
    """
    registro = evals.Registro()
    caso, expectativa = _caso_com_tool_obrigatoria()
    evals.gravar_reliability(
        caso, expectativa, [_Run("quote_plan")], db=db_evals, registro=registro,
    )

    assert registro.erros == [], registro.erros
    assert registro.reliability_avaliados == 1

    with engine_teste.connect() as c:
        n = c.execute(text("select count(*) from ai.eval_runs")).scalar_one()
    assert n == 1, "o eval rodou e não deixou linha — é exatamente o defeito antigo"


def test_o_painel_le_o_QUE_o_eval_gravou(db_evals, engine_teste):
    """A ponte inteira: `gravar_reliability` escreve, `_evals()` conta.

    As duas pontas têm a string `eval_status` — uma no dataclass do Agno, outra na
    consulta SQL do painel. Elas ficam em arquivos diferentes e nada as obriga a
    concordar; este teste é o que as obriga. Se o Agno renomear a chave, aqui fica
    vermelho, em vez de o painel passar a mostrar zero para sempre.
    """
    from sqlalchemy.orm import Session

    from app.api.consultas import _evals

    registro = evals.Registro()
    caso, expectativa = _caso_com_tool_obrigatoria()
    evals.gravar_reliability(
        caso, expectativa, [_Run("quote_plan")], db=db_evals, registro=registro,
    )
    assert registro.reliability_passaram == 1, "a tool esperada foi chamada; devia passar"

    with Session(engine_teste) as s:
        lido = _evals(s)

    assert lido["total"] == 1
    assert lido["passaram"] == 1, (
        "o painel não reconheceu como PASSED o que o Agno gravou — a chave "
        "`eval_status` divergiu entre a escrita e a consulta"
    )


def test_uma_tool_obrigatoria_NAO_chamada_reprova_e_isso_tambem_e_gravado(
    db_evals, engine_teste
):
    """O negativo, sem o qual o positivo não significa nada.

    Um eval que só sabe dizer `PASSED` é um carimbo, não uma avaliação — e o painel
    passaria a exibir um número que sobe sozinho.
    """
    from sqlalchemy.orm import Session

    from app.api.consultas import _evals

    registro = evals.Registro()
    caso, expectativa = _caso_com_tool_obrigatoria()
    # O agente conversou e nunca cotou.
    evals.gravar_reliability(
        caso, expectativa, [_Run("qualify_lead")], db=db_evals, registro=registro,
    )

    assert registro.reliability_avaliados == 1
    assert registro.reliability_passaram == 0

    with Session(engine_teste) as s:
        lido = _evals(s)
    assert lido["total"] == 1 and lido["passaram"] == 0


def test_o_AGNO_ENGOLE_erro_de_escrita_e_a_conferencia_e_quem_acusa(engine_teste):
    """O achado que este arquivo trouxe, e ele mudou o desenho do `Registro`.

    Com o banco fora do ar, `ReliabilityEval.run()` **não levanta**: `log_eval_run`
    captura a exceção, emite `WARNING Could not log eval run` e devolve um resultado
    `PASSED` perfeito. Um contador incrementado no retorno afirmaria "1 gravado" sobre
    uma tabela que não existe — que é a versão nova do defeito antigo, com um número no
    lugar do traço.

    Por isso o relatório publica o que `conferir_gravacao()` lê do BANCO, e a
    divergência entre avaliado e gravado vira erro registrado.
    """
    from sqlalchemy import text as _sql

    with engine_teste.begin() as c:
        c.execute(_sql("drop table if exists ai.eval_runs"))

    registro = evals.Registro()
    caso, expectativa = _caso_com_tool_obrigatoria()

    class _DbQuebrado:
        def __getattr__(self, nome):  # noqa: ANN001
            raise RuntimeError("banco fora do ar")

    evals.gravar_reliability(
        caso, expectativa, [_Run("quote_plan")], db=_DbQuebrado(), registro=registro,
    )

    # O eval rodou e se diz bem-sucedido — este é o comportamento do Agno, não o nosso.
    assert registro.reliability_avaliados == 1
    assert registro.erros == []

    evals.conferir_gravacao(engine_teste, registro)

    assert registro.linhas_no_banco == 0
    assert len(registro.erros) == 1
    assert "engoliu erro de escrita" in registro.erros[0]


def test_uma_excecao_de_montagem_NAO_derruba_o_replay(db_evals):
    """Um replay custa horas; uma avaliação não pode trocar o dado por um traceback.

    Mas também não pode sumir: o erro vai para `registro.erros`, e o relatório o
    mostra. A diferença entre falha conhecida e falha engolida é essa lista.
    """
    registro = evals.Registro()
    caso, expectativa = _caso_com_tool_obrigatoria()

    class _RunImpossivel:
        @property
        def tools(self):
            raise RuntimeError("run corrompido")

    evals.gravar_reliability(
        caso, expectativa, [_RunImpossivel()], db=db_evals, registro=registro,
    )

    assert registro.reliability_avaliados == 0
    assert len(registro.erros) == 1
    assert "run corrompido" in registro.erros[0]


def test_sem_tool_obrigatoria_nao_grava_nada(db_evals, engine_teste):
    """Um `PASSED` sem expectativa é um número que sobe sem nada ter sido verificado.

    É o caso do handoff legítimo: nenhuma tool é obrigatória. `montar_reliability`
    devolve `None` ali, e a gravação precisa respeitar isso — senão o painel infla.
    """
    from qa.replay.assercoes import Expectativa

    registro = evals.Registro()
    caso, _ = _caso_com_tool_obrigatoria()
    from qa.replay.assercoes import Desfecho

    vazia = Expectativa(desfecho=Desfecho.ENCAMINHADO, tools_obrigatorias=())

    evals.gravar_reliability(caso, vazia, [_Run()], db=db_evals, registro=registro)

    assert registro.reliability_avaliados == 0
    assert registro.erros == []
    with engine_teste.connect() as c:
        existe = c.execute(text(
            "select to_regclass('ai.eval_runs') is not null"
        )).scalar_one()
    assert existe is False, "gravou uma linha para uma conversa sem expectativa"


def test_o_juiz_roda_uma_vez_por_MOTIVO_e_nao_por_conversa():
    """Três motivos, três chamadas — e o custo não cresce com o tamanho da amostra.

    O texto da recusa é nosso e vem de um mapa fixo: o modelo não escreve nada no turno
    de recusa. Avaliá-lo por conversa multiplicaria a conta por `n` sem produzir um bit
    de informação nova, porque a entrada seria byte a byte a mesma.

    Sem tocar em modelo nenhum: o juiz é substituído por um dublê que conta chamadas.
    """
    from app.contracts.quote import MotivoRecusa

    chamadas: list[str] = []

    class _JuizFalso:
        def run(self, *, input: str, output: str):  # noqa: A002
            chamadas.append(output)
            return type("R", (), {"eval_status": "PASSED"})()

    registro = evals.Registro()
    import qa.replay.assercoes as assercoes

    original = assercoes.montar_juiz_da_recusa
    assercoes.montar_juiz_da_recusa = lambda **_: _JuizFalso()  # type: ignore[assignment]
    try:
        evals.gravar_juiz_das_recusas(db=object(), registro=registro)
    finally:
        assercoes.montar_juiz_da_recusa = original  # type: ignore[assignment]

    assert len(chamadas) == len(MotivoRecusa) == 3
    assert len(set(chamadas)) == 3, "os três motivos têm textos distintos"
    assert registro.juiz_avaliados == 3 and registro.juiz_passaram == 3


def _caso_com_tool_obrigatoria():
    """Um caso mínimo cuja expectativa exige `quote_plan`."""
    from qa.replay.assercoes import Expectativa

    caso = type("Caso", (), {"conversation_id": "conv_teste_evals"})()
    from qa.replay.assercoes import Desfecho

    expectativa = Expectativa(
        desfecho=Desfecho.OK,
        tools_obrigatorias=("quote_plan",),
    )
    return caso, expectativa


def test_as_DUAS_classes_reportam_aprovacao_de_formas_diferentes():
    """O quarto tropeço da mesma família, e o mais silencioso: não quebra nada.

    `ReliabilityResult` tem `eval_status`; `AgentAsJudgeResult` tem `pass_rate` e uma
    lista `results` com `passed` por caso. Assumir simetria fazia o contador dizer
    "0 passaram" sobre um julgamento que aprovou com nota 9 — medido no replay:
    `pass_rate: 100.0` gravado no banco, `juiz_passaram: 0` no relatório.
    """
    reliability = type("R", (), {"eval_status": "PASSED"})()
    juiz_ok = type("J", (), {"pass_rate": 100.0})()
    juiz_ruim = type("J", (), {"pass_rate": 0.0})()
    juiz_parcial = type("J", (), {"pass_rate": 66.7})()

    assert evals._passou(reliability)
    assert evals._passou(juiz_ok)
    assert not evals._passou(juiz_ruim)
    assert not evals._passou(juiz_parcial)

    # `eval_status` vence quando existe, e um resultado sem NENHUM dos dois campos é
    # reprovado — nunca aprovado por omissão.
    assert not evals._passou(type("R", (), {"eval_status": "FAILED", "pass_rate": 100.0})())
    assert not evals._passou(object())


def test_o_juiz_recebe_o_CASO_descrito_e_nao_o_nome_do_enum():
    """Um juiz de modelo mede o que você lhe dá.

    A primeira versão passava `idade_acima_do_limite` cru como entrada, e o juiz
    reprovou o texto de recusa por causa disso — com razão. O nome é ambíguo (idade
    de quem: do condutor ou do veículo?), e ele penalizou a mensagem por "assumir que
    se trata do condutor sem indicação clara". A crítica era do INSTRUMENTO, não do
    texto.

    Reprovação mal fundamentada é pior que nenhuma: manda consertar o que estava certo.
    """
    from app.contracts.quote import MotivoRecusa

    for motivo in MotivoRecusa:
        caso = evals._caso_do_motivo(motivo)
        assert str(motivo) not in caso, (
            f"o nome do enum vazou para a entrada do juiz: {caso!r}"
        )
        assert len(caso) > 40, f"caso curto demais para julgar: {caso!r}"

    # E a ambiguidade que causou a reprovação está resolvida NOS DOIS sentidos: cada
    # caso diz de quem é a idade, e diz que o outro lado não é o problema.
    assert "CONDUTOR" in evals._caso_do_motivo(MotivoRecusa.IDADE_ACIMA)
    assert "VEÍCULO" in evals._caso_do_motivo(MotivoRecusa.VEICULO_ANTIGO)
