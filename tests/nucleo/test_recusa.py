"""O caminho de recusa — 30% do tráfego, tratado como fluxo principal.

Aplicando as regras de `plans.json` ao dataset: 280 conversas recusadas por idade,
531 por veículo com mais de 20 anos, 60 por ambos — **751 de 2.500, ou 30,0%**. Não é
exceção rara; é três em cada dez leads.

O que este arquivo prova:

1. cada motivo tem o seu texto, do mapa fixo, byte a byte;
2. o texto cru da API nunca chega ao lead;
3. **não retenta** e **não cria handoff**;
4. o que *parece* recusa e não é — ano futuro, plano inexistente — não vira recusa;
5. o reenquadramento acontece **em dois turnos**, sem exceção na regra de descarte;
6. o agente **nunca** sugere trocar o condutor principal.
"""

import datetime as dt
import os

import httpx
import pytest

from app import textos
from app.agent.tools import ContextoDoTurno, make_qualify_lead, make_quote_plan
from app.contracts.quote import MotivoRecusa, QuoteRequest
from app.persistence import repo

from tests.fixtures.pii import cep_de
from app.persistence.models import Handoff, Message, Quote, QuoteAttempt
from app.quote import client
from app.quote.breaker import breaker_global, resetar_breaker
from app.quote.job import executar_job

pytestmark = [pytest.mark.db, pytest.mark.live]

LIMPA = os.getenv("QUOTE_API_LIMPA", "http://localhost:8001")
FALHA = os.getenv("QUOTE_API_FALHA", "http://localhost:8002")


@pytest.fixture(autouse=True)
def bancada(monkeypatch):
    from app.config import get_settings

    for url in (LIMPA, FALHA):
        try:
            httpx.get(f"{url}/health", timeout=2.0).raise_for_status()
        except Exception:  # noqa: BLE001
            pytest.skip(f"bancada indisponível: {url}")
    monkeypatch.setattr(get_settings(), "quote_api_url", LIMPA)
    resetar_breaker()
    client.resetar_semaforo()
    yield
    resetar_breaker()
    client.resetar_semaforo()


class Canal:
    def __init__(self, sessao, conversation_id):
        self.sessao, self.conversation_id = sessao, conversation_id
        self.enviadas: list[str] = []

    def __call__(self, texto, quote_id=None, autor="sistema"):
        m = repo.gravar_mensagem(self.sessao, self.conversation_id, autor=autor,
                                 conteudo=texto, status="sent", quote_id=quote_id)
        self.enviadas.append(m.conteudo)


@pytest.fixture
def canal(sessao, conversa):
    return Canal(sessao, conversa.id)


@pytest.fixture
def ctx(sessao, conversa, canal):
    return ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)


# ─── cada motivo, o seu texto ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "idade,ano,motivo,texto",
    [
        (80, 2022, MotivoRecusa.IDADE_ACIMA, textos.RECUSA_IDADE_ACIMA),
        (17, 2022, MotivoRecusa.IDADE_ABAIXO, textos.RECUSA_IDADE_ABAIXO),
        (35, 2000, MotivoRecusa.VEICULO_ANTIGO, textos.RECUSA_VEICULO),
    ],
    ids=["idade≥76", "idade<18", "veículo>20anos"],
)
def test_cada_motivo_tem_o_seu_texto(ctx, sessao, canal, idade, ano, motivo, texto):
    r = make_quote_plan(ctx)("completo", idade, ano)
    assert "recusado" in r
    assert sessao.query(Quote).one().motivo_recusa == str(motivo)
    assert canal.enviadas[-1] == texto           # byte a byte, do mapa fixo


def test_texto_cru_da_api_nunca_chega_ao_lead(ctx, canal):
    """A API escreve para sistema, sem acento: "Idade acima do limite de aceitacao"."""
    make_quote_plan(ctx)("completo", 80, 2022)
    conteudo = canal.enviadas[-1]
    assert "cotacao_recusada" not in conteudo
    assert "Idade acima do limite de aceitacao" not in conteudo


def test_a_mensagem_de_recusa_e_do_sistema_nao_do_modelo(ctx, sessao):
    make_quote_plan(ctx)("completo", 80, 2022)
    assert sessao.query(Message).one().autor == "sistema"


def test_o_texto_do_modelo_e_descartado_no_turno_da_recusa(ctx):
    """Sem exceção. Ali o risco não é preço alucinado — é promessa falsa: "vou ver
    com o setor de exceções"."""
    make_quote_plan(ctx)("completo", 80, 2022)
    assert ctx.ja_enviou is True


