"""A estratificação — e por que uma amostra aleatória não serviria.

O teste central deste arquivo reproduz as contagens medidas em `docs/API-COTACAO.md`
§8.1 e §8.3 a partir do parquet. Os demais rodam sobre um corpus sintético, para que a
propriedade — "o estrato de 60 conversas sempre entra" — seja verificável sem o dataset
externo.
"""

from __future__ import annotations

from qa.replay import amostra as amostragem
from qa.replay.casos import CasoReplay, Fala, Gabarito
from qa.dataset.elegibilidade import Elegibilidade

OUTCOMES = ("em_negociacao", "ganho", "perdido", "sem_resposta")


def _caso(cid: str, *, idade=False, veiculo=False, outcome="ganho", midia=False, falas=5):
    """Um caso sintético com os eixos que a amostragem lê. Nada mais."""
    return CasoReplay(
        conversation_id=cid,
        outcome=outcome,
        falas=tuple(Fala(i, "audio" if (midia and i == 0) else "text", "oi") for i in range(falas)),
        gabarito=Gabarito(idade=35, veiculo_ano=2018, cep="01310100"),
        elegibilidade=Elegibilidade(
            cotavel=not (idade or veiculo),
            por_idade=idade,
            por_veiculo=veiculo,
            motivo=None,
            ano_veiculo=2018,
            idade_veiculo=8,
        ),
        _midias=1 if midia else 0,
    )


def _corpus(n_por_celula: int = 40) -> list[CasoReplay]:
    """Um corpus com as 16 células cheias, para a proporcionalidade ter o que dividir."""
    corpus: list[CasoReplay] = []
    combinacoes = (
        ("ambos", True, True),
        ("so_idade", True, False),
        ("so_veiculo", False, True),
        ("cotavel", False, False),
    )
    for nome, idade, veiculo in combinacoes:
        for outcome in OUTCOMES:
            for i in range(n_por_celula):
                corpus.append(
                    _caso(
                        f"{nome}-{outcome}-{i}",
                        idade=idade, veiculo=veiculo, outcome=outcome,
                        midia=(i % 5 == 0),
                    )
                )
    return corpus


# ─────────────────────────────────────────────────────────────────────────────
# As medições, reproduzidas
# ─────────────────────────────────────────────────────────────────────────────


def test_contagem_medida_reproduz_a_tabela_da_api(casos_replay):
    """280 por idade · 531 por veículo · 60 por ambos · 1.749 cotáveis (§8.1).

    A forma conferida é a **publicada**, com sobreposição: 280 e 531 incluem as 60, e
    280 + 531 − 60 = 751 = 30,0%. Conferir uma partição disjunta aqui seria conferir uma
    tabela diferente da que o documento publica.
    """
    assert amostragem.contar_medido(casos_replay) == amostragem.MEDIDO


def test_a_particao_disjunta_fecha_com_a_medida(casos_replay):
    """A partição usada para sortear não pode perder nem duplicar conversa."""
    from collections import Counter

    contagem = Counter(amostragem.estrato_de(c) for c in casos_replay)
    assert sum(contagem.values()) == amostragem.MEDIDO["conversas"]
    assert contagem["ambos"] == amostragem.MEDIDO["ambos"]
    assert contagem["so_idade"] == amostragem.MEDIDO["idade"] - amostragem.MEDIDO["ambos"]
    assert contagem["so_veiculo"] == amostragem.MEDIDO["veiculo"] - amostragem.MEDIDO["ambos"]
    assert contagem["cotavel"] == amostragem.MEDIDO["cotaveis"]


def test_os_quatro_outcomes_do_dataset_aparecem(casos_replay):
    """`em_negociacao` 757 · `ganho` 712 · `perdido` 538 · `sem_resposta` 493 (§8.3)."""
    from collections import Counter

    contagem = Counter(c.outcome for c in casos_replay)
    assert contagem == {
        "em_negociacao": 757, "ganho": 712, "perdido": 538, "sem_resposta": 493
    }


# ─────────────────────────────────────────────────────────────────────────────
# As propriedades da amostragem
# ─────────────────────────────────────────────────────────────────────────────


def test_o_estrato_de_ambos_sempre_entra():
    """O motivo inteiro de estratificar.

    Numa amostra aleatória de 30 em 2.500, a chance de pegar uma das 60 conversas
    recusadas pelos dois motivos é ~51%: metade das execuções não exercitaria o estrato
    que fixa qual recusa a API reporta primeiro.
    """
    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
    assert amostra.por_elegibilidade.get("ambos", 0) >= 1


