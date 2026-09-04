"""Os textos determinísticos e a composição do handoff."""

from pathlib import Path

import pytest

from app import textos
from app.agent.guardrail import checar_texto_do_modelo

RAIZ = Path(__file__).resolve().parents[2]


def test_textos_batem_com_a_documentacao():
    """`docs/TEXTOS.md` é o contrato aprovado. Divergir dele é divergir de decisão
    fechada — e é a deriva mais fácil de não notar, porque nada quebra."""
    doc = _normalizar(RAIZ.joinpath("docs/TEXTOS.md").read_text())
    for nome, texto in textos.TODOS.items():
        assert _normalizar(texto) in doc, nome


def _normalizar(t: str) -> str:
    """Os textos aparecem no documento como blockquote e quebrados em várias linhas.
    A normalização remove o marcador `>` e colapsa espaço — nada mais: colapsar
    pontuação ou acento faria a comparação deixar de pegar a deriva que ela existe
    para pegar."""
    linhas = [linha.lstrip().removeprefix("> ").removeprefix(">") for linha in t.splitlines()]
    return " ".join(" ".join(linhas).split())


def test_a_normalizacao_nao_apaga_diferenca_real():
    """A própria normalização precisa de teste: se ela colapsasse demais, o teste
    acima passaria com um texto diferente do aprovado."""
    assert _normalizar("> um dois\n> três") == "um dois três"
    assert _normalizar("valor R$ 10,00") != _normalizar("valor R$ 10,10")
    assert _normalizar("nao") != _normalizar("não")


@pytest.mark.parametrize("nome,texto", sorted(textos.TODOS.items()))
def test_nenhum_texto_tem_slot_de_interpolacao(nome, texto):
    """Sem slot, a comparação byte a byte do guardrail é trivial — e nenhum valor
    monetário existe fora do bloco da cotação."""
    assert "{" not in texto and "%s" not in texto


@pytest.mark.parametrize("nome,texto", sorted(textos.TODOS.items()))
def test_nenhum_texto_tem_valor_monetario(nome, texto):
    checar_texto_do_modelo(texto)


@pytest.mark.parametrize("nome,texto", sorted(textos.TODOS.items()))
def test_nenhum_texto_promete_prazo_ou_retorno(nome, texto):
    t = texto.lower()
    for proibido in ("entraremos em contato", "vamos te ligar", "em breve",
                     "dentro de", "até amanhã", "em alguns minutos"):
        assert proibido not in t


def test_recusas_por_idade_nao_oferecem_trocar_condutor():
    """Sugerir declarar outro condutor principal é instrução para declaração falsa,
    e a conta chega como negativa de sinistro — no pior momento para o cliente."""
    for t in (textos.RECUSA_IDADE_ACIMA, textos.RECUSA_IDADE_ABAIXO):
        for proibido in ("outro condutor", "outra pessoa", "condutor principal",
                         "no nome de", "exceção", "autorização especial"):
            assert proibido not in t.lower()


def test_so_a_recusa_por_veiculo_tem_oferta():
    assert "outro carro" in textos.RECUSA_VEICULO
    assert "outro carro" not in textos.RECUSA_IDADE_ACIMA


def test_recusa_por_idade_fecha_a_porta_da_excecao():
    assert "não é algo que eu consiga contornar" in textos.RECUSA_IDADE_ACIMA


def test_despedida_nao_presume_genero():
    assert "A equipe assume" in textos.DESPEDIDA
    assert "Ele assume" not in textos.DESPEDIDA


def test_indisponibilidade_diz_a_arquitetura_ao_lead():
    assert "sem ter certeza dele" in textos.INDISPONIBILIDADE


@pytest.mark.parametrize(
    "trigger,assunto,esperado",
    [
        ("cotacao_indisponivel", None,
         textos.INDISPONIBILIDADE + "\n\n" + textos.DESPEDIDA),
        ("assunto_sensivel", "sinistro",
         textos.SENSIVEL_SINISTRO + "\n\n" + textos.DESPEDIDA),
        ("assunto_sensivel", "juridico",
         textos.SENSIVEL_JURIDICO + "\n\n" + textos.DESPEDIDA),
        ("lead_pediu", None, textos.DESPEDIDA),
        ("objecao_fora_da_alcada", None, textos.DESPEDIDA),
    ],
)
def test_composicao_prefixo_mais_despedida(trigger, assunto, esperado):
    assert textos.compor_handoff(trigger, assunto=assunto) == esperado