# ─── não retenta, não encaminha ──────────────────────────────────────────────


def test_recusa_nao_consome_mais_de_uma_tentativa(sessao, conversa):
    q = executar_job(sessao, conversa.id,
                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
    assert q.status == "refused"
    assert sessao.query(QuoteAttempt).count() == 1


def test_recusa_nao_cria_handoff(ctx, sessao, conversa):
    """Um humano releria a mesma regra fixa em plans.json e daria o mesmo "não".
    Encaminhar 30% do tráfego para isso encheria a fila com casos sem saída."""
    make_quote_plan(ctx)("completo", 80, 2022)
    sessao.commit()
    assert sessao.query(Handoff).count() == 0
    assert repo.obter_conversa(sessao, conversa.id).state != "encaminhado"


def test_recusa_nao_conta_para_o_breaker(sessao, conversa):
    """Recusa é a API funcionando perfeitamente. Contá-la abriria o circuito num dia
    de muitos leads idosos."""
    from app.quote.breaker import Estado

    for _ in range(10):
        executar_job(sessao, conversa.id,
                     QuoteRequest(plano_id="completo", idade=80, veiculo_ano=2022))
    assert breaker_global().estado is Estado.FECHADO


# ─── o que PARECE recusa e não é ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "args,porque",
    [
        (("completo", 35, 2030), "ano futuro: o lead não é inelegível, o dado está errado"),
        (("completo", 35, 2027), "idem"),
    ],
)
def test_ano_futuro_nao_vira_recusa(ctx, sessao, canal, args, porque):
    """Dizer "seu veículo não é aceito" a quem informou 2030 é mentir para ele."""
    r = make_quote_plan(ctx)(*args)
    assert "dados_invalidos" in r, porque
    assert not any(t in canal.enviadas for t in textos.RECUSAS), porque
    assert sessao.query(Quote).one().motivo_recusa is None


def test_plano_inexistente_nao_vira_recusa(ctx, canal):
    """Nenhum lead digita `plano_id` — fomos NÓS que escolhemos."""
    r = make_quote_plan(ctx)("ouro", 35, 2019)
    assert "dados_invalidos" in r
    assert not any(t in canal.enviadas for t in textos.RECUSAS)


# ─── o registro, e o que ele não promete ─────────────────────────────────────


def test_o_lead_recusado_fica_visivel_no_admin(ctx, sessao, conversa):
    """"Deixei seu cadastro registrado do nosso lado" é verdade: a conversa está no
    banco, com o perfil e o motivo, e aparece na listagem do operador."""
    from app.api import consultas

    make_qualify_lead(ctx)(idade=80, veiculo_ano=2022)
    make_quote_plan(ctx)("completo", 80, 2022)
    sessao.commit()

    linha = next(c for c in consultas.resumo_conversas(sessao) if c["id"] == conversa.id)
    assert linha["ultima_cotacao_status"] == "refused"
    assert repo.obter_conversa(sessao, conversa.id).idade == 80


@pytest.mark.parametrize("texto", textos.RECUSAS)
def test_nenhuma_recusa_promete_contato(texto):
    """Prometer que alguém liga seria a promessa vazia que a regra máxima proíbe —
    não há quem faça esse contato."""
    t = texto.lower()
    for proibido in ("entraremos em contato", "vamos te ligar", "retornamos",
                     "em breve", "assim que possível", "nossa equipe vai"):
        assert proibido not in t


# ─── o reenquadramento, e o seu limite ───────────────────────────────────────


def test_so_a_recusa_por_veiculo_oferece_reenquadramento():
    assert "outro carro" in textos.RECUSA_VEICULO
    assert "outro carro" not in textos.RECUSA_IDADE_ACIMA
    assert "outro carro" not in textos.RECUSA_IDADE_ABAIXO


@pytest.mark.parametrize("texto", [textos.RECUSA_IDADE_ACIMA, textos.RECUSA_IDADE_ABAIXO])
def test_recusa_por_idade_nunca_sugere_trocar_o_condutor(texto):
    """Se quem dirige de fato tem 78 anos, declarar outra pessoa como condutor
    principal é declaração falsa — e a conta chega como negativa de sinistro, no pior
    momento possível para o cliente.

    Registrar um fato que o lead trouxe é uma coisa; sugerir o caminho é outra.
    """
    t = texto.lower()
    for proibido in ("outro condutor", "outra pessoa", "condutor principal",
                     "no nome de", "no nome do", "exceção", "excecao",
                     "autorização especial", "jeitinho", "declare"):
        assert proibido not in t


