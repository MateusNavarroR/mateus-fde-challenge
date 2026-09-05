"""Rate limit, HTTP 402 e o laço do executor — testados sem banco e sem modelo.

**Um replay que morre na conversa 18 e não diz que morreu é pior que um replay que não
roda.** Este arquivo é o que torna essa frase verificável: ele monta um agente falso que
levanta as exceções reais dos provedores, roda o laço do executor com um relógio que não
dorme, e confere que o relatório sai — com o número de conversas completadas, o número
de falhadas e o motivo de cada uma.

O caminho exercitado é o de verdade em tudo que importa para a resiliência: a costura de
`captura.py`, a detecção por delta no coletor (necessária porque `turno.responder`
captura `Exception` de forma ampla e a falha nunca chega ao executor como exceção), a
política de retentativa por classe e a parada no 402.
"""

from __future__ import annotations

import asyncio

import pytest

from qa.replay import executor as exec_mod
from qa.replay.assercoes import Desfecho
from qa.replay.captura import Coletor, capturando, instrumentar
from qa.replay.casos import CasoReplay, Fala, Gabarito
from tests.fixtures.pii import cep_de
from qa.dataset.elegibilidade import Elegibilidade
from qa.replay.falhas import Backoff, ClasseDeFalha, classificar, de_excecao
from qa.replay import amostra as amostragem


# ─────────────────────────────────────────────────────────────────────────────
# Classificação
# ─────────────────────────────────────────────────────────────────────────────


class ErroDeProvedor(Exception):
    """Imita o formato dos SDKs: `status_code` como atributo."""

    def __init__(self, mensagem: str, status_code: int | None = None):
        super().__init__(mensagem)
        self.status_code = status_code


@pytest.mark.parametrize(
    "erro,esperado",
    [
        (ErroDeProvedor("nope", 402), ClasseDeFalha.PAGAMENTO),
        (ErroDeProvedor("nope", 429), ClasseDeFalha.RATE_LIMIT),
        (ErroDeProvedor("nope", 503), ClasseDeFalha.INDISPONIVEL),
        (ErroDeProvedor("nope", 400), ClasseDeFalha.OUTRA),
    ],
)
def test_classifica_pelo_status_quando_ele_existe(erro, esperado):
    assert classificar(erro) is esperado


@pytest.mark.parametrize(
    "mensagem,esperado",
    [
        # A forma exata que o free tier do Ollama Cloud devolve em três dos quatro
        # modelos — e o motivo de o 402 existir como classe própria.
        ("402 Payment Required", ClasseDeFalha.PAGAMENTO),
        ("insufficient credit for this model", ClasseDeFalha.PAGAMENTO),
        ("429 Too Many Requests", ClasseDeFalha.RATE_LIMIT),
        ("rate limit exceeded, retry later", ClasseDeFalha.RATE_LIMIT),
        ("upstream 503 service unavailable", ClasseDeFalha.INDISPONIVEL),
        ("Read timed out", ClasseDeFalha.INDISPONIVEL),
        ("something else entirely", ClasseDeFalha.OUTRA),
    ],
)
def test_classifica_pelo_texto_quando_nao_ha_status(mensagem, esperado):
    """O erro atravessa o SDK do provedor e o wrapper do Agno, e cada um embrulha de um
    jeito. Casar por tipo exigiria importar exceções de três bibliotecas e manter-se em
    dia com as três."""
    assert classificar(RuntimeError(mensagem)) is esperado


def test_classifica_atraves_da_cadeia_de_causas():
    """O Agno embrulha a exceção do SDK: o "402" fica um nível abaixo."""
    try:
        try:
            raise ErroDeProvedor("Payment Required", 402)
        except ErroDeProvedor as origem:
            raise RuntimeError("model run failed") from origem
    except RuntimeError as e:
        assert classificar(e) is ClasseDeFalha.PAGAMENTO


