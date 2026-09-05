"""O guardrail de preço.

As verificações 2 e 3 exigem cotação persistida e chegam na fatia 3. A 1 é testável
já, e é a que impede o modelo de escrever um número.
"""

import pytest

from app.agent.guardrail import (
    GuardrailViolado,
    checar_mensagem_de_cotacao,
    checar_texto_do_modelo,
)

from tests.fixtures.pii import cep_de


@pytest.mark.parametrize(
    "texto",
    [
        "fica R$ 209,90 por mês",
        "custa 209,90 reais",
        "sai por R$1.025,14",
        "uns 300 reais",
        "R$ 119",
        "o Completo fica em 392,25 por mês",
        "são 392,25/mês",
    ],
)
def test_valor_monetario_em_texto_do_modelo_e_rejeitado(texto):
    with pytest.raises(GuardrailViolado):
        checar_texto_do_modelo(texto)


@pytest.mark.parametrize(
    "texto",
    [
        "tenho 35 anos",
        "seu carro é 2019, certo?",
        "o CEP é " + cep_de("01") + "",
        "cobre colisão, roubo e furto",
        "a franquia é menor no Premium",
        "começando dia 17/10",
        "roubo e furto têm 30 dias de carência",
        "são 15 dos 31 dias do mês",
        "",
    ],
)
def test_texto_legitimo_do_agente_passa(texto):
    """Se o regex reprovar estes, o agente não consegue conversar. Este bloco vale
    tanto quanto o de cima: guardrail que impede o produto de funcionar é removido
    na primeira sexta-feira."""
    checar_texto_do_modelo(texto)


def test_a_violacao_diz_qual_trecho():
    """A linha de auditoria precisa do trecho, não só do fato."""
    with pytest.raises(GuardrailViolado) as e:
        checar_texto_do_modelo("no fim fica R$ 392,25 mesmo")
    assert e.value.trecho is not None
    assert "392" in e.value.trecho or "R$" in e.value.trecho


# ─── verificações 2 e 3 ──────────────────────────────────────────────────────

RENDER = "*Completo — R$ 392,25/mês*\nFranquia de R$ 3.000."


def test_quote_id_de_cotacao_nao_ok_e_rejeitado():
    for status in ("failed", "refused", "pending"):
        with pytest.raises(GuardrailViolado):
            checar_mensagem_de_cotacao(
                RENDER, quote_status=status, render_esperado=RENDER
            )


def test_conteudo_identico_ao_render_passa():
    checar_mensagem_de_cotacao(RENDER, quote_status="ok", render_esperado=RENDER)



@pytest.mark.parametrize(
    "adulterado",
    [
        RENDER + " :)",
        RENDER.replace("392,25", "392,20"),
        RENDER.replace("R$ 3.000", "R$ 300"),
        "Fica R$ 392,25 por mês, cobre tudo",  # paráfrase plausível
    ],
)
def test_parafrase_com_quote_id_valido_e_rejeitada(adulterado):
    """O buraco que as verificações 1 e 2 sozinhas deixariam: um texto do modelo
    com um quote_id válido colado. Só a comparação byte a byte pega."""
    with pytest.raises(GuardrailViolado):
        checar_mensagem_de_cotacao(
            adulterado, quote_status="ok", render_esperado=RENDER
        )
