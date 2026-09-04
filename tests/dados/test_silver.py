"""A suíte da camada silver.

Cada teste aqui existe contra uma medição de `docs/API-COTACAO.md` §8.3, não contra uma
intuição: PII em 100% das conversas, timestamp fora de ordem em 99,8% delas, e 30,0% de
leads incotáveis repartidos em 280 · 531 · 60.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.privacy.mascarar import _REGRAS, contem_pii
from qa.dataset import caminhos
from qa.dataset.elegibilidade import avaliar, carregar_regras, extrair_ano_veiculo
from qa.dataset.silver import COLUNAS_MASCARADAS, construir, resumo_elegibilidade
from tests.fixtures.pii import frase_do_lead, gerar_pii

RAIZ = Path(__file__).resolve().parents[2]

#: Medido sobre o parquet do desafio com ano corrente 2026 (API-COTACAO §8.1).
ESPERADO = {"conversas": 2500, "idade": 280, "veiculo": 531, "ambos": 60, "incotaveis": 751}


def _linha(conv, idx, corpo, ts, *, idade=35, veiculo="Toyota Corolla 2018"):
    return {
        "conversation_id": conv,
        "message_index": idx,
        "timestamp": ts,
        "sender_role": "lead",
        "sender_name": "Fulano de Tal",
        "message_type": "text",
        "message_body": corpo,
        "channel": "whatsapp",
        "conversation_outcome": "ganho",
        "lead_idade_informada": idade,
        "veiculo_texto": veiculo,
    }


# ─────────────────────────────────────────────────────────────────────────────
# PII — sobre TODO o silver, não sobre amostra
# ─────────────────────────────────────────────────────────────────────────────


def test_silver_completo_nao_contem_pii(silver):
    """As cinco classes, em todas as colunas de texto, nas 26.470 linhas.

    Amostrar aqui seria o mesmo erro que a §8.3 documenta no dataset: o CPF está em
    100% das conversas, mas nada garante que o regex acerte 100% das *formas*. Só a
    varredura completa transforma "mascaramos" em fato.
    """
    problemas: list[str] = []
    for linha in silver:
        for coluna, valor in linha.items():
            if not isinstance(valor, str):
                continue
            for classe, padrao, _ in _REGRAS:
                achado = padrao.search(valor)
                if achado:
                    problemas.append(
                        f"{linha['conversation_id']}#{linha['message_index']} "
                        f"{coluna}: {classe}"
                    )
    assert not problemas, "PII no silver:\n  " + "\n  ".join(problemas[:20])


def test_a_varredura_de_pii_tem_o_que_varrer(silver):
    """Contraprova: sem isto, o teste acima passaria sobre uma lista vazia."""
    assert len(silver) > 10_000
    assert any(m in linha["message_body"] for linha in silver for m in ("[CPF]", "[CEP]"))


def test_bronze_tinha_a_pii_que_o_silver_nao_tem(bronze_linhas):
    """O mascaramento está fazendo trabalho, não recebendo texto já limpo."""
    assert any(contem_pii(l["message_body"]) for l in bronze_linhas)


def test_todas_as_colunas_de_texto_livre_passam_pelo_mascaramento():
    """Guarda contra a regressão silenciosa: alguém acrescenta uma coluna de texto ao
    silver e esquece de mascará-la. A PII vem do gerador semeado, nunca literal."""
    frase, valores = frase_do_lead(seed=2026)
    p = gerar_pii(seed=7)
    linhas = [
        _linha("conv_x", 0, frase, "2026-01-01T10:00:00", veiculo=f"Ford Ka 2018 {p['placa']}")
    ]
    linhas[0]["sender_name"] = f"Fulano {p['email']}"

    silver = construir(linhas, ano_corrente=2026)

    assert set(COLUNAS_MASCARADAS) <= set(silver[0])
    for valor in valores.values():
        assert valor not in str(silver[0])
    for coluna in COLUNAS_MASCARADAS:
        assert not contem_pii(silver[0][coluna]), coluna


def test_nenhum_arquivo_desta_suite_contem_literal_de_pii():
    """CLAUDE.md 13b, verificado no próprio diretório: os testes de dados também não
    podem carregar um valor de PII escrito à mão."""
    problemas = [
        f"{p.relative_to(RAIZ)}: {classe}"
        for p in sorted((RAIZ / "tests" / "dados").rglob("*.py"))
        for classe, padrao, _ in _REGRAS
        if padrao.search(p.read_text(encoding="utf-8"))
    ]
    assert not problemas, problemas


# ─────────────────────────────────────────────────────────────────────────────
# Ordenação — por message_index, nunca por timestamp
# ─────────────────────────────────────────────────────────────────────────────


def test_conversa_com_timestamp_fora_de_ordem_sai_por_message_index():
    """O caso que vale por 2.495 conversas: o relógio anda para trás e a ordem certa
    continua sendo a de `message_index`."""
    relogios = ["2026-03-02T09:00:00", "2026-03-01T08:00:00", "2026-03-03T07:30:00"]
    linhas = [
        _linha("conv_z", 2, "terceira", relogios[2]),
        _linha("conv_z", 0, "primeira", relogios[0]),
        _linha("conv_z", 1, "segunda", relogios[1]),
    ]

    silver = construir(linhas, ano_corrente=2026)

    assert [l["message_index"] for l in silver] == [0, 1, 2]
    assert [l["message_body"] for l in silver] == ["primeira", "segunda", "terceira"]
    # E a ordem por relógio seria outra — é o que torna o teste não trivial.
    assert sorted(relogios) != relogios
    assert silver[0]["timestamp_monotonico"] is False


def test_silver_inteiro_esta_ordenado_por_conversa_e_indice(silver):
    chaves = [(l["conversation_id"], l["message_index"]) for l in silver]
    assert chaves == sorted(chaves)


def test_o_dataset_real_tem_conversa_fora_de_ordem_e_ela_sai_ordenada(silver):
    """Os 99,8% da §8.3, confirmados no artefato em vez de citados de memória."""
    fora = {l["conversation_id"] for l in silver if not l["timestamp_monotonico"]}
    total = {l["conversation_id"] for l in silver}
    assert len(fora) / len(total) > 0.99

    alvo = sorted(fora)[0]
    mensagens = [l for l in silver if l["conversation_id"] == alvo]
    indices = [l["message_index"] for l in mensagens]
    assert indices == sorted(indices)
    assert indices == list(range(len(indices)))
    relogios = [l["timestamp"] for l in mensagens]
    assert relogios != sorted(relogios)


# ─────────────────────────────────────────────────────────────────────────────
# Elegibilidade — reproduz a medição
# ─────────────────────────────────────────────────────────────────────────────


def test_elegibilidade_reproduz_a_medicao(silver):
    assert resumo_elegibilidade(silver) == ESPERADO


def test_incotaveis_sao_30_por_cento(silver):
    r = resumo_elegibilidade(silver)
    assert round(100 * r["incotaveis"] / r["conversas"], 1) == 30.0


def test_a_fronteira_do_veiculo_e_derivada_do_ano_corrente():
    """`ano_corrente - 20`, não 2005 escrito à mão: em 2027 o limite anda sozinho."""
    regras = carregar_regras()
    assert regras.idade_veiculo_maxima == 20
    assert regras.ano_veiculo_minimo(2026) == 2006
    assert regras.ano_veiculo_minimo(2027) == 2007

    for ano_corrente, fronteira in ((2026, 2006), (2027, 2007)):
        aceito = avaliar(
            idade=35, veiculo_texto=f"Fiat Uno {fronteira}", ano_corrente=ano_corrente
        )
        recusado = avaliar(
            idade=35, veiculo_texto=f"Fiat Uno {fronteira - 1}", ano_corrente=ano_corrente
        )
        assert aceito.cotavel and not aceito.por_veiculo
        assert not recusado.cotavel and recusado.por_veiculo


def test_a_fronteira_da_idade_vem_do_plans_json():
    regras = carregar_regras()
    assert (regras.idade_minima, regras.idade_maxima) == (18, 75)
    assert avaliar(idade=75, veiculo_texto="Fiat Uno 2020", ano_corrente=2026).cotavel
    assert not avaliar(idade=76, veiculo_texto="Fiat Uno 2020", ano_corrente=2026).cotavel


def test_recusa_pelos_dois_eixos_guarda_o_motivo_da_api():
    """A `/quote` avalia a faixa etária antes da idade do veículo, então o motivo único
    é o da idade. Os dois eixos continuam marcados — é o que dá as 60 conversas."""
    v = avaliar(idade=80, veiculo_texto="Fiat Uno 1999", ano_corrente=2026)
    assert v.por_idade and v.por_veiculo
    assert str(v.motivo) == "idade_acima_do_limite"


@pytest.mark.parametrize(
    "texto,ano",
    [("Toyota Corolla 2008", 2008), ("VW Gol 1.0 2015", 2015), ("carro sem ano", None)],
)
def test_extracao_do_ano_do_veiculo(texto, ano):
    assert extrair_ano_veiculo(texto) == ano


# ─────────────────────────────────────────────────────────────────────────────
# O artefato não escapa da varredura do repositório público
# ─────────────────────────────────────────────────────────────────────────────


def test_o_destino_do_silver_e_ignorado_pelo_git():
    """CLAUDE.md 13/13a: nenhum derivado do bronze pode ser versionado.

    A defesa não é lembrar de não dar `git add`: o diretório carrega o próprio
    `.gitignore` com `*`, então `git check-ignore` o reconhece e a varredura de
    `tests/nucleo/test_repo_publico.py` nunca o encontra em `git ls-files`.
    """
    destino = caminhos.dir_saida()
    alvo = destino / "conversations_silver.parquet"
    r = subprocess.run(
        ["git", "check-ignore", "-q", str(alvo)], cwd=RAIZ, capture_output=True
    )
    assert r.returncode == 0, f"{alvo} não é ignorado pelo Git"


def test_nenhum_derivado_do_bronze_esta_versionado():
    versionados = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.split("\0")
    suspeitos = [
        p
        for p in versionados
        if p and (p.endswith(".parquet") or p.startswith("qa/_saida/silver"))
    ]
    assert not suspeitos, f"derivado do bronze versionado: {suspeitos}"


def test_parquet_materializado_nao_contem_pii_em_bytes(silver, tmp_path):
    """A varredura de `test_repo_publico` lê bytes crus e ignora erros de decodificação.
    Este teste faz o mesmo sobre o parquet gerado: se o mascaramento deixasse passar
    algo, o portão de segurança acharia — melhor achar aqui."""
    pa = pytest.importorskip("pyarrow")
    pq = pytest.importorskip("pyarrow.parquet")

    alvo = tmp_path / "silver.parquet"
    pq.write_table(pa.Table.from_pylist(silver), alvo)

    texto = alvo.read_bytes().decode("utf-8", errors="ignore")
    achados = [
        (classe, m.group(0)[:4] + "…")
        for classe, padrao, _ in _REGRAS
        for m in padrao.finditer(texto)
    ]
    assert not achados, achados[:20]
