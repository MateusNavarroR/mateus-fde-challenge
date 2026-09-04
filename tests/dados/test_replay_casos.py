"""A montagem dos casos de replay — o corpus virando entrada do agente.

Os testes rodam sobre linhas sintéticas com PII do **gerador semeado** de
`tests/fixtures/pii.py` (CLAUDE.md 13b): nenhum literal de PII entra no repositório, nem
sintético, e o regex é exercitado no formato real em vez de num exemplo escolhido a dedo.

Os que dependem do parquet do desafio ficam separados e **pulam** quando ele não está no
caminho configurado — quem clona só este repositório não tem o dataset, e uma suíte
vermelha por falta de um arquivo externo ensina a ignorar vermelho.
"""

from __future__ import annotations

import pytest

from app.privacy.mascarar import contem_pii, mascarar
from qa.replay import casos as construtor
from tests.fixtures.pii import cep_de, frase_do_lead


def _linha(conv, idx, corpo, *, papel="lead", tipo="text", idade=35,
           veiculo="Toyota Corolla 2018", outcome="ganho"):
    return {
        "conversation_id": conv,
        "message_index": idx,
        "timestamp": 1000 - idx,  # relógio invertido de propósito: ver o teste da ordem
        "sender_role": papel,
        "sender_name": "Fulano de Tal",
        "message_type": tipo,
        "message_body": corpo,
        "channel": "whatsapp",
        "conversation_outcome": outcome,
        "lead_idade_informada": idade,
        "veiculo_texto": veiculo,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ordem e recorte
# ─────────────────────────────────────────────────────────────────────────────


def test_falas_saem_em_ordem_de_message_index_e_nao_de_timestamp():
    """2.495 das 2.500 conversas têm relógio não monotônico (API-COTACAO §8.3).

    O replay é literal: injetar as falas na ordem do relógio embaralharia 99,8% do
    corpus e mediria o agente contra uma conversa que nunca aconteceu.
    """
    linhas = [
        _linha("c1", 2, "terceira"),
        _linha("c1", 0, "primeira"),
        _linha("c1", 1, "segunda"),
    ]
    [caso] = construtor.montar(linhas, ano_corrente=2026)
    assert [f.texto for f in caso.falas] == ["primeira", "segunda", "terceira"]
    assert [f.message_index for f in caso.falas] == [0, 1, 2]


def test_so_as_falas_do_lead_entram():
    """As do vendedor são 10.000 das 26.470 e não são reproduzidas.

    Injetá-las faria o agente responder ao vendedor do dataset — cujas cotações são 100%
    impossíveis (§8.2) —, que é a definição de aprender a coisa errada.
    """
    linhas = [
        _linha("c1", 0, "oi", papel="lead"),
        _linha("c1", 1, "boa tarde!", papel="vendedor"),
        _linha("c1", 2, "quero cotar", papel="lead"),
    ]
    [caso] = construtor.montar(linhas, ano_corrente=2026)
    assert [f.texto for f in caso.falas] == ["oi", "quero cotar"]
    assert caso.inferencias == 2


def test_conversa_sem_fala_do_lead_e_descartada():
    """Não existe no dataset medido; a guarda é para um parquet diferente falhar na
    contagem em vez de produzir um caso vazio que o replay tentaria injetar."""
    assert construtor.montar([_linha("c1", 0, "oi", papel="vendedor")]) == []


# ─────────────────────────────────────────────────────────────────────────────
# Gabarito: três campos, e só três
# ─────────────────────────────────────────────────────────────────────────────


def test_gabarito_tem_idade_ano_e_cep():
    fala, pii = frase_do_lead(seed=11)
    linhas = [_linha("c1", 0, fala, idade=35, veiculo="Renault Sandero 2022")]
    [caso] = construtor.montar(linhas, ano_corrente=2026)

    assert caso.gabarito.idade == 35
    assert caso.gabarito.veiculo_ano == 2022
    assert caso.gabarito.cep == pii["cep"].replace("-", "")
    assert caso.gabarito.campos_com_gabarito == ("idade", "veiculo_ano", "cep")


def test_marca_e_modelo_nao_viram_gabarito():
    """`veiculo_texto` contém informação que o lead nunca disse (DECISOES-FECHADAS §9).

    A coluna diz "Renault Sandero 2022" e a fala diz "e um Sandero 2022". Penalizar o
    agente por não extrair uma marca que ninguém pronunciou mediria o ruído do gabarito,
    e por isso o `Gabarito` **não tem** campo para marca nem para modelo — a ausência é
    a garantia, e este teste é o que a torna difícil de desfazer por engano.
    """
    campos = construtor.Gabarito.__dataclass_fields__
    assert set(campos) == {"idade", "veiculo_ano", "cep"}


def test_cep_e_extraido_pelo_mesmo_padrao_do_mascaramento():
    """Uma segunda definição de "o que é um CEP" divergiria da primeira — e a primeira é
    a que decide o que vaza."""
    from app.privacy.mascarar import _REGRAS

    assert construtor._CEP is next(p for nome, p, _ in _REGRAS if nome == "cep")


def test_cep_normalizado_para_oito_digitos():
    """`conversations.cep` é `String(8)`: comparar cep_de("01") com cep_de("01", com_hifen=False)
    reprovaria uma extração correta."""
    fala, pii = frase_do_lead(seed=7)
    [caso] = construtor.montar([_linha("c1", 0, fala)], ano_corrente=2026)
    assert caso.gabarito.cep is not None
    assert len(caso.gabarito.cep) == 8 and caso.gabarito.cep.isdigit()
    assert caso.gabarito.cep == pii["cep"].replace("-", "")


def test_sem_cep_na_fala_o_gabarito_fica_vazio():
    """Campo sem gabarito não conta como erro do agente — contar rebaixaria a taxa por
    culpa do corpus."""
    [caso] = construtor.montar([_linha("c1", 0, "oi, quero cotar")], ano_corrente=2026)
    assert caso.gabarito.cep is None
    assert "cep" not in caso.gabarito.campos_com_gabarito


def test_as_falas_chegam_cruas_ao_agente_e_isso_e_o_ponto():
    """O replay lê o **bronze**, não o silver.

    O silver mascara `message_body`: injetar "meu cep é [CEP]" mediria o mascaramento, e
    a extração de CEP — que subcota em 30% quando erra — nunca seria exercitada.
    """
    fala, _ = frase_do_lead(seed=3)
    [caso] = construtor.montar([_linha("c1", 0, fala)], ano_corrente=2026)
    assert contem_pii(caso.falas[0].texto)
    assert caso.falas[0].texto != mascarar(fala)


# ─────────────────────────────────────────────────────────────────────────────
# Elegibilidade e mídia
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "idade,veiculo,cotavel,motivo",
    [
        (35, "Toyota Corolla 2018", True, None),
        (80, "Toyota Corolla 2018", False, "idade_acima_do_limite"),
        (35, "Fiat Uno 2004", False, "veiculo_acima_de_20_anos"),
        # Recusada pelos dois: a API reporta a idade primeiro, por precedência do
        # serviço. É o estrato de 60 conversas que a amostragem garante.
        (80, "Fiat Uno 2004", False, "idade_acima_do_limite"),
    ],
)
def test_elegibilidade_vira_desfecho_esperado(idade, veiculo, cotavel, motivo):
    linhas = [_linha("c1", 0, "oi", idade=idade, veiculo=veiculo)]
    [caso] = construtor.montar(linhas, ano_corrente=2026)
    assert caso.cotavel is cotavel
    assert caso.motivo_recusa == motivo