def test_so_o_402_e_fatal():
    """429 melhora com espera; 402 não. Insistir num 402 só produz mais 402."""
    assert de_excecao(ErroDeProvedor("x", 402)).fatal
    assert not de_excecao(ErroDeProvedor("x", 429)).fatal
    assert not de_excecao(ErroDeProvedor("x", 503)).fatal


def test_mensagem_da_falha_e_truncada():
    """Sem traceback e sem corpo de resposta inteiro: os dois podem ecoar o prompt."""
    falha = de_excecao(RuntimeError("x" * 5000), limite=120)
    assert len(falha.mensagem) == 120


# ─────────────────────────────────────────────────────────────────────────────
# Backoff
# ─────────────────────────────────────────────────────────────────────────────


def test_backoff_cresce_e_respeita_o_teto():
    dormidas: list[float] = []
    b = Backoff(base_s=2.0, teto_s=10.0, seed=1, dormir=dormidas.append)
    for tentativa in range(1, 8):
        b.esperar(tentativa)
    assert dormidas[0] < dormidas[2]
    assert max(dormidas) <= 10.0
    assert b.esperado_s == pytest.approx(sum(dormidas))


def test_backoff_e_reproduzivel():
    """Um jitter não reprodutível tornaria dois relatórios incomparáveis por um motivo
    que não tem nada a ver com o agente."""
    a = Backoff(seed=7, dormir=lambda _: None)
    b = Backoff(seed=7, dormir=lambda _: None)
    assert [a.espera(i) for i in range(1, 5)] == [b.espera(i) for i in range(1, 5)]


# ─────────────────────────────────────────────────────────────────────────────
# A costura de captura
# ─────────────────────────────────────────────────────────────────────────────


class RunFalso:
    """O mínimo que `ReliabilityEval` e o coletor leem de um `RunOutput`."""

    def __init__(self, tools=()):
        self.content = "ok"
        self.messages = [
            type("Msg", (), {"tool_calls": [
                {"function": {"name": nome, "arguments": args}} for nome, args in tools
            ]})()
        ]