def test_a_recusa_por_idade_fecha_a_porta_da_excecao():
    """O texto diz explicitamente o que o modelo inventaria sozinho."""
    assert "não é algo que eu consiga contornar" in textos.RECUSA_IDADE_ACIMA


def test_reenquadramento_acontece_em_dois_turnos(ctx, sessao, conversa, canal):
    """A oferta vem DENTRO do template; o turno seguinte é livre.

    Turno 1: recusa por veículo, texto de template, texto do modelo descartado.
    Turno 2: sem resultado de tool, o modelo conversa e pode cotar de novo.
    """
    make_quote_plan(ctx)("completo", 35, 2000)
    assert canal.enviadas[-1] == textos.RECUSA_VEICULO
    assert ctx.ja_enviou is True

    # A conversa NÃO terminou — não houve handoff e o estado não é terminal.
    sessao.commit()
    assert sessao.query(Handoff).count() == 0
    assert repo.obter_conversa(sessao, conversa.id).state != "encaminhado"

    # Turno 2, com o outro veículo: cota normalmente.
    #
    # ⚠️ Um `ContextoDoTurno` NOVO, e não o mesmo com `ja_enviou` zerado. O envelope
    # é por turno — `responder` constrói um a cada mensagem —, e é ele que carrega a
    # trava de uma cotação por turno. Reaproveitar o objeto simulava um segundo turno
    # que não existe em lugar nenhum do código de produção, e esta linha passou a
    # falhar quando a trava entrou: era o teste que estava frouxo, não a trava.
    #
    # Que o reenquadramento leve dois turnos é a decisão §2, não um efeito colateral.
    ctx2 = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)
    r = make_quote_plan(ctx2)("completo", 35, 2021, cep_de("01"), "2026-10-17")
    assert "cotado" in r
    assert sessao.query(Quote).filter(Quote.status == "ok").count() == 1


# ─── recusa sob instabilidade — o cruzamento com a fatia 4 ───────────────────


@pytest.mark.serial
def test_breaker_aberto_nao_vira_recusa(ctx, sessao, monkeypatch, canal):
    """Com o circuito aberto **não chamamos a API**, logo não sabemos se este lead
    seria recusado. Afirmar recusa ali seria adivinhar."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "quote_api_url", FALHA)
    monkeypatch.setattr(get_settings(), "quote_backoff_teto_s", 0.01)
    for _ in range(2):
        executar_job(sessao, conversa.id if False else ctx.conversation_id,
                     QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2019))

    r = make_quote_plan(ctx)("completo", 80, 2022)       # lead REALMENTE incotável
    assert "indisponivel" in r
    assert not any(t in canal.enviadas for t in textos.RECUSAS)
    assert sessao.query(Quote).filter(Quote.circuito_aberto.is_(True)).count() >= 1


# ─── contra o modelo real ────────────────────────────────────────────────────


@pytest.mark.modelo
async def test_o_agente_nao_sugere_trocar_o_condutor(sessao, conversa, canal):
    """O teste que reprova o comportamento inteiro se ele voltar.

    Roda contra o modelo de verdade, porque é o modelo que poderia inventar isso —
    os testes de texto acima protegem o template, e não o que o agente escreve por
    conta própria no turno seguinte à recusa, que é livre.
    """
    from app.agent.agente import construir_agente
    from app.bootstrap import bootstrap

    bootstrap()
    ctx = ContextoDoTurno(sessao=sessao, conversation_id=conversa.id, enviar=canal)
    agente = construir_agente(ctx)

    # Os CINCO campos numa mensagem só: sem o CEP o agente reperguntaria em vez de
    # cotar, e o teste mediria a qualificação em vez do caminho de recusa.
    r = agente.run(
        "tenho 80 anos, meu carro é um Onix 2022, o cep aqui é " + cep_de("01") + ", "
        "quero o Completo, começando dia 17 de outubro"
    )
    dito = " ".join([*canal.enviadas, (r.content or "")]).lower()

    for proibido in ("no nome do seu", "no nome da sua", "coloque outra pessoa",
                     "declare outra", "condutor principal seja", "consigo uma exceção",
                     "setor de exceções", "autorização especial", "dar um jeito"):
        assert proibido not in dito, f"o agente sugeriu: {proibido!r}"

    # E disse o motivo real, do template.
    assert textos.RECUSA_IDADE_ACIMA in canal.enviadas