def test_todas_as_celulas_nao_vazias_recebem_ao_menos_uma_vaga():
    """4 estratos × 4 outcomes = 16 células, e `n=30` cabe todas."""
    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
    celulas = {(amostragem.estrato_de(c), c.outcome) for c in amostra.casos}
    assert len(celulas) == 16


def test_amostra_tem_exatamente_n_conversas_sem_repetir():
    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
    assert len(amostra) == 30
    assert len({c.conversation_id for c in amostra.casos}) == 30


def test_amostragem_e_deterministica_para_a_mesma_seed():
    """Uma amostra que muda a cada execução torna impossível dizer se a taxa caiu porque
    o agente piorou ou porque saíram outras conversas."""
    a = amostragem.amostrar(_corpus(), n=30, seed=42)
    b = amostragem.amostrar(_corpus(), n=30, seed=42)
    assert [c.conversation_id for c in a.casos] == [c.conversation_id for c in b.casos]


def test_seeds_diferentes_dao_amostras_diferentes():
    a = amostragem.amostrar(_corpus(), n=30, seed=1)
    b = amostragem.amostrar(_corpus(), n=30, seed=2)
    assert [c.conversation_id for c in a.casos] != [c.conversation_id for c in b.casos]


def test_a_ordem_do_corpus_nao_muda_a_amostra():
    """Dois parquets com as mesmas conversas em ordem física diferente têm que produzir
    a mesma amostra — senão a seed não reproduz nada."""
    corpus = _corpus()
    a = amostragem.amostrar(corpus, n=30, seed=7)
    b = amostragem.amostrar(list(reversed(corpus)), n=30, seed=7)
    assert sorted(c.conversation_id for c in a.casos) == sorted(
        c.conversation_id for c in b.casos
    )


def test_cota_de_midia_e_garantida():
    """O estrato transversal: conversas com mídia sem transcrição."""
    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
    assert amostra.com_midia >= max(1, round(30 * amostragem.FRACAO_MIDIA))


def test_cota_de_midia_troca_dentro_da_celula():
    """Trocar dentro da célula é o que impede a cota transversal de desfazer a
    estratificação: sai uma conversa sem mídia, entra uma com mídia do mesmo estrato e
    do mesmo `outcome`."""
    corpus = _corpus()
    sem_cota = amostragem.amostrar(corpus, n=30, seed=1, fracao_midia=0.0)
    com_cota = amostragem.amostrar(corpus, n=30, seed=1)
    assert sem_cota.por_elegibilidade == com_cota.por_elegibilidade
    assert sem_cota.por_outcome == com_cota.por_outcome
    assert com_cota.com_midia >= sem_cota.com_midia


def test_cota_de_midia_impossivel_nao_estoura():
    """Corpus sem nenhuma mídia: a cota fica abaixo do alvo, e isso é informação sobre
    o corpus — não uma falha da amostragem."""
    corpus = [_caso(f"c{i}", outcome=OUTCOMES[i % 4], midia=False) for i in range(40)]
    amostra = amostragem.amostrar(corpus, n=10, seed=1)
    assert amostra.com_midia == 0
    assert len(amostra) == 10


def test_n_maior_que_o_corpus_devolve_o_corpus_inteiro():
    """`--tudo` passa por aqui: 2.500 pedidas em 2.500 disponíveis."""
    corpus = _corpus(n_por_celula=2)
    amostra = amostragem.amostrar(corpus, n=10_000, seed=1)
    assert len(amostra) == len(corpus)


def test_n_zero_devolve_amostra_vazia():
    amostra = amostragem.amostrar(_corpus(), n=0, seed=1)
    assert len(amostra) == 0 and amostra.inferencias == 0


def test_inferencias_somam_as_falas_do_lead():
    """É a unidade do custo de relógio: uma inferência por fala."""
    amostra = amostragem.amostrar(_corpus(), n=30, seed=1)
    assert amostra.inferencias == sum(c.inferencias for c in amostra.casos)


def test_amostra_grande_converge_para_a_forma_do_corpus(casos_replay):
    """Com `n` grande a proporcionalidade tem que aparecer: ~30% de incotáveis."""
    amostra = amostragem.amostrar(casos_replay, n=500, seed=3)
    incotaveis = sum(1 for c in amostra.casos if not c.cotavel)
    assert 0.25 <= incotaveis / len(amostra) <= 0.35