class AgenteFalso:
    """Roteiro por turno: uma exceção ou um `RunFalso`."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.chamadas = 0

    def run(self, texto, **kwargs):
        self.chamadas += 1
        passo = self.roteiro.pop(0) if self.roteiro else RunFalso()
        if isinstance(passo, BaseException):
            raise passo
        return passo


def test_a_captura_registra_o_run_e_relanca_a_excecao():
    """Relançar importa: engolir a exceção aqui faria a falha chegar ao relatório como
    "conversa normal que respondeu estranho"."""
    coletor = Coletor()
    agente = instrumentar(AgenteFalso([RunFalso(), ErroDeProvedor("x", 402)]), coletor)
    agente.run("oi")
    with pytest.raises(ErroDeProvedor):
        agente.run("de novo")
    assert len(coletor.runs) == 1
    assert coletor.falhas[-1].classe is ClasseDeFalha.PAGAMENTO


def test_a_captura_le_nomes_e_argumentos_das_tools():
    coletor = Coletor()
    agente = instrumentar(
        AgenteFalso([RunFalso(tools=[
            ("qualify_lead", '{"idade": 35}'),
            ("quote_plan", '{"plano_id": "completo", "idade": 35, "veiculo_ano": 2018}'),
        ])]),
        coletor,
    )
    agente.run("oi")
    assert coletor.chamadas_de_tool() == ["qualify_lead", "quote_plan"]
    assert coletor.argumentos_de("quote_plan")[0]["veiculo_ano"] == 2018


def test_argumento_ilegivel_nao_derruba_o_coletor():
    """O modelo às vezes emite JSON quebrado. Estourar aqui perderia a conversa inteira
    por causa de uma vírgula."""
    coletor = Coletor()
    agente = instrumentar(AgenteFalso([RunFalso(tools=[("quote_plan", "{isso nao e json")])]), coletor)
    agente.run("oi")
    assert coletor.argumentos_de("quote_plan") == [{}]


def test_a_costura_e_desfeita_mesmo_quando_o_corpo_levanta():
    """Deixar a costura instalada depois de uma falha faria o próximo teste da mesma
    sessão medir o coletor errado — o tipo de defeito que só aparece na ordem de
    execução."""
    from app.agent import turno

    original = turno.construir_agente
    with pytest.raises(ValueError):
        with capturando(Coletor()):
            raise ValueError("boom")
    assert turno.construir_agente is original


# ─────────────────────────────────────────────────────────────────────────────
# O laço do executor
# ─────────────────────────────────────────────────────────────────────────────


def _caso(cid="c1", falas=3, cotavel=True):
    from app.contracts.quote import MotivoRecusa

    return CasoReplay(
        conversation_id=cid,
        outcome="ganho",
        falas=tuple(Fala(i, "text", f"fala {i}") for i in range(falas)),
        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep=cep_de("01", com_hifen=False)),
        elegibilidade=Elegibilidade(
            cotavel=cotavel, por_idade=not cotavel, por_veiculo=False,
            motivo=None if cotavel else MotivoRecusa.IDADE_ACIMA,
            ano_veiculo=2018, idade_veiculo=8,
        ),
    )


class SessaoFalsa:
    """O executor só precisa que a sessão exista e feche. Quem lê o banco é `observar`,
    que os testes deste bloco substituem."""

    def commit(self): ...
    def close(self): ...
    def expire_all(self): ...


def _montar_executor(monkeypatch, roteiro, *, observacao=None, **kwargs):
    """Um executor cujo `responder` imita o de produção no que importa aqui.

    Ele constrói o agente pelo módulo `turno` — que é o que `capturando` embrulha — e
    **captura a exceção**, como o `responder` real faz. É exatamente essa captura que
    obriga o executor a detectar a falha por delta no coletor.
    """
    from app.agent import turno

    agente = AgenteFalso(roteiro)
    recebidas: list[tuple[str, str]] = []
    monkeypatch.setattr(turno, "construir_agente", lambda ctx: agente)

    async def responder_falso(cid, texto, adaptador, chegada_do_lead=None, tipo="text"):
        # Registrado para que um teste possa afirmar o que CHEGOU ao agente, e não só
        # o que o executor achou que mandou.
        recebidas.append((texto, tipo))
        construido = turno.construir_agente(None)
        try:
            construido.run(texto)
        except Exception:  # noqa: BLE001 - é o que o `responder` de produção faz
            pass
        await adaptador.send(cid, "e qual plano você prefere?", message_id="m")

    monkeypatch.setattr(
        exec_mod, "observar",
        lambda sessao, cid: observacao or exec_mod.Observacao(desfecho=Desfecho.OK),
    )
    import app.persistence.repo as repo

    monkeypatch.setattr(
        repo, "criar_conversa",
        lambda s, **kw: type("C", (), {"id": "conv_x", "state": "cotado"})(),
    )
    monkeypatch.setattr(repo, "obter_conversa", lambda s, cid: None)

    executor = exec_mod.Executor(
        modo=exec_mod.Modo.DESFECHO,
        sessao_factory=SessaoFalsa,
        responder=responder_falso,
        backoff=Backoff(seed=1, dormir=lambda _: None),
        modelo="falso:teste",
        **kwargs,
    )
    executor.recebidas = recebidas  # type: ignore[attr-defined]
    return executor, agente


def _rodar(executor, casos):
    estrat = amostragem._fechar(casos)
    return asyncio.run(executor.executar(estrat))


def test_rate_limit_e_retentado_e_a_execucao_continua(monkeypatch):
    """429 é transitório por definição. Abortar por causa dele desperdiçaria as horas já
    gastas numa execução longa e não interativa."""
    roteiro = [ErroDeProvedor("429 rate limit", 429), RunFalso()]
    executor, agente = _montar_executor(monkeypatch, roteiro)
    rel = _rodar(executor, [_caso("c1", falas=1)])

    # Uma chamada que falhou, a retentativa, e os dois turnos do respondedor — o
    # `responder_falso` sempre pergunta o plano.
    assert agente.chamadas == 2 + exec_mod.MAX_INJECOES_POR_FALA
    assert rel.completadas == 1
    assert rel.falhadas == 0
    assert rel.segundos_de_espera > 0


def test_rate_limit_persistente_marca_a_conversa_e_segue_para_a_proxima(monkeypatch):
    executor, _ = _montar_executor(
        monkeypatch, [ErroDeProvedor("429", 429)] * 40
    )
    rel = _rodar(executor, [_caso("c1", falas=1), _caso("c2", falas=1)])

    assert rel.falhadas == 2
    assert rel.completadas == 0
    assert rel.falhas_por_classe == {"rate_limit": 2}
    assert rel.interrompido_por is None  # não é fatal: a execução foi até o fim
    assert rel.taxa_de_acerto is None


def test_402_para_a_execucao_e_o_relatorio_diz_onde_parou(monkeypatch):
    """A propriedade central do módulo: 17 conversas com o motivo, e não um traceback."""
    executor, agente = _montar_executor(monkeypatch, [ErroDeProvedor("402", 402)] * 10)
    rel = _rodar(executor, [_caso(f"c{i}", falas=1) for i in range(5)])

    assert len(rel.resultados) == 1        # parou na primeira
    assert rel.nao_alcancadas == 4         # e diz quantas não tentou
    assert rel.falhas_por_classe == {"pagamento_402": 1}
    assert "402" in (rel.interrompido_por or "")
    assert agente.chamadas == 1            # não retentou: 402 não melhora com espera
    assert not rel.aprovado


def test_402_com_continuar_tenta_todas(monkeypatch):
    """A flag existe, e o default é o contrário — insistir num 402 só produz mais 402."""
    executor, _ = _montar_executor(
        monkeypatch, [ErroDeProvedor("402", 402)] * 10, parar_no_402=False
    )
    rel = _rodar(executor, [_caso(f"c{i}", falas=1) for i in range(3)])
    assert len(rel.resultados) == 3
    assert rel.interrompido_por is None


def test_o_relatorio_existe_mesmo_quando_a_execucao_morre_no_meio(monkeypatch):
    executor, _ = _montar_executor(monkeypatch, [ErroDeProvedor("402", 402)])
    rel = _rodar(executor, [_caso("c1", falas=2), _caso("c2", falas=2)])
    assert rel.terminado_em is not None
    assert rel.modo == "desfecho" and rel.modelo == "falso:teste"
    assert rel.conversas_pedidas == 2


def test_desfecho_esperado_sai_da_tabela_do_contrato(monkeypatch):
    """Lead incotável: **`quote_plan` obrigatório**, desfecho `refused`,
    `escalate_to_human` proibido. É a asserção que estava invertida na spec original."""
    executor, _ = _montar_executor(
        monkeypatch, [RunFalso(tools=[("quote_plan", "{}")])] * 5,
        observacao=exec_mod.Observacao(
            desfecho=Desfecho.REFUSED, motivo="idade_acima_do_limite"
        ),
    )
    rel = _rodar(executor, [_caso("c1", falas=1, cotavel=False)])
    linha = rel.resultados[0]

    assert linha.desfecho_esperado == "refused"
    assert linha.tools_faltando == []
    assert linha.tools_proibidas_chamadas == []
    assert linha.passou


def test_escalate_num_lead_incotavel_reprova(monkeypatch):
    """Recusa não cria handoff (DECISOES-FECHADAS §2)."""
    executor, _ = _montar_executor(
        monkeypatch,
        [RunFalso(tools=[("quote_plan", "{}"), ("escalate_to_human", "{}")])] * 5,
        observacao=exec_mod.Observacao(
            desfecho=Desfecho.REFUSED, motivo="idade_acima_do_limite"
        ),
    )
    rel = _rodar(executor, [_caso("c1", falas=1, cotavel=False)])
    assert rel.resultados[0].tools_proibidas_chamadas == ["escalate_to_human"]
    assert not rel.resultados[0].passou


def test_quote_indisponivel_nao_e_veredito_sobre_o_agente(monkeypatch):
    """A `/quote` falha em ~20% das chamadas. Encaminhar aí é o comportamento correto, e
    contá-lo como erro faria a taxa de acerto oscilar com `FAILURE_RATE`."""
    executor, _ = _montar_executor(
        monkeypatch, [RunFalso(tools=[("quote_plan", "{}")])] * 5,
        observacao=exec_mod.Observacao(
            desfecho=Desfecho.ENCAMINHADO, trigger_handoff="cotacao_indisponivel"
        ),
    )
    rel = _rodar(executor, [_caso("c1", falas=1)])
    assert rel.completadas == 0
    assert rel.falhas_por_classe == {"indisponivel": 1}


def test_o_respondedor_e_consultado_no_modo_desfecho(monkeypatch):
    """O `responder_falso` sempre pergunta o plano; o script tem que responder, e o
    turno extra tem que aparecer na contagem."""
    executor, agente = _montar_executor(monkeypatch, [RunFalso()] * 20)
    rel = _rodar(executor, [_caso("c1", falas=1)])
    assert rel.resultados[0].perguntas_do_agente >= 1
    assert agente.chamadas > 1  # a fala do dataset mais a resposta roteirizada


def test_o_respondedor_fica_desligado_no_modo_extracao(monkeypatch):
    """`data_inicio` e `plano_id` não têm gabarito e não são medidos: injetar respostas
    para eles gastaria inferência sem mudar a medição."""
    executor, agente = _montar_executor(monkeypatch, [RunFalso()] * 20)
    executor.modo = exec_mod.Modo.EXTRACAO
    _rodar(executor, [_caso("c1", falas=3)])
    assert agente.chamadas == 3  # exatamente as três falas do dataset


def test_o_laco_nao_injeta_alem_do_limite(monkeypatch):
    """Se o agente continuar perguntando depois de plano e data respondidos, insistir
    vira laço — e o laço apareceria no relatório como custo, não como defeito."""
    executor, agente = _montar_executor(monkeypatch, [RunFalso()] * 50)
    _rodar(executor, [_caso("c1", falas=1)])
    assert agente.chamadas <= 1 + exec_mod.MAX_INJECOES_POR_FALA


def test_o_tipo_da_fala_atravessa_o_replay_ate_o_agente(monkeypatch):
    """Sem isto, o estrato de mídia mede a coisa errada.

    Uma fala `[documento] CNH_frente.pdf` chegava ao agente como TEXTO comum: o
    executor chamava `responder` sem o `tipo`, `messages.tipo` gravava `text`, e
    `MIDIA_SEM_TEXTO` não tinha como disparar. A taxa do grupo media se o modelo, por
    conta própria, reagia a uma string que parecia um anexo — não a política de mídia.

    Descoberto lendo o relatório do replay: 14 das 15 conversas reprovadas eram
    `midia nao tratada`, uma causa só dominando todas as outras. Uma taxa ruim
    concentrada num grupo é sinal de instrumento quebrado antes de ser sinal de agente
    ruim.
    """
    import asyncio

    from qa.replay import executor as exec_mod

    executor, _ = _montar_executor(monkeypatch, ["ok"])
    caso = _caso()
    caso = type(caso)(
        conversation_id=caso.conversation_id,
        outcome=caso.outcome,
        falas=(
            Fala(0, "text", "oi"),
            Fala(1, "document", "[documento] CNH_frente.pdf"),
            Fala(2, "audio", "[audio] 0:12"),
        ),
        gabarito=caso.gabarito,
        elegibilidade=caso.elegibilidade,
    )

    asyncio.run(executor.rodar_conversa(caso, exec_mod.Coletor()))

    tipos = dict(executor.recebidas)
    assert tipos.get("oi") == "text"
    assert tipos.get("[documento] CNH_frente.pdf") == "document", (
        f"a fala de mídia chegou como {tipos.get('[documento] CNH_frente.pdf')!r} — "
        "o gatilho de mídia não tem como disparar"
    )
    assert tipos.get("[audio] 0:12") == "audio"


# ─── a falha que não vem como exceção ───────────────────────────────────────


def test_run_com_status_de_erro_vira_falha_classificada():
    """**O defeito que publicou um número falso.**

    O Agno não levanta quando a chamada ao provider falha: devolve um `RunOutput` com
    `status=ERROR` e o texto do erro em `content`. O `instrumentar` só classificava
    exceção, então o run entrava na lista como resposta normal do agente.

    Medido: a conta ficou sem crédito no meio de uma execução às 07:05:40, e as 18
    conversas seguintes viraram «o agente não perguntou nada e não chamou tool
    nenhuma» — `tools_chamadas: []`, `perguntas_do_agente: 0`, `falha: None`. O
    relatório publicou 36,7% de acerto sobre isso. Não era o agente: era uma fatura.

    `credit balance` cai em `PAGAMENTO`, que é `fatal` — a execução aborta na primeira
    em vez de produzir dezoito linhas que não medem nada.
    """
    from qa.replay.falhas import ClasseDeFalha, de_run_com_erro

    class RunComErro:
        status = "ERROR"
        content = (
            "Error code: 400 - {'type': 'error', 'error': {'type': "
            "'invalid_request_error', 'message': 'Your credit balance is too low to "
            "access the Anthropic API. Please go to Plans & Billing to upgrade or "
            "purchase credits.'}}"
        )

    falha = de_run_com_erro(RunComErro(), conversation_id="c1", message_index=3)
    assert falha is not None
    assert falha.classe is ClasseDeFalha.PAGAMENTO
    assert falha.fatal, "sem `fatal` a execução segue gastando relógio por nada"
    assert falha.conversation_id == "c1" and falha.message_index == 3


def test_run_bem_sucedido_nao_vira_falha():
    """O negativo: classificar run bom como falha zeraria toda a avaliação."""
    from qa.replay.falhas import de_run_com_erro

    class RunOk:
        status = "COMPLETED"
        content = "Boa, me passa o ano do carro?"

    assert de_run_com_erro(RunOk()) is None
    assert de_run_com_erro(type("Sem", (), {"content": "x"})()) is None


def test_a_costura_registra_o_run_com_erro_no_coletor(monkeypatch):
    """Ponta a ponta na costura: o `instrumentar` precisa VER o status.

    Um teste só sobre `de_run_com_erro` provaria a função e deixaria a fiação de
    fora — que foi exatamente como o defeito sobreviveu.
    """
    from qa.replay.captura import Coletor, instrumentar
    from qa.replay.falhas import ClasseDeFalha

    class RunComErro:
        status = "ERROR"
        content = "Error code: 429 - rate limit exceeded"

    class AgenteQueFalhaSemLevantar:
        def run(self, _texto):
            return RunComErro()

    coletor = Coletor()
    coletor.conversation_id = "c9"
    agente = instrumentar(AgenteQueFalhaSemLevantar(), coletor)

    agente.run("oi")

    assert len(coletor.falhas) == 1, (
        "o run com status de erro não chegou ao coletor — o executor continuaria "
        "tratando a resposta do provedor como fala do agente"
    )
    assert coletor.falhas[0].classe is ClasseDeFalha.RATE_LIMIT