def test_conversa_recusada_pelos_dois_mantem_os_dois_eixos():
    """O motivo único sozinho esconderia as 60 conversas recusadas por ambos."""
    linhas = [_linha("c1", 0, "oi", idade=80, veiculo="Fiat Uno 2004")]
    [caso] = construtor.montar(linhas, ano_corrente=2026)
    assert caso.elegibilidade.por_idade and caso.elegibilidade.por_veiculo


@pytest.mark.parametrize("tipo", construtor.TIPOS_DE_MIDIA)
def test_midia_sem_transcricao_e_marcada(tipo):
    """1.789 mensagens (6,8%) são mídia sem transcrição (§8.3).

    O corpo existe — "[audio] mensagem de voz (18s)" — mas é rótulo do gerador, não
    transcrição: não há conteúdo para extrair, e a política é pedir por texto ou
    encaminhar, nunca inventar.
    """
    linhas = [
        _linha("c1", 0, "oi"),
        _linha("c1", 1, f"[{tipo}] alguma coisa", tipo=tipo),
    ]
    [caso] = construtor.montar(linhas, ano_corrente=2026)
    assert caso.tem_midia_sem_transcricao
    assert caso.midias == 1
    assert caso.falas[1].e_midia_sem_transcricao
    assert not caso.falas[0].e_midia_sem_transcricao


# ─────────────────────────────────────────────────────────────────────────────
# Contra o parquet de verdade
# ─────────────────────────────────────────────────────────────────────────────


def test_o_corpus_tem_16470_falas_do_lead(casos_replay):
    """A medição que dimensiona o custo de relógio (DECISOES-FECHADAS §9).

    16.470 inferências × ~3 s = ~14 h de parede. É este número que obriga o default a
    ser uma amostra de 30 conversas, e conferi-lo é o que impede a estimativa impressa
    pelo `__main__` de virar folclore.
    """
    assert len(casos_replay) == 2500
    assert sum(c.inferencias for c in casos_replay) == 16470


def test_o_corpus_tem_cep_em_toda_conversa(casos_replay):
    """100% das conversas têm CEP em texto livre (§8.3) — logo, 100% têm gabarito de CEP."""
    sem_cep = [c.conversation_id for c in casos_replay if c.gabarito.cep is None]
    assert sem_cep == []
