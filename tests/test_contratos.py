"""Testes dos contratos da Fase 0.

Provam três coisas que o resto da entrega assume:

1. `QuoteRequest` torna **impossível** montar uma requisição que a `/quote` aceitaria
   errado sem devolver erro (`plano_id` vazio, CEP de 7 dígitos).
2. `classificar_erro` separa as quatro classes de erro pela *forma do corpo*, não só
   pelo status — inclusive os dois casos que a API chama de recusa mas são bug nosso.
3. `QuotePayload` valida o corpo 200 **real** da API rodando, não um exemplo colado.

Os testes marcados `live` batem na `/quote` em `QUOTE_API_URL` (default
`http://localhost:8001`, a instância sem instabilidade). Sem ela, pulam.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import urllib.error
import urllib.request

import pytest
from pydantic import ValidationError

from app.contracts.channel import ChannelAdapter
from app.contracts.conversa import (
    Autor,
    HandoffSignal,
    HandoffTrigger,
    LeadProfile,
    MessageStatus,
    Turn,
)

from tests.fixtures.pii import cep_de
from app.contracts.quote import (
    MotivoRecusa,
    QuoteOutcome,
    QuotePayload,
    QuoteRequest,
    classificar_erro,
)

QUOTE_API_URL = os.getenv("QUOTE_API_URL", "http://localhost:8001")


# ─── QuoteRequest: normalização na fronteira ────────────────────────────────


def test_cep_mascarado_vira_oito_digitos():
    r = QuoteRequest(plano_id="completo", idade=35, veiculo_ano=2022, cep=cep_de("01"))
    assert r.cep == cep_de("01", com_hifen=False)


def test_cep_de_sete_digitos_e_descartado():
    """`"7000-000"` seria lido pela API como prefixo `"70"` e perderia o agravo de
    30% em silêncio. Vira `None` para que o agente repergunte."""
    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022, cep="7000-000")
    assert r.cep is None


@pytest.mark.parametrize(
    ("cep", "esperado"),
    [(cep_de("07"), True), (cep_de("08", com_hifen=False), True), (cep_de("59", com_hifen=False), True), (cep_de("01", com_hifen=False), False), (None, False)],
)
def test_deteccao_de_cep_de_alto_risco(cep, esperado):
    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022, cep=cep)
    assert r.cep_alto_risco is esperado


@pytest.mark.parametrize("plano_id", ["", "ouro", "COMPLETO", None])
def test_plano_id_invalido_e_rejeitado_na_construcao(plano_id):
    """`plano_id: ""` faz a API cotar `essencial` com status 200 — o erro mais
    perigoso, porque não aparece em nenhum status HTTP."""
    with pytest.raises(ValidationError):
        QuoteRequest(plano_id=plano_id, idade=35, veiculo_ano=2022)


def test_payload_omite_opcionais_em_vez_de_enviar_vazio():
    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022)
    assert r.to_api_payload() == {"plano_id": "essencial", "idade": 35, "veiculo_ano": 2022}


def test_payload_completo():
    r = QuoteRequest(
        plano_id="completo", idade=35, veiculo_ano=2022,
        cep=cep_de("01"), data_inicio=dt.date(2026, 7, 15),
    )
    assert r.to_api_payload() == {
        "plano_id": "completo", "idade": 35, "veiculo_ano": 2022,
        "cep": cep_de("01", com_hifen=False), "data_inicio": "2026-07-15",
    }


# ─── Taxonomia de erro ──────────────────────────────────────────────────────

CORPO_5XX = {"error": "upstream_unavailable", "message": "Servico temporariamente indisponivel."}


def _recusa(motivo: str) -> dict:
    return {"error": "cotacao_recusada", "motivo": motivo}


@pytest.mark.parametrize(
    ("status", "corpo", "timeout", "outcome", "motivo"),
    [
        (503, CORPO_5XX, False, QuoteOutcome.TRANSIENT, None),
        (500, CORPO_5XX, False, QuoteOutcome.TRANSIENT, None),
        (502, CORPO_5XX, False, QuoteOutcome.TRANSIENT, None),
        (None, None, True, QuoteOutcome.TIMEOUT, None),
        # Recusas de verdade — o lead ouve o motivo.
        (422, _recusa("Idade acima do limite de aceitacao (75 anos)."), False,
         QuoteOutcome.REFUSED, MotivoRecusa.IDADE_ACIMA),
        (422, _recusa("Idade fora das faixas aceitas."), False,
         QuoteOutcome.REFUSED, MotivoRecusa.IDADE_ABAIXO),
        (422, _recusa("Veiculo com mais de 20 anos nao e aceito."), False,
         QuoteOutcome.REFUSED, MotivoRecusa.VEICULO_ANTIGO),
        # Vestidos de recusa, mas são bug nosso: o lead informou um ano futuro, e o
        # `plano_id` fomos nós que escolhemos. Dizer "você foi recusado" seria mentir.
        (422, _recusa("Idade do veiculo fora das faixas aceitas."), False,
         QuoteOutcome.BAD_REQUEST, None),
        (422, _recusa("Plano 'ouro' inexistente. Opcoes: essencial, completo, premium"), False,
         QuoteOutcome.BAD_REQUEST, None),
        # Validação do Pydantic e parsing interno: bug nosso, o lead nunca vê.
        (422, {"detail": [{"type": "missing", "loc": ["body", "idade"]}]}, False,
         QuoteOutcome.BAD_REQUEST, None),
        (400, {"error": "payload_invalido", "detalhe": "Invalid isoformat string: '15/07/2026'"},
         False, QuoteOutcome.BAD_REQUEST, None),
        (405, None, False, QuoteOutcome.BAD_REQUEST, None),
        (404, None, False, QuoteOutcome.BAD_REQUEST, None),
    ],
)
def test_classificacao_de_erro(status, corpo, timeout, outcome, motivo):
    e = classificar_erro(status, corpo, timeout=timeout)
    assert e.outcome is outcome
    assert e.motivo_recusa is motivo


@pytest.mark.parametrize(
    ("outcome", "retentavel"),
    [
        (QuoteOutcome.TRANSIENT, True),
        (QuoteOutcome.TIMEOUT, True),
        (QuoteOutcome.OK, False),
        (QuoteOutcome.REFUSED, False),
        (QuoteOutcome.BAD_REQUEST, False),
    ],
)
def test_so_transitorio_e_timeout_retentam(outcome, retentavel):
    assert outcome.retentavel is retentavel


def test_422_do_pydantic_nao_propaga_detalhe():
    """O corpo do 422 de validação ecoa o payload enviado — idade e CEP do lead.
    Ele não pode viajar para log nem para a tela."""
    # CEP do gerador: o valor não importa para a classificação, e um literal aqui
    # violaria o invariante 13b tanto quanto num teste de mascaramento.
    e = classificar_erro(
        422, {"detail": [{"input": {"idade": 80, "cep": cep_de("07", com_hifen=False)}}]}
    )
    assert e.detalhe_bruto is None


def test_motivo_desconhecido_nao_vira_recusa():
    """Na dúvida, não afirmamos ao lead que ele foi recusado."""
    e = classificar_erro(422, _recusa("Motivo que a API ainda não tinha em 2026."))
    assert e.outcome is QuoteOutcome.BAD_REQUEST


# ─── LeadProfile ────────────────────────────────────────────────────────────


def test_campos_faltantes_seguem_a_ordem_de_qualificacao():
    assert LeadProfile(idade=35).campos_faltantes == ("veiculo_ano", "cep", "data_inicio", "plano_id")


def test_perfil_incompleto_nao_cota():
    with pytest.raises(ValueError, match="perfil incompleto"):
        LeadProfile(idade=35).to_quote_request()


def test_perfil_completo_produz_a_requisicao():
    lp = LeadProfile(
        idade=35, veiculo_ano=2022, cep=cep_de("01", com_hifen=False),
        data_inicio=dt.date(2026, 7, 15), plano_id="completo",
    )
    assert lp.completo
    assert lp.to_quote_request() == QuoteRequest(
        plano_id="completo", idade=35, veiculo_ano=2022,
        cep=cep_de("01", com_hifen=False), data_inicio=dt.date(2026, 7, 15),
    )


def test_lead_profile_rejeita_cep_fora_de_oito_digitos():
    with pytest.raises(ValidationError):
        LeadProfile(cep="7000000")


# ─── Turno, handoff e porta ─────────────────────────────────────────────────


def test_mensagem_com_preco_carrega_quote_id():
    t = Turn(
        message_id="m1", conversation_id="c1", index=0, autor=Autor.SISTEMA,
        conteudo="Ficou R$ 209,90/mês.", status=MessageStatus.SENT,
        criado_em=dt.datetime(2026, 9, 4, 12, 0), quote_id="q1",
    )
    assert t.quote_id == "q1"


def test_handoff_e_disparado_por_regra_ate_prova_em_contrario():
    h = HandoffSignal(trigger=HandoffTrigger.COTACAO_INDISPONIVEL, reason="3 tentativas sem resposta")
    assert h.disparado_por == "regra"


def test_adaptador_minimo_satisfaz_a_porta():
    class Fake:
        name = "fake"

        async def send(self, conversation_id, text, *, message_id, quote_id=None):
            return "x"

        async def typing(self, conversation_id, *, ativo): ...

        def receive(self): ...

    assert isinstance(Fake(), ChannelAdapter)


# ─── Contra a API rodando ───────────────────────────────────────────────────


def _post(payload: dict) -> dict:
    req = urllib.request.Request(
        f"{QUOTE_API_URL}/quote",
        data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


@pytest.fixture(scope="module")
def api_viva() -> None:
    try:
        with urllib.request.urlopen(f"{QUOTE_API_URL}/health", timeout=3):
            return
    except (urllib.error.URLError, OSError):
        pytest.skip(f"/quote indisponível em {QUOTE_API_URL}")


@pytest.mark.live
def test_payload_valida_o_corpo_200_real(api_viva):
    r = QuoteRequest(
        plano_id="completo", idade=35, veiculo_ano=2022,
        cep=cep_de("01"), data_inicio=dt.date(2026, 7, 15),
    )
    p = QuotePayload.model_validate(_post(r.to_api_payload()))
    assert p.premio_mensal == 209.90
    assert p.carencia.dias == 30
    assert p.carencia.coberturas == ["roubo", "furto"]
    assert p.primeiro_pagamento_pro_rata is not None


@pytest.mark.live
@pytest.mark.parametrize("plano_id", ["essencial", "completo", "premium"])
def test_carencia_vem_nos_tres_planos(api_viva, plano_id):
    """Ela é incondicional na resposta — por isso entra no template, e não fica a
    critério do modelo lembrar."""
    p = QuotePayload.model_validate(
        _post(QuoteRequest(plano_id=plano_id, idade=35, veiculo_ano=2022).to_api_payload())
    )
    assert p.carencia.dias == 30


@pytest.mark.live
def test_pro_rata_some_no_dia_primeiro(api_viva):
    r = QuoteRequest(plano_id="essencial", idade=35, veiculo_ano=2022,
                     data_inicio=dt.date(2026, 10, 1))

    assert QuotePayload.model_validate(_post(r.to_api_payload())).primeiro_pagamento_pro_rata is None
