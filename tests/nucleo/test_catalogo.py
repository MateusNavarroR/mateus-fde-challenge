"""O catálogo sem valor monetário."""

import os

import pytest

from app.agent.catalogo import (
    CatalogoIndisponivel,
    buscar_planos,
    carregar_catalogo,
    render_catalogo,
)

QUOTE_API = os.getenv("QUOTE_API_URL", "http://localhost:8000")


@pytest.fixture(scope="module")
def catalogo_texto():
    try:
        return carregar_catalogo(QUOTE_API)
    except CatalogoIndisponivel:
        pytest.skip(f"/planos indisponível em {QUOTE_API}")


@pytest.mark.live
@pytest.mark.parametrize(
    "proibido", ["119", "209", "339", "4500", "3000", "1500", "R$", "119,90"]
)
def test_catalogo_nao_contem_valor_monetario(catalogo_texto, proibido):
    """O que torna o guardrail absoluto em vez de heurístico: o modelo não tem
    número no contexto, então não há o que ele possa escrever."""
    assert proibido not in catalogo_texto


@pytest.mark.live
def test_catalogo_tem_nomes_e_coberturas(catalogo_texto):
    for nome in ("Essencial", "Completo", "Premium"):
        assert nome in catalogo_texto
    assert "carro_reserva" in catalogo_texto
    assert "terceiros" in catalogo_texto


@pytest.mark.live
def test_franquia_entra_como_ordem_relativa(catalogo_texto):
    """O lead pergunta "qual tem franquia menor?" e isso tem resposta sem número."""
    assert "menor franquia" in catalogo_texto
    assert "Premium tem a menor franquia" in catalogo_texto


@pytest.mark.live
def test_diz_ao_modelo_que_ele_nao_sabe_os_valores(catalogo_texto):
    assert "NÃO sabe" in catalogo_texto


@pytest.mark.live
def test_posicao_de_franquia_reflete_a_realidade():
    planos = buscar_planos(QUOTE_API)
    por_id = {p.id: p for p in planos}
    # premium 1500 < completo 3000 < essencial 4500
    assert por_id["premium"].posicao_franquia < por_id["completo"].posicao_franquia
    assert por_id["completo"].posicao_franquia < por_id["essencial"].posicao_franquia


def test_boot_falha_alto_se_planos_nao_responde():
    """Falhar alto é melhor que subir com catálogo vazio: um agente que não sabe os
    nomes dos planos conversa errado sem nenhum sinal."""
    with pytest.raises(CatalogoIndisponivel):
        buscar_planos("http://127.0.0.1:1", tentativas=1)


def test_render_nao_vaza_franquia_de_dados_arbitrarios():
    """Assere sobre o render, não sobre a API: se alguém acrescentar a franquia ao
    `Plano`, este teste é quem reprova."""
    from app.agent.catalogo import Plano

    texto = render_catalogo([
        Plano("essencial", "Essencial", ("colisao",), 1),
        Plano("premium", "Premium", ("colisao", "vidros"), 0),
    ])
    assert not any(c.isdigit() for c in texto)
